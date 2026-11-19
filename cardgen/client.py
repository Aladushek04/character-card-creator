"""Minimal OpenAI-compatible HTTP client for the local inference server."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any


class InferenceError(RuntimeError):
    pass


class LlamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: int = 1200,
        *,
        disable_reasoning: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.disable_reasoning = disable_reasoning
        self._tokenizer_exact: bool | None = None

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:1000]
            raise InferenceError(f"HTTP {exc.code} on {path}: {body}") from exc
        except urllib.error.URLError as exc:
            raise InferenceError(
                f"cannot reach {self.base_url}{path}: {exc.reason}. "
                "Check that the model server is running."
            ) from exc

    def get_json(self, path: str, timeout: int = 10) -> Any:
        req = urllib.request.Request(self.base_url + path, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def health(self) -> dict[str, Any]:
        try:
            return self.get_json("/health")
        except Exception as exc:  # network/parse errors are both unhelpful here
            raise InferenceError(f"health check failed: {exc}") from exc

    def models(self) -> list[str]:
        req = urllib.request.Request(self.base_url + "/v1/models", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return [m.get("id", "") for m in payload.get("data", [])]
        except Exception as exc:
            raise InferenceError(f"model listing failed: {exc}") from exc

    def tokenize(self, text: str) -> int:
        """Use the server tokenizer when available; otherwise estimate.

        LM Studio and other generic OpenAI-compatible servers do not expose
        /tokenize. An estimate is sufficient for budget reporting and history
        trimming; it is labelled as such by the caller.
        """
        try:
            result = self._post("/tokenize", {"content": text, "add_special": False})
            tokens = result.get("tokens") if isinstance(result, dict) else None
            if isinstance(tokens, list):
                self._tokenizer_exact = True
                return len(tokens)
        except Exception:
            pass
        self._tokenizer_exact = False
        return max(1, len(text) // 4)

    @property
    def exact_tokenizer(self) -> bool:
        if self._tokenizer_exact is None:
            self.tokenize("x")
        return bool(self._tokenizer_exact)

    def chat_json(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        gen_cfg: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Request a schema-constrained JSON response; return (object, usage)."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "character_card", "strict": True, "schema": schema},
            },
            "temperature": gen_cfg["temperature"],
            "top_p": gen_cfg["top_p"],
            "top_k": gen_cfg["top_k"],
            "repeat_penalty": gen_cfg["repeat_penalty"],
            "max_tokens": gen_cfg["max_tokens"],
        }
        if self.disable_reasoning:
            payload["reasoning"] = False
        result = self._post("/v1/chat/completions", payload)
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceError(f"unexpected chat response: {str(result)[:500]}") from exc
        usage = result.get("usage", {})
        return parse_json_object(content), usage

    def chat_text(
        self, messages: list[dict[str, Any]], gen_cfg: dict[str, Any], max_tokens: int = 256
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": gen_cfg["temperature"],
            "top_p": gen_cfg["top_p"],
            "max_tokens": max_tokens,
        }
        if self.disable_reasoning:
            payload["reasoning"] = False
        result = self._post("/v1/chat/completions", payload)
        return result["choices"][0]["message"]["content"]


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse model output, tolerating markdown fences and surrounding prose."""
    if not isinstance(content, str):
        raise InferenceError("model returned a non-string response")
    text = _FENCE.sub("", content).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise InferenceError(f"no JSON object in model output: {content[:300]}")
        obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        raise InferenceError("model output is not a JSON object")
    return obj
