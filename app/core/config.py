"""
Application settings.

Every field below can be overridden by an environment variable with the same
name in upper case (e.g. `LLM_MODEL=gpt-4o`) or by a line in `.env`.
Keeping every knob in one class makes it easy to see what the system depends on.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/core/config.py -> parents[2] is the repository root.
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Helix Assistant API"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # --- LLM -----------------------------------------------------------------
    # Any OpenAI-compatible endpoint works (OpenAI, AvalAI, OpenRouter, vLLM,
    # Ollama ...): switching provider is only a matter of these three values.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    # "low" | "medium" | "high" for reasoning models (gpt-oss, OpenAI o-series). Empty = the provider's
    # default, and the parameter is not sent at all: non-reasoning models such as gpt-4o-mini reject it.
    # The evaluation found gpt-oss:20b misreading one policy rule at its default effort and getting it
    # right 3/3 times at "high", with no measurable extra latency.
    llm_reasoning_effort: str = ""
    # How the sub-agents get structured answers ({sql, reason}, {answerable, answer, cited_ids}):
    # "json_schema"      -> the server constrains generation to the JSON schema, so the output
    #                       always parses. Supported by OpenAI, Ollama, LM Studio, vLLM.
    # "function_calling" -> the answer comes back as a forced tool call; for providers without
    #                       response_format support. (gpt-oss on Ollama occasionally wrote
    #                       malformed tool-call JSON this way, hence json_schema by default.)
    llm_structured_output: str = "json_schema"

    # --- Embeddings ----------------------------------------------------------
    # "local"  -> fastembed (ONNX, CPU only, no API calls). The model is baked
    #             into the Docker image at build time.
    # "openai" -> the /embeddings endpoint of the same provider as the LLM.
    #             Set EMBEDDING_MODEL to e.g. text-embedding-3-small as well.
    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_cache_dir: Path = ROOT_DIR / "models"

    # --- Data locations ------------------------------------------------------
    documents_dir: Path = ROOT_DIR / "data" / "documents"
    vector_store_dir: Path = ROOT_DIR / "data" / "vector_store"
    database_path: Path = ROOT_DIR / "data" / "database" / "helix.db"

    # --- RAG -----------------------------------------------------------------
    chunk_max_chars: int = 900
    retrieval_top_k: int = 5
    # Cosine similarity below this means "not about the question"; such chunks
    # never reach the LLM. Calibrated with the default model on 15 questions:
    # unrelated questions score <= 0.16, near-domain ones the documents do not
    # cover (leave policy, dress code) 0.31-0.35, and the best hit of every
    # answerable question >= 0.41 (some relevant chunks rank lower, ~0.37).
    # The cut-off sits below the relevant range; borderline cases are left to
    # the LLM's `answerable` check (see app/agents/document_agent.py).
    retrieval_min_score: float = 0.30

    # --- NL2SQL --------------------------------------------------------------
    sql_max_rows: int = 200
    sql_timeout_seconds: float = 3.0
    sql_max_attempts: int = 2  # first try + one self-correction from the DB error

    # --- Coordinator ---------------------------------------------------------
    agent_max_tool_rounds: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
