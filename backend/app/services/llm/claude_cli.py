"""LLM implementation using the Claude CLI (claude -p)."""

import asyncio
import json

from google import genai

from app.config import settings
from app.services.llm.base import BaseLLM


class ClaudeCliLLM(BaseLLM):
    def __init__(self, model: str = ""):
        if settings.gemini_api_key:
            self.gemini = genai.Client(api_key=settings.gemini_api_key)
        else:
            self.gemini = None
        self.last_cost_usd: float = 0.0
        self.last_duration_ms: int = 0

    async def _run_claude(self, prompt: str, system_prompt: str = "") -> str:
        """Run claude CLI and return the result text. Updates last_cost_usd and last_duration_ms."""
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{full_prompt}"

        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", full_prompt,
            "--output-format", "json",
            "--max-turns", "1",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {stderr.decode()}")

        output = json.loads(stdout.decode())
        self.last_cost_usd = output.get("total_cost_usd", 0.0)
        self.last_duration_ms = output.get("duration_ms", 0)
        return output.get("result", "")

    async def generate(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        user_text = ""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_text += content + "\n"
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            user_text += part["text"] + "\n"
        return await self._run_claude(user_text.strip(), system_prompt)

    async def generate_structured(
        self,
        messages: list[dict],
        system_prompt: str = "",
        schema: dict | None = None,
        temperature: float = 0.7,
    ) -> dict:
        json_instruction = "\n\n重要：你必须只输出合法的 JSON，不要输出任何其他内容，不要用 markdown 代码块包裹。"
        last_err: Exception | None = None
        for attempt in range(3):
            text = await self.generate(messages, system_prompt + json_instruction, temperature)
            text = text.strip()
            if text.startswith("```json"):
                text = text.split("```json", 1)[1].rsplit("```", 1)[0]
            elif text.startswith("```"):
                text = text.split("```", 1)[1].rsplit("```", 1)[0]
            try:
                return json.loads(text.strip())
            except json.JSONDecodeError as e:
                last_err = e
        raise last_err

    async def embed(self, text: str) -> list[float]:
        """Use local Ollama for embeddings."""
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:11434/api/embed",
                json={"model": "nomic-embed-text", "input": text},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
