"""Runtime endpoint discovery: the user supplies the URL, the service inspects it."""

from __future__ import annotations

import copy
import json
import urllib.parse
import urllib.request
from typing import Any, Callable

from cardgen.client import LlamaClient

Getter = Callable[[str, str], Any]

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


class ConnectionState:
    def __init__(
        self,
        default_url: str,
        default_model: str = "",
        *,
        allow_remote: bool = False,
        get_json: Getter | None = None,
        timeout_s: int = 1200,
    ):
        self.default_url = default_url
        self.allow_remote = allow_remote
        self._get = get_json or default_get
        self.timeout_s = timeout_s
        self.base_url = default_url
        self.error = ""
        self.online = False
        self.models: list[dict[str, Any]] = []
        self.loaded_model = ""
        self.model_path = ""
        self.context: int | None = None
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

    def probe(self, raw: str | None = None) -> dict[str, Any]:
        url = self.validate(raw) if raw is not None else self.base_url
        self.base_url = url
        self.error = ""
        self.online = False
        self.models = []
        self.loaded_model = ""
        self.model_path = ""
        self.context = None
        self.vision = self.video = self.audio = False
        self.build_info = ""
        self.slots = []
        self.sleeping = False
        self.props_available = False

        try:
            health = self._get(url, "/health")
            self.online = str(health.get("status", "")).lower() == "ok"
            if not self.online:
                self.error = f"server responded: {health}"
                return self.summary()
        except Exception as exc:
            self.error = f"cannot reach {url}: {exc}"
            return self.summary()

        try:
            payload = self._get(url, "/v1/models")
            for item in payload.get("data", []):
                self.models.append(
                    {
                        "id": item.get("id", ""),
                        "modalities": item.get("modalities", []),
                        "owned_by": item.get("owned_by", ""),
                    }
                )
        except Exception as exc:
            self.error = f"model listing failed: {exc}"

        try:
            props = self._get(url, "/props")
            self.props_available = True
            self.loaded_model = props.get("model_alias", "") or ""
            self.model_path = props.get("model_path", "") or ""
            self.build_info = props.get("build_info", "") or ""
            self.sleeping = bool(props.get("is_sleeping", False))
            gen = props.get("default_generation_settings") or {}
            self.context = gen.get("n_ctx")
            mods = props.get("modalities") or {}
            self.vision = bool(mods.get("vision", False))
            self.video = bool(mods.get("video", False))
            self.audio = bool(mods.get("audio", False))
        except Exception:
            pass  # generic OpenAI-compatible servers do not expose /props

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

    @property
    def ready(self) -> bool:
        return bool(
            self.online
            and not self.sleeping
            and self.selected_model
            and self.selected_model in [m["id"] for m in self.models]
        )

    def summary(self) -> dict[str, Any]:
        return {
            "online": self.online,
            "ready": self.ready,
            "error": self.error,
            "base_url": self.base_url,
            "models": self.models,
            "loaded_model": self.loaded_model,
            "selected_model": self.selected_model,
            "context": self.context,
            "vision": self.vision,
            "video": self.video,
            "audio": self.audio,
            "build_info": self.build_info,
            "model_path": self.model_path,
            "slots": self.slots,
            "props_available": self.props_available,
        }

    def make_client(self) -> LlamaClient:
        return LlamaClient(self.base_url, self.selected_model, self.timeout_s)

    def config_override(self, config: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(config)
        result["server"]["base_url"] = self.base_url
        result["server"]["model"] = self.selected_model
        return result
