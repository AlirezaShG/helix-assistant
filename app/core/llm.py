"""
Creates the chat model and turns provider failures into readable messages.

LangChain's ChatOpenAI speaks the OpenAI protocol, which most providers expose,
so the rest of the code never needs to know which provider is behind it.
"""

import openai
from langchain_openai import ChatOpenAI

from app.core.config import Settings


class LLMNotConfiguredError(RuntimeError):
    """Raised when a request needs the LLM but LLM_API_KEY is empty."""


def create_chat_model(settings: Settings) -> ChatOpenAI:
    if not settings.llm_api_key:
        raise LLMNotConfiguredError(
            "LLM_API_KEY is not set. Copy .env.example to .env and fill in your key."
        )
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def describe_llm_error(exc: openai.OpenAIError) -> tuple[int, str]:
    """Map an OpenAI SDK exception to (HTTP status, message for the API caller).

    The order matters: the specific classes are subclasses of APIStatusError
    or APIConnectionError, so they are checked first.
    """
    if isinstance(exc, openai.AuthenticationError):
        return 502, "The LLM provider rejected the API key (check LLM_API_KEY / LLM_BASE_URL)."
    if isinstance(exc, openai.NotFoundError):
        return 502, "The LLM provider does not know this model (check LLM_MODEL)."
    if isinstance(exc, openai.RateLimitError):
        return 503, "The LLM provider is rate-limiting us or the quota is exhausted. Try again later."
    if isinstance(exc, openai.APITimeoutError):
        return 504, "The LLM provider did not answer in time."
    if isinstance(exc, openai.APIConnectionError):
        return 502, "Could not reach the LLM provider (network or LLM_BASE_URL problem)."
    if isinstance(exc, openai.APIStatusError):
        return 502, f"The LLM provider returned HTTP {exc.status_code}."
    return 502, "The LLM call failed."
