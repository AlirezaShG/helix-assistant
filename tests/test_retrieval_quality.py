"""
Retrieval quality with the REAL embedding model (no LLM involved).

For each question, the section that answers it must be among the chunks the
document agent would hand to the LLM (top-k, above the threshold), and
questions the documents do not cover must not reach the LLM at all.

Skipped when the embedding model is not on disk yet. It is in the Docker
image; locally it is downloaded by the first `python -m app.bootstrap`.
"""

import pytest

from app.core.config import get_settings
from app.rag.vector_store import VectorStore

settings = get_settings()
model_on_disk = settings.embedding_cache_dir.exists() and any(
    "paraphrase-multilingual-MiniLM" in p.name for p in settings.embedding_cache_dir.iterdir())

pytestmark = pytest.mark.skipif(
    settings.embedding_provider != "local" or not model_on_disk,
    reason="local embedding model not downloaded (run: python -m app.bootstrap)",
)

ANSWERABLE = [
    ("How many days do customers have to return products?", "2. Standard returns"),
    ("Can a pharmacy return insulin after accepting the delivery?", "3. Cold-chain products"),
    ("What is the late payment fee for overdue invoices?", "5. Late payment"),
    ("What are the payment terms for hospitals?", "2. Payment terms by customer type"),
    ("Within how many hours must a serious adverse event be reported?", "3. Reporting timelines"),
    ("What should happen if a vaccine was above 8 degrees for 45 minutes?", "4. Handling a temperature excursion"),
    # Vector search alone ranked this section 6th; hybrid search brings it to the top.
    ("What must happen when a refrigerated product was above 8 °C for 40 minutes?",
     "4. Handling a temperature excursion"),
    ("What is the maximum transit time for inter-city deliveries?", "5. Transport"),
    ("What happens when a batch is recalled?", "6. Product recalls"),
]

UNRELATED = ["What is the capital of France?", "How do I reset my laptop password?"]


@pytest.fixture(scope="module")
def real_store(chunks, tmp_path_factory):
    from app.rag.embeddings import create_embedder

    store = VectorStore(tmp_path_factory.mktemp("real_vs"), create_embedder(settings))
    store.build(chunks, fingerprint="test")
    return store


@pytest.mark.parametrize("question, section", ANSWERABLE)
def test_answer_section_reaches_the_llm(real_store, question, section):
    hits = real_store.search(question, settings.retrieval_top_k)
    kept = [h.section for h in hits if h.score >= settings.retrieval_min_score]
    assert section in kept, f"{section!r} not in {kept}"


@pytest.mark.parametrize("question", UNRELATED)
def test_unrelated_questions_are_filtered_out(real_store, question):
    hits = real_store.search(question, settings.retrieval_top_k)
    assert all(h.score < settings.retrieval_min_score for h in hits)
