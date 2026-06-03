import json

import openai

from app.services.llm.base import BaseLLM


class OpenAILLM(BaseLLM):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.client = openai.AsyncOpenAI(api_key=api_key)
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
        all_messages.extend(messages)

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
        all_messages = []
        suffix = ""
        if schema:
            suffix = (
                f"\n\nRespond with valid JSON matching this schema:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
        if system_prompt or suffix:
            all_messages.append({"role": "system", "content": system_prompt + suffix})
        all_messages.extend(messages)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=all_messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    async def embed(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
