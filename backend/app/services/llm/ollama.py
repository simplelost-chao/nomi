"""Fast local LLM via Ollama for chat responses."""

import json
import httpx

from app.services.llm.base import BaseLLM

OLLAMA_URL = "http://localhost:11434"


class OllamaLLM(BaseLLM):
    def __init__(self, model: str = "qwen2.5:7b"):
        self.model = model

    async def generate(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        ollama_messages = []
        if system_prompt:
            ollama_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                ollama_messages.append({"role": msg["role"], "content": content})
            elif isinstance(content, list):
                text = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
                ollama_messages.append({"role": msg["role"], "content": text})

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": self.model, "messages": ollama_messages, "stream": False},
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]

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
        return json.loads(text.strip())

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": "nomic-embed-text", "input": text},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
