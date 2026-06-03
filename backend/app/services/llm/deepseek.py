"""DeepSeek V4 Flash for fast chat responses."""

import json
import openai

from app.config import settings
from app.services.llm.base import BaseLLM


class DeepSeekLLM(BaseLLM):
    def __init__(self, model: str = "deepseek-v4-flash"):
        self.client = openai.AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
        )
        self.model = model

    async def generate(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                all_messages.append({"role": msg["role"], "content": content})
            elif isinstance(content, list):
                text = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
                all_messages.append({"role": msg["role"], "content": text})

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=all_messages,
            temperature=temperature,
        )
        return response.choices[0].message.content

    async def generate_structured(
        self,
        messages: list[dict],
        system_prompt: str = "",
        schema: dict | None = None,
        temperature: float = 0.7,
    ) -> dict:
        json_instruction = "\n\n重要：只输出合法 JSON，不要其他内容。"
        text = await self.generate(messages, system_prompt + json_instruction, temperature)
        text = text.strip()
        if text.startswith("```json"):
            text = text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif text.startswith("```"):
            text = text.split("```", 1)[1].rsplit("```", 1)[0]
        text = text.strip()
        # Fix trailing commas (common LLM JSON error)
        import re
        text = re.sub(r',\s*([}\]])', r'\1', text)
        return json.loads(text)

    async def embed(self, text: str) -> list[float]:
        # Use Ollama for embeddings
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:11434/api/embed",
                json={"model": "nomic-embed-text", "input": text},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
