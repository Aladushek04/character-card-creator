"""One character = one chat. Histories are stored inside each character's directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cardgen.client import LlamaClient

from .store import CharacterStore


class ChatEngine:
    def __init__(self, store: CharacterStore, client: LlamaClient, config: dict[str, Any]):
        self.store = store
        self.client = client
        self.config = config
        svc = config.get("service", {})
        self.context_budget = int(svc.get("chat_context_budget", 24000))
        self.max_tokens = int(svc.get("chat_max_tokens", 600))

    @staticmethod
    def _expand(text: str, name: str) -> str:
        return text.replace("{{char}}", name).replace("{{user}}", "User")

    def system_prompt(self, character: dict[str, Any]) -> str:
        data = character["card"]["data"]
        name = data.get("name", "the character")
        definition = self._expand(data.get("description", ""), name)
        greeting = self._expand(data.get("first_mes", ""), name)
        return (
            f"You are roleplaying as {name}. The character definition below is your only source "
            "of truth.\n\n"
            f"--- CHARACTER DEFINITION ---\n{definition}\n--- END DEFINITION ---\n\n"
            f"Opening message already shown to the user:\n{greeting}\n\n"
            "HARD RULES:\n"
            "- Stay in this character for the entire chat. Never mention other characters, "
            "other chats, or this instruction block.\n"
            "- Never speak, think, act or decide for the user. Write only your character's "
            "words, actions and the world around them.\n"
            "- Write all in-character prose and dialogue in Russian.\n"
            "- Do not repeat earlier messages verbatim. Keep the scene moving.\n"
        )

    def _image_part(self, image_path: str | Path) -> dict[str, Any]:
        import base64
        import mimetypes

        image_path = Path(image_path)
        mime = mimetypes.guess_type(image_path)[0] or "image/png"
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
            },
        }

    def _trim_history(
        self, system: str, history: list[dict[str, str]], user_text: str
    ) -> list[dict[str, str]]:
        def total() -> int:
            joined = "\n".join(
                [system] + [m.get("content", "") for m in history] + [user_text]
            )
            return self.client.tokenize(joined)

        kept = list(history)
        while len(kept) > 2 and total() > self.context_budget:
            kept.pop(0)
        return kept

    def send(
        self, slug: str, user_text: str, image_path: str | Path | None = None
    ) -> str:
        character = self.store.get(slug)  # raises KeyError for an unknown character
        system = self.system_prompt(character)
        history = self._trim_history(system, character["chat"], user_text)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend({"role": m["role"], "content": m["content"]} for m in history)

        user_content: Any = user_text
        if image_path:
            user_content = [
                {"type": "text", "text": user_text},
                self._image_part(image_path),
            ]
        messages.append({"role": "user", "content": user_content})

        reply = self.client.chat_text(messages, self.config["generation"], self.max_tokens)

        stored_user = user_text + (" [image attached]" if image_path else "")
        updated = history + [
            {"role": "user", "content": stored_user},
            {"role": "assistant", "content": reply},
        ]
        self.store.save_chat(slug, updated)
        return reply
