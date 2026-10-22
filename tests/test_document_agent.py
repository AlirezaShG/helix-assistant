"""Document agent: grounded answers with citations, and the two not-found guards."""

from langchain_core.messages import AIMessage

from app.agents.document_agent import NOT_FOUND_EN, NOT_FOUND_FA, DocumentAgent, GroundedAnswer
from tests.fakes import FakeChatModel


def test_answer_is_grounded_and_cites_the_retrieved_section(hash_store):
    llm = FakeChatModel(structured=[GroundedAnswer(answerable=True, answer="1.5% per month.", cited_ids=[1])])
    agent = DocumentAgent(llm, hash_store, top_k=3, min_score=0.1)

    result = agent.run("What is the late payment fee on overdue invoices?")

    assert result.found and result.answer == "1.5% per month."
    assert result.sources[0].section == "5. Late payment"
    excerpts_shown_to_llm = llm.calls[0][0].content
    assert "[1] (credit_and_payment_terms.pdf, page 1, section '5. Late payment')" in excerpts_shown_to_llm


def test_unrelated_question_never_reaches_the_llm(hash_store):
    llm = FakeChatModel()  # no scripted answers: any LLM call would fail the test
    agent = DocumentAgent(llm, hash_store, top_k=3, min_score=0.3)

    result = agent.run("What is the capital of France?")

    assert not result.found and result.answer == NOT_FOUND_EN and result.sources == []
    assert llm.calls == []


def test_llm_saying_not_answerable_gives_not_found(hash_store):
    llm = FakeChatModel(structured=[GroundedAnswer(answerable=False)])
    agent = DocumentAgent(llm, hash_store, min_score=0.0)
    assert not agent.run("What is the annual leave policy?").found


def test_prose_instead_of_structure_gives_not_found(hash_store):
    llm = FakeChatModel(structured=[None])  # the model ignored the required structure
    agent = DocumentAgent(llm, hash_store, min_score=0.0)
    assert not agent.run("payment terms for pharmacies").found


def test_answer_without_a_valid_citation_is_not_trusted(hash_store):
    # The model claims an answer but cites an excerpt id that does not exist.
    llm = FakeChatModel(structured=[GroundedAnswer(answerable=True, answer="30 days", cited_ids=[99])])
    agent = DocumentAgent(llm, hash_store, min_score=0.0)
    assert not agent.run("payment terms for pharmacies").found


def test_persian_question_is_translated_for_search_and_answered_in_persian(hash_store):
    llm = FakeChatModel(
        replies=[AIMessage("late payment fee overdue invoices")],  # the translation call
        structured=[GroundedAnswer(answerable=True, answer="۱.۵ درصد در ماه", cited_ids=[1])],
    )
    agent = DocumentAgent(llm, hash_store, top_k=3, min_score=0.1)

    result = agent.run("جریمه دیرکرد پرداخت چقدر است؟")

    assert result.search_query == "late payment fee overdue invoices"
    assert result.found and result.sources[0].section == "5. Late payment"


def test_not_found_message_follows_the_question_language(hash_store):
    llm = FakeChatModel(replies=[AIMessage("capital of france")])
    agent = DocumentAgent(llm, hash_store, min_score=0.9)
    assert agent.run("پایتخت فرانسه کجاست؟").answer == NOT_FOUND_FA
