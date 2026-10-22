"""
Creates the long-lived objects once and hands them to the API.

Data preparation happens when the app starts. Everything that needs the LLM is
created lazily, on first use: the API therefore starts, and /health answers,
even before an API key is configured. A request that needs the LLM then gets a
clear 503 instead of the whole service failing to boot.
"""

import logging
from functools import cached_property

from app.agents.coordinator import Coordinator
from app.agents.document_agent import DocumentAgent
from app.agents.sql_agent import SQLAgent
from app.bootstrap import prepare_data
from app.core.config import Settings
from app.core.llm import create_chat_model
from app.rag.embeddings import create_embedder
from app.rag.vector_store import IndexNotReadyError, VectorStore

logger = logging.getLogger(__name__)


class Services:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store: VectorStore | None = None
        self.startup_error: str | None = None
        try:
            self.store = prepare_data(settings, create_embedder(settings))
        except Exception as exc:  # keep the API up; /health and the 503 handler report the problem
            logger.exception("Document index could not be prepared")
            self.startup_error = f"{type(exc).__name__}: {exc}"

    @cached_property
    def llm(self):
        return create_chat_model(self.settings)

    @cached_property
    def document_agent(self) -> DocumentAgent:
        if self.store is None:
            raise IndexNotReadyError(f"The document index is not available ({self.startup_error}).")
        s = self.settings
        return DocumentAgent(self.llm, self.store, s.retrieval_top_k, s.retrieval_min_score, s.llm_structured_output)

    @cached_property
    def sql_agent(self) -> SQLAgent:
        s = self.settings
        return SQLAgent(self.llm, s.database_path, s.sql_max_rows, s.sql_timeout_seconds, s.sql_max_attempts,
                        s.llm_structured_output)

    @cached_property
    def coordinator(self) -> Coordinator:
        return Coordinator(self.llm, self.document_agent, self.sql_agent, self.settings.agent_max_tool_rounds)
