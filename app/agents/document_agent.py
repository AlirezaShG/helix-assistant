"""
Document sub-agent: answers questions from the policy PDFs (RAG).

    question --(Persian?)--> English search query      (1 LLM call, only for Persian)
             --> hybrid search (vectors + BM25), top-k chunks
             --> drop chunks under the similarity threshold
             --> nothing left?  "not in the documents"  (LLM never called)
             --> quoted evidence + grounded answer + cited excerpt ids   (1 LLM call, structured output)
             --> keep only citations that were really retrieved

Two independent guards stop made-up answers:
  1. the similarity threshold: unrelated chunks never reach the LLM;
  2. the structured output: the model must say whether the excerpts answer the
     question (`answerable`) and which excerpts it used. An answer with no
     valid citation is treated as "not found".
In the travel-agent project, a retrieval miss was covered up by the LLM
answering from its own knowledge; these guards exist to prevent exactly that.

"Quote, then answer": the model first copies the sentences that answer the
question (`evidence`), then answers. The evaluation showed why: without it,
gpt-oss read "a 5% restocking fee applies to returns not caused by a Helix
error" next to "returns caused by a Helix error ... without a restocking fee"
and answered "no fee". Quoting first makes it read the right sentence, and the
quotes are returned to the caller as evidence.
"""

import logging
import re
import time
from dataclasses import asdict, dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.rag.vector_store import SearchHit, VectorStore

logger = logging.getLogger(__name__)

PERSIAN_CHARS = re.compile(r"[؀-ۿ]")

NOT_FOUND_EN = "The documents do not contain enough information to answer this question."
NOT_FOUND_FA = "اطلاعات کافی برای پاسخ به این سؤال در اسناد وجود ندارد."

ANSWER_PROMPT = """You answer questions about the internal policies of Helix Pharma Distribution.
Use ONLY the numbered excerpts below. Do not use outside knowledge, do not guess.

1. evidence: copy, word for word, the sentence(s) from the excerpts that answer the question.
2. If they answer it: set answerable=true and answer concisely, based only on the evidence.
   Include any condition, exception or limit the excerpts attach to the answer.
   List in cited_ids the ids of the excerpts you quoted.
3. If the excerpts do not answer it (or only partly): set answerable=false, leave answer empty.
- Do not calculate amounts for the user's own figures; state the rule (rates, deadlines) as written.
- Answer in {language}. Keep numbers, units and deadlines exactly as written.

Excerpts:
{excerpts}"""

TRANSLATE_PROMPT = (
    "Rewrite the user's question as one short English search query for a policy-document search. "
    "Keep every number and named item. Return only the query."
)


class GroundedAnswer(BaseModel):
    """Structured output the LLM must return. Field order matters: the model
    writes `evidence` before deciding and answering."""

    evidence: list[str] = Field(default_factory=list,
                                description="Sentences copied word for word from the excerpts that answer the question.")
    answerable: bool = Field(description="True only if the excerpts contain the information needed.")
    answer: str = Field(default="", description="The answer, based only on the excerpts. Empty if not answerable.")
    cited_ids: list[int] = Field(default_factory=list, description="Ids of the excerpts the answer is based on.")


@dataclass
class Source:
    document: str
    section: str
    page: int
    score: float


@dataclass
class DocumentAnswer:
    question: str
    found: bool
    answer: str
    sources: list[Source] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)  # the quoted sentences the answer rests on
    search_query: str = ""
    retrieved: list[dict] = field(default_factory=list)  # every hit with its score, for debugging

    def to_dict(self) -> dict:
        return asdict(self)


class DocumentAgent:
    def __init__(self, llm: BaseChatModel, store: VectorStore, top_k: int = 5, min_score: float = 0.30,
                 structured_output_method: str = "json_schema"):
        self.llm = llm
        self.store = store
        self.top_k = top_k
        self.min_score = min_score
        self.answerer = llm.with_structured_output(GroundedAnswer, method=structured_output_method)

    def run(self, question: str) -> DocumentAnswer:
        started = time.perf_counter()
        search_query = self._search_query(question)

        hits = self.store.search(search_query, self.top_k)
        relevant = [hit for hit in hits if hit.score >= self.min_score]
        retrieved = [{"chunk_id": h.chunk_id, "section": h.section, "score": h.score} for h in hits]
        logger.info("[document_agent] query=%r hits=%s kept=%d", search_query,
                    [(h.chunk_id, h.score) for h in hits], len(relevant))

        if not relevant:
            return self._not_found(question, search_query, retrieved, "no excerpt above the similarity threshold")

        # Excerpts are numbered 1..n; the model cites these numbers.
        excerpts = "\n\n".join(
            f"[{i}] ({hit.source}, page {hit.page}, section '{hit.section}')\n{hit.text}"
            for i, hit in enumerate(relevant, start=1)
        )
        # The answer language is decided in code: asked to "answer in the language of the
        # question", gpt-oss once answered an English question in German.
        language = "Persian" if PERSIAN_CHARS.search(question) else "English"
        try:
            result = self.answerer.invoke([
                SystemMessage(ANSWER_PROMPT.format(excerpts=excerpts, language=language)),
                HumanMessage(question),
            ])
        except ValueError as exc:  # empty or unparsable output (LangChain's and pydantic's parse errors are ValueErrors)
            logger.warning("[document_agent] unusable structured output: %s", exc)
            result = None
        if result is None:  # the model answered in prose, or not at all, instead of the required structure
            return self._not_found(question, search_query, retrieved, "the LLM returned no structured answer")

        cited = [relevant[i - 1] for i in dict.fromkeys(result.cited_ids) if 1 <= i <= len(relevant)]
        if not result.answerable or not result.answer.strip() or not cited:
            return self._not_found(question, search_query, retrieved, "the LLM found no supported answer")

        logger.info("[document_agent] answered in %.0f ms citing %s",
                    (time.perf_counter() - started) * 1000, [h.chunk_id for h in cited])
        return DocumentAnswer(
            question=question,
            found=True,
            answer=result.answer.strip(),
            sources=[_to_source(hit) for hit in cited],
            evidence=[quote.strip() for quote in result.evidence if quote.strip()],
            search_query=search_query,
            retrieved=retrieved,
        )

    def _search_query(self, question: str) -> str:
        """The documents are in English. The embedding model is multilingual, but
        a Persian question still matches better once translated, so Persian
        questions get one short rewrite call (the same idea as rewrite_query in
        the Persian legal RAG graph)."""
        if not PERSIAN_CHARS.search(question):
            return question
        response = self.llm.invoke([SystemMessage(TRANSLATE_PROMPT), HumanMessage(question)])
        return str(response.content).strip() or question

    def _not_found(self, question: str, search_query: str, retrieved: list[dict], reason: str) -> DocumentAnswer:
        logger.info("[document_agent] not found: %s", reason)
        message = NOT_FOUND_FA if PERSIAN_CHARS.search(question) else NOT_FOUND_EN
        return DocumentAnswer(question=question, found=False, answer=message,
                              search_query=search_query, retrieved=retrieved)


def _to_source(hit: SearchHit) -> Source:
    return Source(document=hit.source, section=hit.section, page=hit.page, score=hit.score)
