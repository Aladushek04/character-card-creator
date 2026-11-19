"""Photo reference analysis through the vision endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cardgen.client import LlamaClient
from cardgen.prompts import load

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "age_presentation": {
            "type": "string",
            "enum": ["adult", "uncertain", "underage"],
        },
        "overall": {"type": "string"},
        "hair": {"type": "string"},
        "eyes": {"type": "string"},
        "face": {"type": "string"},
        "body_build": {"type": "string"},
        "distinctive_marks": {"type": "array", "items": {"type": "string"}},
        "attire": {"type": "string"},
        "intimate_features": {
            "type": "object",
            "properties": {
                "chest": {"type": "string"},
                "waist": {"type": "string"},
                "hips": {"type": "string"},
                "legs": {"type": "string"},
                "skin": {"type": "string"},
                "intimate_attire": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["chest", "waist", "hips", "legs", "skin", "intimate_attire", "notes"],
        },
    },
    "required": [
        "age_presentation", "overall", "hair", "eyes", "face", "body_build",
        "distinctive_marks", "attire", "intimate_features",
    ],
}


class UnderageSubject(ValueError):
    pass


def analyze_photo(
    client: LlamaClient,
    photo: str | Path,
    gen_cfg: dict[str, Any],
    *,
    confirm_adult: bool = False,
) -> dict[str, Any]:
    photo = Path(photo)
    if not photo.is_file():
        raise FileNotFoundError(photo)
    import base64
    import mimetypes

    mime = mimetypes.guess_type(photo)[0] or "image/png"
    data = base64.b64encode(photo.read_bytes()).decode("ascii")
    messages = [
        {"role": "system", "content": load("photo_analysis.txt")},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Analyze this photo and return the requested JSON."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
            ],
        },
    ]
    cfg = dict(gen_cfg)
    cfg["max_tokens"] = 900
    cfg["temperature"] = 0.15
    result, _usage = client.chat_json(messages, ANALYSIS_SCHEMA, cfg)
    presentation = str(result.get("age_presentation", "uncertain")).lower()
    if presentation == "underage":
        raise UnderageSubject("the photo appears to show an underage person; card creation blocked")
    if presentation == "uncertain" and not confirm_adult:
        raise UnderageSubject(
            "the subject's age is unclear; tick the adult-subject confirmation to continue"
        )
    return result


def format_analysis(analysis: dict[str, Any] | None) -> str:
    """Render the structured photo analysis as a brief block for card generation."""
    if not analysis:
        return "No photo analysis available."
    lines = [
        "PHOTO REFERENCE (use these exact details in the Appearance section):",
        f"- Overall: {analysis.get('overall', '')}",
        f"- Hair: {analysis.get('hair', '')}",
        f"- Eyes: {analysis.get('eyes', '')}",
        f"- Face: {analysis.get('face', '')}",
        f"- Body build: {analysis.get('body_build', '')}",
        "- Distinctive marks: " + ", ".join(analysis.get("distinctive_marks", [])),
        f"- Attire: {analysis.get('attire', '')}",
    ]
    intimate = analysis.get("intimate_features") or {}
    for key, label in (
        ("chest", "Chest"),
        ("waist", "Waist"),
        ("hips", "Hips"),
        ("legs", "Legs"),
        ("skin", "Skin"),
        ("intimate_attire", "Intimate attire"),
        ("notes", "Notes"),
    ):
        if intimate.get(key):
            lines.append(f"- {label}: {intimate[key]}")
    return "\n".join(lines)
