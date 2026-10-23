"""The model factory: it should work with local servers and cloud models without per-model code."""

import pytest

from app.core.config import Settings
from app.core.llm import LLMNotConfiguredError, create_chat_model


def make(**overrides):
    return create_chat_model(Settings(_env_file=None, **overrides))


def test_remote_provider_without_key_is_rejected():
    with pytest.raises(LLMNotConfiguredError):
        make(llm_api_key="", llm_base_url="https://api.openai.com/v1")


@pytest.mark.parametrize("url", ["http://localhost:11434/v1", "http://host.docker.internal:1234/v1"])
def test_local_server_needs_no_key(url):
    assert make(llm_api_key="", llm_base_url=url, llm_model="qwen2.5:7b").openai_api_key is not None


@pytest.mark.parametrize("model", ["o3-mini", "o4-mini", "gpt-5", "openai/gpt-5-mini", "openai/o1"])
def test_reasoning_models_get_no_temperature(model):
    assert make(llm_api_key="k", llm_model=model).temperature is None


@pytest.mark.parametrize("model", ["gpt-4o-mini", "gpt-oss:20b", "openai/gpt-4o", "gpt-5-chat-latest"])
def test_other_models_keep_temperature_zero(model):
    assert make(llm_api_key="k", llm_model=model).temperature == 0.0
