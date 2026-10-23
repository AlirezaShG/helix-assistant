"""Coordinator routing and tracing, with scripted tool calls."""

from langchain_core.messages import AIMessage

from app.agents.coordinator import Coordinator
from app.agents.document_agent import DocumentAgent, GroundedAnswer
from app.agents.sql_agent import SQLAgent, SQLDraft
from tests.fakes import FakeChatModel

SHARE_SQL = (
    "SELECT SUM(CASE WHEN c.customer_type = 'hospital' THEN oi.quantity * oi.unit_price END) AS hospital_revenue, "
    "SUM(oi.quantity * oi.unit_price) AS total_revenue "
    "FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
    "JOIN order_items oi ON oi.order_id = o.order_id "
    "WHERE o.status = 'delivered' AND o.order_date BETWEEN '2026-01-01' AND '2026-03-31'"
)


def tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_multi_step_sql_then_calculator(db_path, hash_store):
    sql_llm = FakeChatModel(structured=[SQLDraft(sql=SHARE_SQL, reason="hospital and total revenue in Q1")])
    sql_agent = SQLAgent(sql_llm, db_path)
    hospital, total = sql_agent.run("probe").rows[0]
    sql_llm.structured.append(SQLDraft(sql=SHARE_SQL, reason="hospital and total revenue in Q1"))

    expression = f"{hospital} / {total} * 100"
    coordinator_llm = FakeChatModel(replies=[
        tool_call("query_database", {"question": "Q1 2026 delivered revenue: hospitals and total"}, "call_1"),
        tool_call("calculator", {"expression": expression}, "call_2"),
        AIMessage("Hospitals generated about X% of Q1 revenue."),
    ])
    coordinator = Coordinator(coordinator_llm, DocumentAgent(FakeChatModel(), hash_store), sql_agent)

    reply = coordinator.ask("What share of Q1 revenue came from hospitals?")

    assert reply.route == ["sql_agent", "calculator"]
    assert [step.tool for step in reply.steps] == ["query_database", "calculator"]
    assert reply.steps[0].output["status"] == "ok" and reply.sql == [SHARE_SQL]
    assert reply.steps[1].output["result"] == round(hospital / total * 100, 10)
    assert reply.answer.startswith("Hospitals generated")

    last_prompt = coordinator_llm.calls[-1]
    assert any(getattr(m, "name", None) == "calculator" for m in last_prompt)


def test_document_question_routes_to_document_agent_with_sources(db_path, hash_store):
    doc_llm = FakeChatModel(structured=[GroundedAnswer(answerable=True, answer="60 days.", cited_ids=[1])])
    coordinator_llm = FakeChatModel(replies=[
        tool_call("search_documents", {"question": "payment term for hospitals"}, "call_1"),
        AIMessage("Hospitals have 60 days (Customer Credit and Payment Terms, section 2)."),
    ])
    coordinator = Coordinator(coordinator_llm, DocumentAgent(doc_llm, hash_store, min_score=0.1),
                              SQLAgent(FakeChatModel(), db_path))

    reply = coordinator.ask("What are the payment terms for hospitals?")

    assert reply.route == ["document_agent"]
    assert reply.sources and reply.sources[0]["document"] == "credit_and_payment_terms.pdf"


def test_out_of_scope_question_is_answered_without_tools(db_path, hash_store):
    coordinator_llm = FakeChatModel(replies=[AIMessage("I only answer questions about Helix.")])
    coordinator = Coordinator(coordinator_llm, DocumentAgent(FakeChatModel(), hash_store),
                              SQLAgent(FakeChatModel(), db_path))
    reply = coordinator.ask("Who won the 2022 World Cup?")
    assert reply.route == [] and reply.steps == []


def test_tool_loop_is_capped(db_path, hash_store):
    looping = [tool_call("calculator", {"expression": "1 + 1"}, f"call_{i}") for i in range(2)]
    coordinator_llm = FakeChatModel(replies=looping + [AIMessage("Stopped after the tool budget.")])
    coordinator = Coordinator(coordinator_llm, DocumentAgent(FakeChatModel(), hash_store),
                              SQLAgent(FakeChatModel(), db_path), max_tool_rounds=2)

    reply = coordinator.ask("loop forever")

    assert len(reply.steps) == 2 and reply.answer == "Stopped after the tool budget."
    assert "tool budget for this question is used up" in coordinator_llm.calls[-1][0].content
