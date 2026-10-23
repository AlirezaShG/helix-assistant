"""HTTP endpoints."""

from fastapi import APIRouter, Depends, Request

from app.api.schemas import AskResponse, DocumentResponse, QuestionRequest, SQLResponse
from app.core.llm import is_local
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
        "llm_configured": bool(settings.llm_api_key) or is_local(settings.llm_base_url),
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
