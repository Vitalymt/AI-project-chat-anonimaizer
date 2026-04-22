"""
AI client supporting OpenRouter and DeepSeek providers.
Both expose an OpenAI-compatible /chat/completions endpoint.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional
from time import perf_counter

import httpx

from config.settings import Settings
from vault import build_tool_trace_entry

# Conditional import for request checking
try:
    from fastapi import Request
    HAS_REQUEST = True
except ImportError:
    HAS_REQUEST = False
    Request = None

logger = logging.getLogger(__name__)

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
            logger.info(f"Initialized OpenRouter client with model: {self.model}")
        else:
            self.base_url = "https://api.deepseek.com"
            self.api_key = settings.DEEPSEEK_API_KEY
            self.model = settings.DEEPSEEK_MODEL
            self.extra_headers = {}
            logger.info(f"Initialized DeepSeek client with model: {self.model}")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

    def _build_payload(
        self,
        messages: list[dict],
        system: str,
        stream: bool,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict:
        all_messages = [{"role": "system", "content": system}] + messages
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": all_messages,
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        return payload

    async def chat(self, messages: list[dict], system: str) -> str:
        """Non-streaming chat completion. Returns the full response text."""
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, system, stream=False)
        
        logger.debug(f"Sending chat request to {self.provider} with {len(messages)} messages, system prompt length: {len(system)}")
        
        try:
            response = await self._http.post(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            
            data = response.json()
            result = data["choices"][0]["message"].get("content") or ""
            logger.debug(f"Chat response received, length: {len(result)}")
            return result
            
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error {e.response.status_code} from {self.provider}: {e.response.text}"
            logger.error(error_msg)
            raise Exception(f"AI provider error: {e.response.status_code}")
        except httpx.RequestError as e:
            error_msg = f"Request error to {self.provider}: {str(e)}"
            logger.error(error_msg)
            raise Exception(f"Failed to connect to AI provider: {str(e)}")
        except (KeyError, IndexError) as e:
            error_msg = f"Unexpected response format from {self.provider}: {str(e)}"
            logger.error(error_msg)
            raise Exception(f"Invalid response from AI provider")

    async def _chat_completion_message(
        self,
        messages: list[dict],
        system: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict:
        """Non-streaming completion; returns assistant message dict (may include tool_calls)."""
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(
            messages,
            system,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        response = await self._http.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]

    async def run_chat_with_tools(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict[str, Any]],
        execute_tool: Callable[[str, dict[str, Any]], str],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_rounds: int = 24,
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        """
        Tool-calling loop until assistant returns text (no tool_calls).
        Returns (final_text, trace_call_entries, tool_result_strings).
        """
        current: list[dict] = [dict(m) for m in messages]
        trace_calls: list[dict[str, Any]] = []
        result_strings: list[str] = []
        tools_by_name = {
            t.get("function", {}).get("name"): t.get("function", {})
            for t in tools
            if t.get("type") == "function" and t.get("function", {}).get("name")
        }

        for _ in range(max_rounds):
            msg = await self._chat_completion_message(
                current,
                system,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice="auto",
            )
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                current.append(msg)
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    args_raw = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                    except json.JSONDecodeError:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}

                    # Strict argument filtering against tool schema
                    fn_schema = tools_by_name.get(name, {})
                    props = (((fn_schema.get("parameters") or {}).get("properties")) or {})
                    if props:
                        args = {k: v for k, v in args.items() if k in props}

                    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    t0 = perf_counter()
                    result_text = execute_tool(name, args)
                    # Soft retry for transient tool errors
                    if "\"error\"" in result_text and any(
                        token in result_text.lower()
                        for token in ("timeout", "tempor", "timed out", "connection")
                    ):
                        result_text = execute_tool(name, args)
                    duration_ms = int((perf_counter() - t0) * 1000)
                    finished = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    result_strings.append(result_text)
                    trace_calls.append(
                        build_tool_trace_entry(
                            name,
                            args,
                            result_text,
                            started_at=started,
                            finished_at=finished,
                            duration_ms=duration_ms,
                        )
                    )
                    current.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "content": result_text,
                        }
                    )
                continue

            content = msg.get("content")
            if content is None:
                content = ""
            return str(content), trace_calls, result_strings

        fallback = (
            "Не удалось завершить цепочку навигации по vault за допустимое число шагов. "
            "Даю ответ по уже собранным данным; при необходимости уточните вопрос."
        )
        return fallback, trace_calls, result_strings

    async def stream_chat(
        self,
        messages: list[dict],
        system: str,
        request: Optional["Request"] = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming chat completion. Yields text chunks as they arrive."""
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(
            messages,
            system,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        logger.debug(f"Starting stream chat to {self.provider} with {len(messages)} messages, system prompt length: {len(system)}")
        
        async with self._http.stream("POST", url, headers=self._headers(), json=payload) as response:
            response.raise_for_status()
            logger.debug(f"Stream started successfully with status: {response.status_code}")
            async for line in response.aiter_lines():
                if request is not None and HAS_REQUEST:
                    try:
                        if await request.is_disconnected():
                            logger.info("Client disconnected during provider stream")
                            break
                    except Exception:
                        pass
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    logger.debug("Received [DONE] signal, ending stream")
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
