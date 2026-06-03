import json

import anthropic

from app.services.llm.base import BaseLLM


class AnthropicLLM(BaseLLM):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def generate(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            temperature=temperature,
        )
        return response.content[0].text

    async def generate_structured(
        self,
        messages: list[dict],
        system_prompt: str = "",
        schema: dict | None = None,
        temperature: float = 0.7,
    ) -> dict:
        prompt_suffix = ""
        if schema:
            prompt_suffix = (
                f"\n\nRespond with valid JSON matching this schema:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt + prompt_suffix,
            messages=messages,
            temperature=temperature,
        )
        text = response.content[0].text
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())

    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Anthropic does not provide embeddings. "
            "Use OpenAI or another provider for embeddings."
        )
