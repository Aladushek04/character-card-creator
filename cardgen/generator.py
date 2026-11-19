"""Generation orchestration: brief -> structured JSON -> V3 card -> PNG + JSON."""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from .client import InferenceError, LlamaClient
from .png_io import make_portrait, write_card_png
from .prompts import build_brief, build_repair_prompt, build_system_prompt, load, render
from .schema import DRAFT_SCHEMA, build_card, card_text, draft_metrics, normalize_macros, validate_draft

_SLUG = re.compile(r"[^\w]+", re.UNICODE)


def slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).lower()
    return _SLUG.sub("_", normalized).strip("_") or "character"


def _image_part(path: str) -> dict[str, Any]:
    import base64
    import mimetypes

    mime = mimetypes.guess_type(path)[0] or "image/png"
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{data}"},
    }


def _user_message(args: Any, card_cfg: dict[str, Any]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": build_brief(args, card_cfg)}]
    if args.photo and not args.no_photo_in_prompt:
        content.append(_image_part(args.photo))
    return {"role": "user", "content": content}


def _generate_draft(
    client: LlamaClient,
    system_prompt: str,
    messages: list[dict[str, Any]],
    gen_cfg: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    last_errors: list[str] = []
    attempts = gen_cfg["retries"] + 1
    for attempt in range(attempts):
        started = time.monotonic()
        print(
            f"[generate] attempt {attempt + 1}/{attempts}: requesting "
            f"{gen_cfg['max_tokens']} tokens...",
            flush=True,
        )
        try:
            draft, usage = client.chat_json(
                [{"role": "system", "content": system_prompt}, *messages],
                DRAFT_SCHEMA,
                gen_cfg,
            )
        except (InferenceError, ValueError) as exc:
            last_errors.append(f"model output could not be parsed: {exc}")
            print(f"[generate] attempt {attempt + 1} failed to parse: {exc}", flush=True)
            continue
        draft = normalize_macros(draft)
        errors = validate_draft(draft)
        print(
            f"[generate] attempt {attempt + 1}: "
            f"{usage.get('completion_tokens', '?')} tokens in {time.monotonic() - started:.0f}s — "
            + ("valid" if not errors else "validation failed: " + "; ".join(errors)),
            flush=True,
        )
        if not errors:
            return draft, usage
        last_errors = errors
        if attempt < gen_cfg["retries"]:
            messages = [*messages, {"role": "assistant", "content": json.dumps(draft, ensure_ascii=False)},
                        {"role": "user", "content": build_repair_prompt(errors)}]
    raise InferenceError("draft validation failed: " + "; ".join(last_errors))


def generate(args: Any, config: dict[str, Any]) -> dict[str, Any]:
    server_cfg = config["server"]
    gen_cfg = config["generation"]
    card_cfg = config["card"]
    path_cfg = config["paths"]

    client = LlamaClient(server_cfg["base_url"], server_cfg["model"], server_cfg["timeout_s"])
    models = client.models()
    if server_cfg["model"] not in models:
        raise InferenceError(
            f"configured model is not loaded. Server has: {', '.join(models) or '(none)'}"
        )

    system_prompt = build_system_prompt(args, gen_cfg, card_cfg)
    messages = [_user_message(args, card_cfg)]
    draft, usage = _generate_draft(client, system_prompt, messages, gen_cfg)

    card = build_card(draft, card_cfg)
    desc_tokens = client.tokenize(card["data"]["description"])
    budget = gen_cfg["max_description_tokens"]
    shortened = False
    if desc_tokens > budget:
        shorten_prompt = render(
            load("shorten.txt"),
            max_chars=str(gen_cfg.get("max_definition_chars", 6000)),
        )
        retry_messages = [
            _user_message(args, card_cfg),
            {"role": "assistant", "content": json.dumps(draft, ensure_ascii=False)},
            {"role": "user", "content": shorten_prompt},
        ]
        try:
            new_draft, new_usage = client.chat_json(
                [{"role": "system", "content": system_prompt}, *retry_messages],
                DRAFT_SCHEMA,
                gen_cfg,
            )
            new_draft = normalize_macros(new_draft)
            if not validate_draft(new_draft):
                new_card = build_card(new_draft, card_cfg)
                new_tokens = client.tokenize(new_card["data"]["description"])
                if new_tokens < desc_tokens:
                    draft, card, usage, desc_tokens = new_draft, new_card, new_usage, new_tokens
                    shortened = True
        except (InferenceError, ValueError):
            pass  # keep the first valid card; the token count is reported

    portrait_source = args.portrait or args.photo
    portrait = make_portrait(
        portrait_source,
        card_cfg["portrait_width"],
        card_cfg["portrait_height"],
        card["data"]["name"],
    )
    out_dir = Path(args.out or path_cfg["output_dir"])
    stem = slugify(card["data"]["name"])
    json_path = out_dir / f"{stem}.json"
    png_path = out_dir / f"{stem}.png"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_card_png(card, portrait, png_path, embed_ztxt=card_cfg["embed_ztxt_copies"])

    return {
        "card": card,
        "draft": draft,
        "json_path": json_path,
        "png_path": png_path,
        "portrait_png": portrait,
        "usage": usage,
        "description_tokens": desc_tokens,
        "total_tokens": client.tokenize(card_text(card)),
        "metrics": draft_metrics(draft),
        "shortened": shortened,
    }
