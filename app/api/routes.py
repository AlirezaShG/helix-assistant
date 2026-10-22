"""
HTTP endpoints.

    POST /api/v1/ask             the full assistant (coordinator + sub-agents + calculator)
    POST /api/v1/documents/ask   the document sub-agent alone (RAG)
    POST /api/v1/sql/ask         the SQL sub-agent alone (NL2SQL; returns SQL + rows)
    GET  /api/v1/health          readiness of the index, the database and the LLM config

Convention: the HTTP status describes the *request* (422 invalid input, 503 not
configured, 502 provider failure ...). The outcome of a valid question, such
as "not found in the documents" or "query rejected as unsafe", is a normal 200
answer with `found` / `status` saying so.

The handlers are plain `def` functions: FastAPI runs them in a thread pool,
so the blocking LLM calls do not freeze the server.
"""

from fastapi import APIRouter, Depends, Request

from app.api.schemas import AskResponse, DocumentResponse, QuestionRequest, SQLResponse
from app.services import Services

router = APIRouter()


def get_services(request: Request) -> Services:
    return request.app.state.services


@router.get("/health")
def health(services: Services = Depends(get_services)) -> dict:
    settings = services.settings
    return {
        "status": "ok" if services.store is not None else "degraded",
        "documents_indexed": services.store.count() if services.store else 0,
        "database_ready": settings.database_path.exists(),
        "llm_configured": bool(settings.llm_api_key),
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "startup_error": services.startup_error,
    }


@router.post("/ask", response_model=AskResponse)
def ask(body: QuestionRequest, services: Services = Depends(get_services)) -> dict:
    return services.coordinator.ask(body.question).to_dict()


@router.post("/documents/ask", response_model=DocumentResponse)
def ask_documents(body: QuestionRequest, services: Services = Depends(get_services)) -> dict:
    return services.document_agent.run(body.question).to_dict()


@router.post("/sql/ask", response_model=SQLResponse)
def ask_sql(body: QuestionRequest, services: Services = Depends(get_services)) -> dict:
    return services.sql_agent.run(body.question).to_dict()
