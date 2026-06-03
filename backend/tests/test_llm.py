import pytest

from app.services.llm.base import BaseLLM
from app.services.llm.factory import create_llm


def test_base_llm_is_abstract():
    with pytest.raises(TypeError):
        BaseLLM()


def test_factory_creates_anthropic(monkeypatch):
    monkeypatch.setenv("NOMI_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("NOMI_ANTHROPIC_API_KEY", "test-key")
    from app.services.llm.anthropic import AnthropicLLM

    llm = create_llm("anthropic", anthropic_api_key="test-key")
    assert isinstance(llm, AnthropicLLM)


def test_factory_creates_openai(monkeypatch):
    from app.services.llm.openai import OpenAILLM

    llm = create_llm("openai", openai_api_key="test-key")
    assert isinstance(llm, OpenAILLM)


def test_factory_raises_for_unknown():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_llm("unknown")
