"""HTTP layer: input validation, error mapping and response shape."""

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app.agents.coordinator import AssistantReply, Step
from app.core.llm import LLMNotConfiguredError
from app.main import app


class StubServices:
    def __init__(self, coordinator=None, error: Exception | None = None):
        self._coordinator = coordinator
        self._error = error

    @property
    def coordinator(self):
        if self._error:
            raise self._error
        return self._coordinator


class StubCoordinator:
    def ask(self, question):
        return AssistantReply(
            answer=f"echo: {question}",
            route=["calculator"],
            steps=[Step(agent="calculator", tool="calculator", input={"expression": "1+1"}, output={"result": 2})],
        )


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_ask_returns_answer_and_trace(client):
    app.state.services = StubServices(StubCoordinator())
    response = client.post("/api/v1/ask", json={"question": "  what   is 1+1?  "})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "echo: what is 1+1?"  # whitespace normalised by validation
    assert body["route"] == ["calculator"] and body["steps"][0]["output"] == {"result": 2}


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "  "}, {"question": "x" * 1001}, {"q": "hi"}])
def test_invalid_input_is_rejected_with_422(client, payload):
    app.state.services = StubServices(StubCoordinator())
    assert client.post("/api/v1/ask", json=payload).status_code == 422


def test_missing_api_key_gives_503(client):
    app.state.services = StubServices(error=LLMNotConfiguredError("LLM_API_KEY is not set."))
    response = client.post("/api/v1/ask", json={"question": "hello there"})
    assert response.status_code == 503 and "LLM_API_KEY" in response.json()["error"]


def test_provider_auth_error_gives_502(client):
    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")
    error = openai.AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)
    app.state.services = StubServices(error=error)
    response = client.post("/api/v1/ask", json={"question": "hello there"})
    assert response.status_code == 502 and "API key" in response.json()["error"]


def test_unexpected_error_gives_500_without_details(client):
    app.state.services = StubServices(error=RuntimeError("secret internal detail"))
    response = client.post("/api/v1/ask", json={"question": "hello there"})
    assert response.status_code == 500 and "secret" not in response.text
