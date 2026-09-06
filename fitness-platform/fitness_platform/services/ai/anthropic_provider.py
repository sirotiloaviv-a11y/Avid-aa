"""Production provider backed by the Claude Messages API (44).

Kept deliberately thin: build the payload, post it, map the reply. Retries,
model choice and the key all come from configuration, and the key never leaves
the server — the browser talks to ``/api/ai/*``, never to the vendor.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from ...config import get_settings
from .provider import AIProvider, AIRequest, AIResponse, timed

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
TIMEOUT_SECONDS = 30


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.ai_api_key
        self._model = settings.ai_model
        if not self._api_key:
            raise RuntimeError(
                "AI_PROVIDER=anthropic requires AI_API_KEY. Set it, or run with AI_PROVIDER=mock."
            )

    def complete(self, request: AIRequest) -> AIResponse:
        start = time.monotonic()
        system = request.system
        if request.context_blocks:
            system += "\n\n" + "\n\n".join(request.context_blocks)

        payload = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": system,
            "messages": [
                {"role": message.role, "content": message.content} for message in request.messages
            ],
        }
        http_request = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return AIResponse(
                text="",
                provider=self.name,
                latency_ms=timed(start),
                status="error",
                error=f"http_{error.code}",
            )
        except Exception as error:  # network, timeout, malformed body
            return AIResponse(
                text="", provider=self.name, latency_ms=timed(start), status="error", error=type(error).__name__
            )

        text = "".join(
            block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"
        )
        usage = body.get("usage", {})
        return AIResponse(
            text=text.strip(),
            provider=self.name,
            tokens=int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
            latency_ms=timed(start),
            status="ok" if text.strip() else "error",
            error="" if text.strip() else "empty_response",
        )

    def health(self) -> dict:
        return {"provider": self.name, "mock": False, "ready": bool(self._api_key), "model": self._model}
