from abc import ABC, abstractmethod


class BaseLLM(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        """Free-form text generation. Returns the assistant's response text."""

    @abstractmethod
    async def generate_structured(
        self,
        messages: list[dict],
        system_prompt: str = "",
        schema: dict | None = None,
        temperature: float = 0.7,
    ) -> dict:
        """Structured JSON output. Returns parsed dict matching schema."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Text to vector embedding."""
