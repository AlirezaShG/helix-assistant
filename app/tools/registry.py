"""
The three tools the coordinator can call.

Two of them wrap a sub-agent, one is a plain function:

    search_documents  -> DocumentAgent (RAG over the policy PDFs)
    query_database    -> SQLAgent      (NL2SQL over the sales database)
    calculator        -> calculate()   (safe arithmetic)

The docstrings are not just documentation: LangChain sends them to the LLM as
the tool descriptions, and the LLM picks a tool by reading them. That is how
the routing works, so they say precisely what each tool knows about.

Every tool returns JSON. Expected failures (nothing found, unsafe SQL,
division by zero ...) come back as JSON with an "error" field, so the
coordinator can explain them. Unexpected failures (e.g. the LLM provider is
down) are raised and reach the API's error handlers.
"""

import json
import logging
import time

from langchain_core.tools import BaseTool, tool

from app.agents.document_agent import DocumentAgent
from app.agents.sql_agent import SQLAgent
from app.rag.vector_store import IndexNotReadyError
from app.tools.calculator import CalculatorError, calculate

logger = logging.getLogger(__name__)

# Which component each tool belongs to; used in the logs and in the API's "route" field.
AGENT_FOR_TOOL = {
    "search_documents": "document_agent",
    "query_database": "sql_agent",
    "calculator": "calculator",
}

ROWS_SHOWN_TO_LLM = 20  # enough for any summary; keeps the prompt small


def _to_json(payload: dict, started: float) -> str:
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return json.dumps(payload, ensure_ascii=False, default=str)


def build_tools(document_agent: DocumentAgent, sql_agent: SQLAgent) -> list[BaseTool]:
    @tool
    def search_documents(question: str) -> str:
        """Answer a question from Helix's internal policy documents (PDF): returns, credit notes and
        product recalls; cold-chain storage and transport; customer credit limits, payment terms and
        late fees; adverse-event and quality-complaint reporting. Use it for rules, deadlines,
        percentages and procedures. Pass one self-contained question. Returns JSON with
        found (true/false), answer and sources."""
        started = time.perf_counter()
        logger.info("[coordinator] -> document_agent: %r", question)
        try:
            result = document_agent.run(question).to_dict()
        except IndexNotReadyError as exc:
            result = {"found": False, "error": str(exc)}
        result.pop("retrieved", None)  # debugging detail, not needed by the LLM
        return _to_json(result, started)

    @tool
    def query_database(question: str) -> str:
        """Answer a question about Helix's sales data by generating and running a read-only SQL query.
        The database has products, customers (pharmacies, hospitals, clinics in 5 cities), orders
        (Jan-Sep 2026, with status and payment status) and order items (quantities and prices in IRR).
        Pass a precise natural-language question, not SQL. Returns JSON with status, sql, columns
        and rows."""
        started = time.perf_counter()
        logger.info("[coordinator] -> sql_agent: %r", question)
        result = sql_agent.run(question).to_dict()
        if len(result["rows"]) > ROWS_SHOWN_TO_LLM:
            result["rows"] = result["rows"][:ROWS_SHOWN_TO_LLM]
            result["note"] = f"only the first {ROWS_SHOWN_TO_LLM} of {result['row_count']} rows are shown"
        return _to_json(result, started)

    @tool
    def calculator(expression: str) -> str:
        """Evaluate an arithmetic expression exactly, e.g. '(1520000 - 1340000) / 1340000 * 100'.
        Supports + - * / // % ** and parentheses, and the functions abs, round, min, max, sqrt.
        Use it for every percentage, ratio, difference, average or fee instead of computing yourself."""
        started = time.perf_counter()
        logger.info("[coordinator] -> calculator: %r", expression)
        try:
            payload = {"expression": expression, "result": calculate(expression)}
        except CalculatorError as exc:
            payload = {"expression": expression, "error": str(exc)}
        return _to_json(payload, started)

    return [search_documents, query_database, calculator]
