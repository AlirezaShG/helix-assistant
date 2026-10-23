"""Application settings."""

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

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 180.0
    llm_max_retries: int = 2
    llm_reasoning_effort: str = ""
    llm_structured_output: str = "json_schema"

    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_cache_dir: Path = ROOT_DIR / "models"

    documents_dir: Path = ROOT_DIR / "data" / "documents"
    vector_store_dir: Path = ROOT_DIR / "data" / "vector_store"
    database_path: Path = ROOT_DIR / "data" / "database" / "helix.db"

    chunk_max_chars: int = 900
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.30

    sql_max_rows: int = 200
    sql_timeout_seconds: float = 3.0
    sql_max_attempts: int = 2

    agent_max_tool_rounds: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
