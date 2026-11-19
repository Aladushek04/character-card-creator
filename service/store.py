"""Filesystem storage for generated characters (no chat state)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from cardgen.generator import slugify
from cardgen.png_io import read_card, write_card_png


class CharacterStore:
    def __init__(self, root: str | Path = "characters"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, slug: str) -> Path:
        target = self.root / slug
        if not target.is_dir() or not (target / "card.json").is_file():
            raise KeyError(f"unknown character: {slug}")
        return target

    def list(self) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self.root.iterdir()):
            card_file = path / "card.json"
            if not path.is_dir() or not card_file.is_file():
                continue
            try:
                card = json.loads(card_file.read_text(encoding="utf-8"))
                items.append(
                    {
                        "slug": path.name,
                        "name": card["data"].get("name", path.name),
                        "tagline": card["data"].get("creator_notes", "")[:90],
                        "has_portrait": (path / "card.png").is_file(),
                    }
                )
            except (OSError, ValueError, KeyError):
                continue
        return items

    def get(self, slug: str) -> dict[str, Any]:
        path = self._dir(slug)
        card = json.loads((path / "card.json").read_text(encoding="utf-8"))
        meta_path = path / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        bio = path / "bio.txt"
        return {
            "slug": slug,
            "path": path,
            "card": card,
            "meta": meta,
            "bio": bio.read_text(encoding="utf-8") if bio.is_file() else "",
            "portrait": path / "card.png" if (path / "card.png").is_file() else None,
            "references": sorted((path / "references").glob("*")) if (path / "references").is_dir() else [],
        }

    def create(
        self,
        card: dict[str, Any],
        portrait_png: bytes,
        *,
        bio: str = "",
        photos: list[str | Path] | None = None,
        analyses: list[dict[str, Any]] | None = None,
        brief: str = "",
    ) -> str:
        name = card["data"]["name"]
        base = slugify(name)
        slug = base
        counter = 2
        while (self.root / slug).exists():
            slug = f"{base}_{counter}"
            counter += 1
        path = self.root / slug
        path.mkdir(parents=True, exist_ok=True)

        (path / "card.json").write_text(
            json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_card_png(card, portrait_png, path / "card.png")
        if bio:
            (path / "bio.txt").write_text(bio, encoding="utf-8")
        if photos:
            ref_dir = path / "references"
            ref_dir.mkdir(parents=True, exist_ok=True)
            for index, photo in enumerate(photos, start=1):
                suffix = Path(photo).suffix.lower() or ".png"
                shutil.copyfile(photo, ref_dir / f"{index:02d}{suffix}")
        (path / "meta.json").write_text(
            json.dumps(
                {
                    "slug": slug,
                    "tagline": "",  # CT Studio still requires this manually
                    "photo_analyses": analyses or [],
                    "brief": brief,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return slug

    def import_card(self, source: str | Path) -> str:
        """Import an existing CT PNG/JSON card into the library."""
        source = Path(source)
        card = read_card(source) if source.suffix.lower() == ".png" else json.loads(
            source.read_text(encoding="utf-8")
        )
        if source.suffix.lower() == ".png":
            portrait_png = source.read_bytes()
        else:
            from cardgen.png_io import make_portrait

            portrait_png = make_portrait(None, 800, 1200, card["data"].get("name", ""))
        return self.create(card, portrait_png, brief=f"Imported from {source.name}")
