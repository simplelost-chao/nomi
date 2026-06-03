from app.services.llm.base import BaseLLM


def create_llm(provider: str, **kwargs) -> BaseLLM:
    if provider == "anthropic":
        from app.services.llm.anthropic import AnthropicLLM

        return AnthropicLLM(api_key=kwargs.get("anthropic_api_key", ""))
    elif provider == "openai":
        from app.services.llm.openai import OpenAILLM

        return OpenAILLM(api_key=kwargs.get("openai_api_key", ""))
    elif provider == "claude-cli":
        from app.services.llm.claude_cli import ClaudeCliLLM

        return ClaudeCliLLM()
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
