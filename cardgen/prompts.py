"""Prompt assembly. Templates live in prompts/ so they can be edited freely.

Templates use %KEY% placeholders (not str.format) because they contain JSON
and {{char}}/{{user}} tokens whose braces must pass through untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load(name: str) -> str:
    path = PROMPT_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"missing prompt template: {path}")
    return path.read_text(encoding="utf-8")


def render(template: str, **values: str) -> str:
    result = template
    for key, value in values.items():
        result = result.replace(f"%{key}%", value)
    return result


def build_system_prompt(args: Any, gen_cfg: dict[str, Any], card_cfg: dict[str, Any]) -> str:
    return render(
        load("system.txt"),
        narrative_language=args.narrative_language or card_cfg["narrative_language"],
        definition_language=args.definition_language or card_cfg["definition_language"],
        content_rating=args.content_rating or card_cfg["content_rating"],
        min_definition_chars=str(gen_cfg.get("min_definition_chars", 3500)),
        max_definition_chars=str(gen_cfg.get("max_definition_chars", 6000)),
        max_words=str(max(300, gen_cfg["max_description_tokens"] // 2)),
    )


def _biography(args: Any) -> str:
    text = getattr(args, "bio_text", "") or ""
    bio_path = getattr(args, "bio", None)
    if bio_path and Path(bio_path).is_file():
        text = Path(bio_path).read_text(encoding="utf-8", errors="replace")
    return text.strip() or "(no biography provided; invent a coherent background)"


def build_brief(args: Any, card_cfg: dict[str, Any]) -> str:
    return render(
        load("brief.txt"),
        concept=args.concept,
        name=args.name or "(choose a fitting name, 3-80 characters)",
        setting=args.setting or "(infer from the concept)",
        extra=args.extra or "(none)",
        tags=", ".join(args.tags) if args.tags else "(choose 8-15 fitting lowercase tags)",
        photo_note=(
            "A reference photo is attached. Derive the appearance section from what you see, "
            "but NEVER describe anyone who looks underage."
            if args.photo
            else "No reference photo; invent a coherent appearance."
        ),
        biography=(
            "BIOGRAPHY REFERENCE (use it faithfully; do not copy it verbatim into the card):\n"
            + _biography(args)
        ),
        appearance_reference=(
            "APPEARANCE REFERENCE:\n"
            + str(getattr(args, "appearance_reference", "") or "(none)")
        ),
    )


def build_repair_prompt(errors: list[str]) -> str:
    return render(load("repair.txt"), errors="\n".join(f"- {e}" for e in errors))
