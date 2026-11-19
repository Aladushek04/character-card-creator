"""Character Card V3 construction and validation.

Rules implemented here come from:
  * Writing Tips.md supplied for this project (CT field limits, macro rules,
    natural-language-only definitions, underage/malicious/spam prohibitions).
  * The 39 cards exported from character-tavern.com in the project root
    (every one is `chara_card_v3` / `3.0`; `chara` and `ccv3` PNG chunks carry
    the same V3 object; `description` = Definition, `first_mes` = Greeting,
    `creator_notes` = Public description).
"""

from __future__ import annotations

import re
import time
from typing import Any

# Keys the model is asked to produce. All other V3 fields are filled here.
DRAFT_KEYS = (
    "name",
    "tagline",
    "description",
    "first_mes",
    "creator_notes",
    "tags",
)

# minLength values encode Writing Tips.md mandatory-field limits. The
# definition floor (1200) is the anti-spam threshold, not the 200-char hard
# minimum; the model is prompted to aim for 3500-6000 characters.
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 3, "maxLength": 80},
        "tagline": {"type": "string", "minLength": 10, "maxLength": 150},
        "description": {"type": "string", "minLength": 1200, "maxLength": 6000},
        "first_mes": {"type": "string", "minLength": 200, "maxLength": 3200},
        "creator_notes": {"type": "string", "minLength": 20, "maxLength": 25000},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 100},
    },
    "required": list(DRAFT_KEYS),
    "additionalProperties": False,
}

DEFINITION_TARGET = (3500, 6000)
GREETING_TARGET = (800, 3200)
TAGLINE_TARGET = (10, 150)
NAME_TARGET = (3, 80)
IN_CHAT_NAME_TARGET = (1, 50)

# Presentation-based underage gate. "High school" and similar scenarios count
# as underage coding even when an age is stated.
MINOR_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bunder\s*[- ]?\s*(?:18|eighteen)\b",
        r"\bunderage(?:d)?\b",
        r"\b(?:a|the)?\s*(?:minor|teenager|teen|young teen|schoolgirl|schoolboy|school kid)\b",
        r"\b(?:12|13|14|15|16|17)[ -]?(?:year|yr|yo)[ -]?old\b",
        r"\bchild\b",
        r"\bchildlike\b",
        r"\blooks? like a child\b",
        r"\b(?:high|middle|junior) school\b",
        r"\bschool setting\b",
    )
)

# Writing Tips.md: "Avoid W++ and pseudo-code."
WP_PLUS_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in (
        r"^\s*\[[^\]\n]{1,40}\([^\]\n]*\)\]",
        r"\b(?:personality|description|appearance|scenario|behavior)\s*\(",
        r"\b\w+\s*\(\s*['\"][^'\"]+['\"]\s*\+",
    )
)

SPAM_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(?:test|testing|coming soon|placeholder|stolen from)\b",
        r"\basdf\b",
    )
)

_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_CATBOX_IMAGE = re.compile(
    r"!\[[^\]]*\]\(https://files\.catbox\.moe/[^\s)]+\)", re.IGNORECASE
)

def _in_range(text: str, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= len(text) <= bounds[1]


def normalize_macros(draft: dict[str, Any]) -> dict[str, Any]:
    """Deterministic backstop for the 'use {{char}}/{{user}}' rule.

    Replaces the character's own name in the definition and greeting with the
    {{char}} macro, and normalises hand-written user macros. The catalog blurb
    keeps the real name because readers see it outside a chat.
    """
    name = str(draft.get("name", "")).strip()
    for field in ("description", "first_mes"):
        text = str(draft.get(field, ""))
        if name and len(name) >= 3:
            text = re.sub(rf"\b{re.escape(name)}\b", "{{char}}", text, flags=re.IGNORECASE)
        text = re.sub(r"\{\{\s*user\s*\}\}|\[user\]", "{{user}}", text, flags=re.IGNORECASE)
        text = re.sub(r"\{\{\s*char\s*\}\}|\[char\]", "{{char}}", text, flags=re.IGNORECASE)
        draft[field] = text
    return draft


def validate_draft(draft: dict[str, Any]) -> list[str]:
    """Return a list of problems; empty means the draft is usable."""
    errors: list[str] = []
    if not isinstance(draft, dict):
        return ["model output is not a JSON object"]

    for key in DRAFT_KEYS:
        if key not in draft:
            errors.append(f"missing key: {key}")

    for key in ("name", "tagline", "description", "first_mes", "creator_notes"):
        value = draft.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"{key} must be a string")
        elif isinstance(value, str) and not value.strip():
            errors.append(f"{key} is empty")

    name = str(draft.get("name", ""))
    tagline = str(draft.get("tagline", ""))
    description = str(draft.get("description", ""))
    first_mes = str(draft.get("first_mes", ""))
    creator_notes = str(draft.get("creator_notes", ""))
    tags = draft.get("tags")

    if name and not _in_range(name.strip(), NAME_TARGET):
        errors.append(f"name must be {NAME_TARGET[0]}-{NAME_TARGET[1]} characters")
    if tagline and not _in_range(tagline.strip(), TAGLINE_TARGET):
        errors.append(f"tagline must be {TAGLINE_TARGET[0]}-{TAGLINE_TARGET[1]} characters")
    if description and len(description) < 1200:
        errors.append("definition is below the 1200-character anti-spam floor")
    if first_mes and len(first_mes) < 200:
        errors.append("greeting is too short to be usable")
    if creator_notes and len(creator_notes.strip()) < 10:
        errors.append("public description must be at least 10 characters")
    if tags is not None:
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            errors.append("tags must be an array of strings")
        elif not (1 <= len(tags) <= 100):
            errors.append("tags must contain between 1 and 100 entries")

    # Natural language and macros.
    if description:
        if "{{char}}" not in description:
            errors.append("definition must use the {{char}} macro, not a fixed name")
        if "{{user}}" not in description:
            errors.append("definition must use the {{user}} macro, not a fixed name")
        for pattern in WP_PLUS_PATTERNS:
            if pattern.search(description):
                errors.append("definition contains W++/pseudo-code; use natural language")
                break
    if first_mes and "{{user}}" not in first_mes:
        errors.append("greeting must address {{user}} via the macro")

    # Prohibited content.
    inspect = " ".join((description, first_mes, creator_notes, tagline))
    hits = sorted({m.group(0).lower() for p in MINOR_PATTERNS for m in p.finditer(inspect)})
    if hits:
        errors.append("underage or underage-coded presentation: " + ", ".join(hits))
    for pattern in SPAM_PATTERNS:
        if pattern.search(inspect):
            errors.append("spam/placeholder text: " + pattern.pattern)
            break
    safe_for_urls = " ".join(
        (description, _CATBOX_IMAGE.sub("", first_mes), creator_notes, tagline)
    )
    urls = _URL.findall(safe_for_urls)
    if urls:
        errors.append("links are not allowed in cards: " + ", ".join(urls[:3]))

    return errors


def draft_warnings(draft: dict[str, Any]) -> list[str]:
    """CT 'aim for' targets. Reported to the user, never used to retry generation."""
    warnings: list[str] = []
    description = str(draft.get("description", ""))
    first_mes = str(draft.get("first_mes", ""))
    if description and not _in_range(description, DEFINITION_TARGET):
        warnings.append(
            f"definition {len(description)} chars; CT suggests {DEFINITION_TARGET[0]}-"
            f"{DEFINITION_TARGET[1]}"
        )
    if first_mes and not _in_range(first_mes, GREETING_TARGET):
        warnings.append(
            f"greeting {len(first_mes)} chars; CT suggests {GREETING_TARGET[0]}-"
            f"{GREETING_TARGET[1]}"
        )
    return warnings


def build_card(draft: dict[str, Any], card_cfg: dict[str, Any]) -> dict[str, Any]:
    """Build a Character Card V3 object from a validated model draft."""
    now_ms = int(time.time() * 1000)
    name = draft["name"].strip()
    data = {
        "name": name,
        "nickname": name[: IN_CHAT_NAME_TARGET[1]],
        "description": draft["description"].strip(),
        "tags": [t.strip().lower() for t in draft["tags"] if t.strip()],
        "creator": card_cfg["creator"],
        "character_version": card_cfg["character_version"],
        # Legacy fields stay empty on purpose: Writing Tips.md warns that they
        # consume token budget and degrade modern models.
        "mes_example": "",
        "extensions": {},
        "system_prompt": "",
        "post_history_instructions": "",
        "first_mes": draft["first_mes"].strip(),
        "alternate_greetings": [],
        "personality": "",
        "scenario": "",
        "creator_notes": draft["creator_notes"].strip(),
        "character_book": None,
        "creation_date": now_ms,
        "modification_date": now_ms,
        "group_only_greetings": [],
    }
    return {"spec": "chara_card_v3", "spec_version": "3.0", "data": data}


def draft_metrics(draft: dict[str, Any]) -> dict[str, int]:
    return {
        "name": len(str(draft.get("name", ""))),
        "tagline": len(str(draft.get("tagline", ""))),
        "definition": len(str(draft.get("description", ""))),
        "greeting": len(str(draft.get("first_mes", ""))),
        "public_description": len(str(draft.get("creator_notes", ""))),
        "tags": len(draft.get("tags", [])) if isinstance(draft.get("tags"), list) else 0,
    }


def card_text(card: dict[str, Any]) -> str:
    """The text CT's token counter effectively charges for."""
    d = card["data"]
    return "\n".join(
        [
            d.get("name", ""),
            d.get("description", ""),
            d.get("personality", ""),
            d.get("scenario", ""),
            d.get("first_mes", ""),
            "\n".join(d.get("alternate_greetings", [])),
            d.get("creator_notes", ""),
            " ".join(d.get("tags", [])),
        ]
    )
