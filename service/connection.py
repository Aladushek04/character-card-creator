"""Runtime endpoint discovery: the user supplies the URL, the service inspects it.

Supports three flavours:
  * llama.cpp / bmoe  — /health, /props, /slots, /tokenize
  * LM Studio         — /v1/models, /api/v1/models (loaded instances, context, capabilities)
  * generic OpenAI    — /v1/models only
"""

from __future__ import annotations

import copy
import json
import urllib.parse
import urllib.request
from typing import Any, Callable

from cardgen.client import LlamaClient

Getter = Callable[[str, str], Any]
Poster = Callable[[str, str, dict[str, Any]], Any]

LOOPBACK_HOSTS = {"localhost", "::1", "[::1]"}


def normalize_url(raw: str) -> str:
    url = (raw or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("enter a full http:// or https:// URL")
    return url


def is_loopback(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in LOOPBACK_HOSTS or host.startswith("127.")


def default_get(base_url: str, path: str) -> Any:
    req = urllib.request.Request(base_url + path, method="GET")
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def default_post(base_url: str, path: str, payload: dict[str, Any]) -> Any:
    req = urllib.request.Request(
        base_url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


class ConnectionState:
    def __init__(
        self,
        default_url: str,
        default_model: str = "",
        *,
        allow_remote: bool = False,
        get_json: Getter | None = None,
        post_json: Poster | None = None,
        timeout_s: int = 1200,
    ):
        self.default_url = default_url
        self.allow_remote = allow_remote
        self._get = get_json or default_get
        self._post = post_json or default_post
        self.timeout_s = timeout_s
        self.base_url = default_url
        self.error = ""
        self.online = False
        self.api_flavor = "unknown"
        self.models: list[dict[str, Any]] = []
        self.model_details: dict[str, dict[str, Any]] = {}
        self.loaded_instances: list[str] = []
        self.loaded_model = ""
        self.model_path = ""
        self.context: int | None = None
        self.max_context: int | None = None
        self.vision = False
        self.video = False
        self.audio = False
        self.build_info = ""
        self.slots: list[dict[str, Any]] = []
        self.sleeping = False
        self.selected_model = default_model
        self.props_available = False

    def validate(self, raw: str) -> str:
        url = normalize_url(raw)
        if not self.allow_remote and not is_loopback(url):
            raise ValueError(
                "remote endpoints are disabled for now; use a loopback URL "
                "(127.0.0.1, localhost, ::1)"
            )
        return url

    def _reset(self) -> None:
        self.error = ""
        self.online = False
        self.api_flavor = "unknown"
        self.models = []
        self.model_details = {}
        self.loaded_instances = []
        self.loaded_model = ""
        self.model_path = ""
        self.context = None
        self.max_context = None
        self.vision = self.video = self.audio = False
        self.build_info = ""
        self.slots = []
        self.sleeping = False
        self.props_available = False

    def probe(self, raw: str | None = None) -> dict[str, Any]:
        url = self.validate(raw) if raw is not None else self.base_url
        self.base_url = url
        self._reset()

        health = None
        try:
            health = self._get(url, "/health")
        except Exception:
            pass
        if isinstance(health, dict) and str(health.get("status", "")).lower() == "ok":
            self.online = True
        else:
            # LM Studio and generic servers have no /health; a working /v1/models
            # is enough to consider the endpoint reachable.
            try:
                payload = self._get(url, "/v1/models")
                self.online = isinstance(payload, dict) and bool(payload.get("data"))
            except Exception as exc:
                self.error = f"cannot reach {url}: {exc}"
                return self.summary()
            if self.online:
                self.error = "/health not exposed; endpoint verified through /v1/models"

        if not self.online:
            self.error = f"server responded: {health}"
            return self.summary()

        try:
            payload = self._get(url, "/v1/models")
            for item in payload.get("data", []):
                model_id = item.get("id", "")
                self.models.append(
                    {
                        "id": model_id,
                        "modalities": item.get("modalities", []),
                        "owned_by": item.get("owned_by", ""),
                    }
                )
        except Exception as exc:
            self.error = f"model listing failed: {exc}"

        try:
            props = self._get(url, "/props")
            if not isinstance(props, dict) or not (
                "default_generation_settings" in props
                or "model_alias" in props
                or "modalities" in props
            ):
                raise ValueError("not a llama.cpp /props response")
            self.api_flavor = "llama.cpp"
            self.props_available = True
            self.loaded_model = props.get("model_alias", "") or ""
            self.model_path = props.get("model_path", "") or ""
            self.build_info = props.get("build_info", "") or ""
            self.sleeping = bool(props.get("is_sleeping", False))
            gen = props.get("default_generation_settings") or {}
            self.context = gen.get("n_ctx")
            self.max_context = self.context
            mods = props.get("modalities") or {}
            self.vision = bool(mods.get("vision", False))
            self.video = bool(mods.get("video", False))
            self.audio = bool(mods.get("audio", False))
            if self.loaded_model:
                self.loaded_instances = [self.loaded_model]
                self.model_details[self.loaded_model] = {"loaded": True}
        except Exception:
            pass

        if self.api_flavor == "unknown":
            try:
                api_models = self._get(url, "/api/v1/models")
                models = api_models.get("models", []) if isinstance(api_models, dict) else []
                if not isinstance(models, list):
                    raise ValueError("not an LM Studio /api/v1/models response")
                self.api_flavor = "LM Studio"
                for item in models:
                    if item.get("type") != "llm":
                        continue
                    key = item.get("key", "")
                    quant = (item.get("quantization") or {}).get("name", "")
                    caps = item.get("capabilities") or {}
                    if caps.get("vision"):
                        self.vision = True
                    if caps.get("trained_for_tool_use"):
                        pass
                    if item.get("max_context_length"):
                        self.max_context = max(
                            self.max_context or 0, int(item["max_context_length"])
                        )
                    for inst in item.get("loaded_instances", []):
                        inst_id = inst.get("id", "")
                        self.loaded_instances.append(inst_id)
                        if not self.loaded_model:
                            self.loaded_model = inst_id
                        cfg = inst.get("config") or {}
                        if self.context is None and cfg.get("context_length"):
                            self.context = int(cfg["context_length"])
                    for m in self.models:
                        mid = m["id"]
                        if mid == key or mid.startswith(key + "@"):
                            m["modalities"] = ["text", "image"] if caps.get("vision") else ["text"]
                            self.model_details[mid] = {
                                "key": key,
                                "quant": quant,
                                "display_name": item.get("display_name", ""),
                                "params": item.get("params_string", ""),
                                "max_context": item.get("max_context_length"),
                                "reasoning": bool((caps.get("reasoning") or {}).get("allowed_options")),
                                "loaded": mid in self.loaded_instances,
                            }
            except Exception:
                self.api_flavor = "OpenAI-compatible"

        try:
            slots = self._get(url, "/slots")
            if isinstance(slots, list):
                self.slots = [
                    {
                        "id": s.get("id"),
                        "n_ctx": s.get("n_ctx"),
                        "processing": s.get("is_processing", False),
                    }
                    for s in slots
                ]
                if self.context is None and slots:
                    self.context = slots[0].get("n_ctx")
        except Exception:
            pass

        ids = [m["id"] for m in self.models]
        if self.selected_model not in ids:
            self.selected_model = self.loaded_model if self.loaded_model in ids else (ids[0] if ids else "")
        if not self.vision:
            self.vision = any("image" in m.get("modalities", []) for m in self.models)
        return self.summary()

    def set_model(self, model_id: str) -> None:
        if model_id and model_id in [m["id"] for m in self.models]:
            self.selected_model = model_id

    def load_model(self, model_id: str | None = None, context_length: int = 32768) -> dict[str, Any]:
        """LM Studio only: load the chosen model into memory."""
        if self.api_flavor != "LM Studio":
            raise ValueError("model loading is only supported for LM Studio endpoints")
        model_id = model_id or self.selected_model
        details = self.model_details.get(model_id, {})
        key = details.get("key") or (model_id.split("@")[0] if "@" in model_id else model_id)
        result = self._post(
            self.base_url,
            "/api/v1/models/load",
            {"model": key, "context_length": context_length, "echo_load_config": True},
        )
        self.probe()
        return result

    @property
    def ready(self) -> bool:
        ids = [m["id"] for m in self.models]
        if not (self.online and not self.sleeping and self.selected_model and self.selected_model in ids):
            return False
        if self.api_flavor == "LM Studio":
            return self.selected_model in self.loaded_instances
        return True

    def summary(self) -> dict[str, Any]:
        return {
            "online": self.online,
            "ready": self.ready,
            "error": self.error,
            "base_url": self.base_url,
            "api_flavor": self.api_flavor,
            "models": self.models,
            "model_details": self.model_details,
            "loaded_model": self.loaded_model,
            "loaded_instances": self.loaded_instances,
            "selected_model": self.selected_model,
            "context": self.context,
            "max_context": self.max_context,
            "vision": self.vision,
            "video": self.video,
            "audio": self.audio,
            "build_info": self.build_info,
            "model_path": self.model_path,
            "slots": self.slots,
            "props_available": self.props_available,
        }

    def make_client(self) -> LlamaClient:
        # LM Studio defaults to reasoning-on for some models, which can consume
        # the whole token budget with an empty content field.
        return LlamaClient(
            self.base_url,
            self.selected_model,
            self.timeout_s,
            disable_reasoning=self.api_flavor == "LM Studio",
        )

    def config_override(self, config: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(config)
        result["server"]["base_url"] = self.base_url
        result["server"]["model"] = self.selected_model
        return result
