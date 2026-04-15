"""
AI client supporting OpenRouter and DeepSeek providers.
Both expose an OpenAI-compatible /chat/completions endpoint.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator

import httpx

from config.settings import Settings


class AIClient:
    def __init__(self, settings: Settings):
        self._setup(settings)
        self._http = httpx.AsyncClient(timeout=120.0)

    def _setup(self, settings: Settings) -> None:
        self.provider = settings.AI_PROVIDER
        if settings.AI_PROVIDER == "openrouter":
            self.base_url = "https://openrouter.ai/api/v1"
            self.api_key = settings.OPENROUTER_API_KEY
            self.model = settings.OPENROUTER_MODEL
            self.extra_headers: dict = {"HTTP-Referer": "http://localhost"}
        else:
            self.base_url = "https://api.deepseek.com"
            self.api_key = settings.DEEPSEEK_API_KEY
            self.model = settings.DEEPSEEK_MODEL
            self.extra_headers = {}

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

    def _build_payload(self, messages: list[dict], system: str, stream: bool) -> dict:
        all_messages = [{"role": "system", "content": system}] + messages
        return {
            "model": self.model,
            "messages": all_messages,
            "stream": stream,
        }

    async def chat(self, messages: list[dict], system: str) -> str:
        """Non-streaming chat completion. Returns the full response text."""
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, system, stream=False)

        response = await self._http.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def stream_chat(self, messages: list[dict], system: str) -> AsyncGenerator[str, None]:
        """Streaming chat completion. Yields text chunks as they arrive."""
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, system, stream=True)

        async with self._http.stream("POST", url, headers=self._headers(), json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                if not data_str:
                    continue
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def close(self) -> None:
        await self._http.aclose()
