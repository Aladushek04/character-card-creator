"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from .client import InferenceError
from .generator import generate
from .prompts import build_brief, build_system_prompt
from .schema import draft_warnings

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else ROOT / "config.toml"
    with cfg_path.open("rb") as fh:
        return tomllib.load(fh)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate Character Tavern V3 character cards locally.")
    p.add_argument("--concept", help="one-paragraph description of the character")
    p.add_argument("--name", help="character name (default: model chooses)")
    p.add_argument("--setting", help="world / setting")
    p.add_argument("--extra", help="any additional requirements")
    p.add_argument("--tags", nargs="+", help="suggested lowercase tags")
    p.add_argument("--rating", "--content-rating", dest="content_rating",
                   choices=["spicy", "mature", "explicit"], help="adult content intensity")
    p.add_argument("--narrative-language", help="language of dialogue and greeting")
    p.add_argument("--definition-language", help="language of the definition")
    p.add_argument("--bio", help="text/markdown biography file used as a creation reference")
    p.add_argument("--photo", help="reference photo; also used as the card portrait (2:3 crop)")
    p.add_argument("--portrait", help="separate portrait image (overrides --photo for the image)")
    p.add_argument("--no-photo-in-prompt", action="store_true",
                   help="use --photo only as portrait, not as model input")
    p.add_argument("--out", help="output directory (default: generated/)")
    p.add_argument("--config", help="path to config.toml")
    p.add_argument("--interactive", "-i", action="store_true", help="ask for the brief interactively")
    p.add_argument("--dry-run", action="store_true", help="print the assembled prompts and exit")
    return p


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def interactive_args(args: argparse.Namespace) -> argparse.Namespace:
    args.concept = ask("Concept", args.concept or "")
    args.name = ask("Name (blank = model chooses)", args.name or "")
    args.setting = ask("Setting", args.setting or "")
    args.extra = ask("Extra requirements", args.extra or "")
    raw_tags = ask("Tags (space separated)", " ".join(args.tags or []))
    args.tags = raw_tags.split() or None
    photo = ask("Reference photo path (blank = none)", args.photo or "")
    args.photo = photo or None
    return args


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if args.interactive:
        args = interactive_args(args)
    if not args.concept:
        print("error: --concept is required (or use --interactive)", file=sys.stderr)
        return 2
    if args.photo and not Path(args.photo).is_file():
        print(f"error: photo not found: {args.photo}", file=sys.stderr)
        return 2
    if args.portrait and not Path(args.portrait).is_file():
        print(f"error: portrait not found: {args.portrait}", file=sys.stderr)
        return 2
    if args.bio and not Path(args.bio).is_file():
        print(f"error: biography not found: {args.bio}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("=== SYSTEM ===\n")
        print(build_system_prompt(args, config["generation"], config["card"]))
        print("\n=== USER ===\n")
        print(build_brief(args, config["card"]))
        return 0

    try:
        result = generate(args, config)
    except (InferenceError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    card = result["card"]
    print(f"\nName:      {card['data']['name']}")
    print(f"Tagline:   {result['draft']['tagline']}")
    print(f"Tags:      {', '.join(card['data']['tags'])}")
    m = result["metrics"]
    print(f"Definition:        {m['definition']} chars / {result['description_tokens']} tokens "
          f"(target {config['generation']['min_definition_chars']}-"
          f"{config['generation']['max_definition_chars']} chars)"
          + (" [shortened]" if result["shortened"] else ""))
    print(f"Greeting:          {m['greeting']} chars (target 800-3200)")
    print(f"Tagline:           {m['tagline']} chars (target 10-150)")
    print(f"Card tokens:       {result['total_tokens']}")
    for warning in draft_warnings(result["draft"]):
        print(f"Note: {warning}")
    print(f"Usage:             {json.dumps(result['usage'].get('completion_tokens', 0))} completion tokens")
    print(f"JSON:  {result['json_path']}")
    print(f"PNG:   {result['png_path']}")
    print("\nReminder: CT import leaves the Tagline empty and content warnings unticked. "
          "Set those in the Studio before publishing, and upload the portrait with a 2:3 image.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
