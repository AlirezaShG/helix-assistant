"""Coordinator: decides which sub-agent / tool each question needs."""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from app.agents.document_agent import PERSIAN_CHARS, DocumentAgent
from app.agents.sql_agent import SQLAgent
from app.tools.registry import AGENT_FOR_TOOL, build_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the internal assistant of Helix Pharma Distribution, a pharmaceutical distributor.
Today's date is {today}.

You have three tools:
- search_documents: the internal policy documents (returns and recalls, cold-chain storage and transport,
  customer credit and payment terms, adverse-event reporting).
- query_database: the sales database (products, customers, orders, order items; January to September 2026).
- calculator: exact arithmetic.

Rules:
1. You know nothing about Helix except what the tools return. For any question about Helix's policies or
   data, call a tool. Never answer such questions from general knowledge.
2. Rules, deadlines and procedures -> search_documents. Figures about sales, orders, customers or
   products -> query_database. Some questions need both; call both. Any question about a Helix rule,
   policy or procedure goes to search_documents even if its topic is not in the list above: only the
   tool can tell whether the documents cover it.
3. Use query_database to fetch raw figures. Do every further computation (percentage, ratio, difference,
   average of returned values, a fee or discount applied to an amount) with the calculator, never in your
   head, using the exact numbers returned or given by the user.
4. If search_documents returns found=false, say that the documents do not contain this information.
   Do not fill the gap with assumptions.
5. If a tool returns an error or status other than "ok", explain briefly what went wrong. Never invent numbers.
6. The database is read-only. Requests to add, change or delete data are refused.
7. If the question has nothing to do with Helix (general knowledge, coding, chit-chat), say that you only
   answer questions about Helix's policies and sales data, without calling tools.
8. Answer in {language}, the language of the question, concisely. For policy facts name the document
   and section. Write money with thousands separators and the unit IRR."""

FINAL_ROUND_NOTE = "\n\nThe tool budget for this question is used up. Answer now with the information you have."


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


@dataclass
class Step:
    agent: str
    tool: str
    input: dict
    output: dict


@dataclass
class AssistantReply:
    answer: str
    route: list[str] = field(default_factory=list)  # components used, in call order
    steps: list[Step] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)  # cited document sections
    sql: list[str] = field(default_factory=list)  # every executed query
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class Coordinator:
    def __init__(self, llm: BaseChatModel, document_agent: DocumentAgent, sql_agent: SQLAgent,
                 max_tool_rounds: int = 6):
        self.max_tool_rounds = max_tool_rounds
        tools = build_tools(document_agent, sql_agent)
        self.llm_with_tools = llm.bind_tools(tools)
        self.llm_answer_only = llm.bind_tools(tools, tool_choice="none")

        graph = StateGraph(AgentState)
        graph.add_node("reasoner", self._reasoner)
        graph.add_node("tools", ToolNode(tools))
        graph.add_edge(START, "reasoner")
        graph.add_conditional_edges("reasoner", tools_condition)  # tool calls -> "tools", else -> END
        graph.add_edge("tools", "reasoner")
        self.graph = graph.compile()

    def _reasoner(self, state: AgentState) -> dict:
        question = str(state["messages"][0].content)
        language = "Persian" if PERSIAN_CHARS.search(question) else "English"
        system = SYSTEM_PROMPT.format(today=date.today().isoformat(), language=language)
        rounds_used = sum(1 for m in state["messages"] if isinstance(m, AIMessage) and m.tool_calls)
        if rounds_used >= self.max_tool_rounds:
            reply = self.llm_answer_only.invoke([SystemMessage(system + FINAL_ROUND_NOTE)] + state["messages"])
        else:
            reply = self.llm_with_tools.invoke([SystemMessage(system)] + state["messages"])
        for call in reply.tool_calls:
            logger.info("[coordinator] route -> %s (%s) args=%s",
                        AGENT_FOR_TOOL.get(call["name"], "?"), call["name"], call["args"])
        return {"messages": [reply]}

    def ask(self, question: str) -> AssistantReply:
        started = time.perf_counter()
        final_state = self.graph.invoke(
            {"messages": [HumanMessage(question)]},
            config={"recursion_limit": 2 * self.max_tool_rounds + 5},
        )
        reply = _summarise(final_state["messages"])
        reply.elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.info("[coordinator] done in %d ms, route=%s", reply.elapsed_ms, reply.route)
        return reply


def _summarise(messages: list[BaseMessage]) -> AssistantReply:
    """Rebuild the trace from the conversation: pair each tool call with its result."""
    calls = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                calls[call["id"]] = call

    reply = AssistantReply(answer=str(messages[-1].content).strip())
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        call = calls.get(message.tool_call_id, {"name": message.name, "args": {}})
        try:
            output = json.loads(message.content)
        except (TypeError, json.JSONDecodeError):
            output = {"raw": str(message.content)}

        agent = AGENT_FOR_TOOL.get(call["name"], call["name"])
        reply.steps.append(Step(agent=agent, tool=call["name"], input=call["args"], output=output))
        if agent not in reply.route:
            reply.route.append(agent)
        reply.sources.extend(output.get("sources") or [])
        if output.get("status") == "ok" and output.get("sql"):
            reply.sql.append(output["sql"])
    return reply
