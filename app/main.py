"""
FastAPI application: startup, logging, routes and error handling.

Start it with:  uvicorn app.main:app --reload
Interactive API docs: http://localhost:8000/docs
"""

import logging
import time
from contextlib import asynccontextmanager

import openai
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.llm import LLMNotConfiguredError, describe_llm_error
from app.rag.vector_store import IndexNotReadyError
from app.services import Services

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")
for noisy in ("httpx", "httpx2"):  # one line per LLM HTTP call is noise
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Builds the database and the vector index if needed (a few seconds; already
    # done at image build time in Docker).
    app.state.services = Services(settings)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    logger.info("%s %s -> %d (%.0f ms)", request.method, request.url.path,
                response.status_code, (time.perf_counter() - started) * 1000)
    return response


# ---- error handling ---------------------------------------------------------
# Each known failure becomes a JSON error with a clear message and a fitting
# HTTP status. Nothing leaks a stack trace to the caller.

@app.exception_handler(LLMNotConfiguredError)
async def llm_not_configured(_: Request, exc: LLMNotConfiguredError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": str(exc)})


@app.exception_handler(openai.OpenAIError)
async def llm_failed(_: Request, exc: openai.OpenAIError) -> JSONResponse:
    status_code, message = describe_llm_error(exc)
    logger.error("LLM call failed: %s: %s", type(exc).__name__, exc)
    return JSONResponse(status_code=status_code, content={"error": message})


@app.exception_handler(IndexNotReadyError)
async def index_not_ready(_: Request, exc: IndexNotReadyError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": str(exc)})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "Internal error. The details are in the server log."})
