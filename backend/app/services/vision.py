"""Vision service using Gemini for image recognition."""

import json
import httpx
from google import genai
from google.genai import types

from app.config import settings
from app.prompts.creation import build_object_identify_prompt


class VisionService:
    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key)

    async def identify_object(
        self,
        image_bytes: bytes | None = None,
        image_url: str | None = None,
        text_hint: str | None = None,
    ) -> dict:
        """Identify and describe an object from an image using Gemini."""

        system, user_msg = build_object_identify_prompt()

        if text_hint:
            user_msg += f"\n\n用户补充说明：{text_hint}"

        contents = []

        # Add image
        if image_bytes:
            contents.append(types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=image_bytes)))
        elif image_url:
            async with httpx.AsyncClient() as http:
                resp = await http.get(image_url)
                resp.raise_for_status()
                mime = resp.headers.get("content-type", "image/jpeg")
                contents.append(types.Part(inline_data=types.Blob(mime_type=mime, data=resp.content)))

        # Add text
        contents.append(types.Part(text=user_msg))

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.7,
            ),
        )

        text = response.text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
