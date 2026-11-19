import base64
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from cardgen.png_io import make_portrait, read_card, read_text_chunks, write_card_png
from cardgen.schema import (
    DRAFT_SCHEMA,
    build_card,
    normalize_macros,
    validate_draft,
)

CARD_CFG = {
    "creator": "a1adu6ek",
    "character_version": "1.0",
    "portrait_width": 800,
    "portrait_height": 1200,
}

_BASE = (
    "Language: {{char}} speaks in measured English and never raises her voice. "
    "Facts: {{char}} is 34 years old and keeps a ledger of other people's secrets. "
    "Appearance: tall, grey-eyed, always dressed in dark wool. "
    "Character and speech: {{char}} listens before answering and dislikes pretension. "
    "Behaviour: {{char}} never speaks or decides for {{user}}; she reacts only to what {{user}} does. "
    "Intimate behaviour: {{char}} is patient, attentive and explicit with consenting adults. "
    "Sample lines: \"Tell me what you came for, {{user}}.\"\n"
)


def make_draft(**overrides):
    draft = {
        "name": "Nyx",
        "tagline": "A nocturnal archivist who trades in other people's confessions.",
        "description": (_BASE * 8)[:3800],
        "first_mes": (
            "*{{char}} looks up from the ledger as {{user}} enters.* \"You are late.\"\n"
            + ("She closes the book slowly, watching the rain run down the glass. " * 18)
        )[:1200],
        "creator_notes": "A quiet, dangerous archivist for slow-burn adult roleplay.",
        "tags": ["female", "nsfw", "mature", "adult", "original-character", "mystery"],
    }
    draft.update(overrides)
    return draft


class SchemaTests(unittest.TestCase):
    def test_schema_reflects_ct_limits(self):
        p = DRAFT_SCHEMA["properties"]
        self.assertEqual((p["name"]["minLength"], p["name"]["maxLength"]), (3, 80))
        self.assertEqual((p["tagline"]["minLength"], p["tagline"]["maxLength"]), (10, 150))
        self.assertEqual((p["description"]["minLength"], p["description"]["maxLength"]), (1200, 6000))
        self.assertEqual((p["first_mes"]["minLength"], p["first_mes"]["maxLength"]), (800, 3200))

    def test_valid_draft(self):
        self.assertEqual(validate_draft(make_draft()), [])

    def test_missing_and_underage(self):
        bad = make_draft()
        bad.pop("tagline")
        bad["description"] += " She is a 16-year-old schoolgirl."
        errors = validate_draft(bad)
        self.assertTrue(any("tagline" in e for e in errors))
        self.assertTrue(any("underage" in e for e in errors))

    def test_underage_coding_without_age(self):
        bad = make_draft(description=(_BASE + " The story takes place in a high school setting. ") * 8)
        self.assertTrue(any("underage" in e for e in validate_draft(bad)))

    def test_w_plus_rejected(self):
        bad = make_draft(description=_BASE * 8 + '\nPersonality("shy" + "loyal")')
        self.assertTrue(any("W++" in e for e in validate_draft(bad)))

    def test_links_rejected_but_catbox_image_allowed(self):
        bad = make_draft(creator_notes="Get it at https://evil.example/payload")
        self.assertTrue(any("links are not allowed" in e for e in validate_draft(bad)))
        good = make_draft(first_mes=make_draft()["first_mes"] +
                          "\n![Room](https://files.catbox.moe/abc123.png)")
        self.assertEqual(validate_draft(good), [])

    def test_short_definition_is_spam(self):
        bad = make_draft(description="Too small. " * 25)
        self.assertTrue(any("definition" in e for e in validate_draft(bad)))

    def test_normalize_macros(self):
        draft = make_draft(
            description=("Nyx is 34 years old. Nyx watches {{user}} closely. " * 30)[:3800],
            first_mes="*Nyx greets {{user}}.* " + "Rain taps the glass. " * 60,
        )
        normalized = normalize_macros(draft)
        self.assertNotIn("Nyx", normalized["description"])
        self.assertIn("{{char}}", normalized["description"])
        self.assertNotIn("Nyx", normalized["first_mes"])
        self.assertIn("{{user}}", normalized["first_mes"])

    def test_build_card_layout(self):
        card = build_card(make_draft(), CARD_CFG)
        self.assertEqual(card["spec"], "chara_card_v3")
        self.assertEqual(card["spec_version"], "3.0")
        data = card["data"]
        for key in ("name", "nickname", "description", "tags", "creator", "character_version",
                    "mes_example", "extensions", "system_prompt", "post_history_instructions",
                    "first_mes", "alternate_greetings", "personality", "scenario",
                    "creator_notes", "character_book", "creation_date", "modification_date",
                    "group_only_greetings"):
            self.assertIn(key, data)
        self.assertEqual(data["nickname"], "Nyx")
        self.assertEqual(data["personality"], "")
        self.assertEqual(data["mes_example"], "")
        self.assertEqual(data["character_book"], None)
        self.assertIsInstance(data["creation_date"], int)


class PngTests(unittest.TestCase):
    def test_roundtrip_and_chunk_layout(self):
        card = build_card(make_draft(), CARD_CFG)
        portrait = make_portrait(None, 300, 450, "Nyx")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "nyx.png"
            write_card_png(card, portrait, out, embed_ztxt=True)
            raw = out.read_bytes()
            self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
            with Image.open(out) as im:
                self.assertEqual(im.size, (300, 450))
            chunks = read_text_chunks(out)
            self.assertIn("ccv3", chunks)
            self.assertIn("chara", chunks)
            self.assertEqual(json.loads(base64.b64decode(chunks["ccv3"]).decode()), card)
            self.assertEqual(read_card(out), card)
            pos = []
            idx = 8
            while idx + 12 <= len(raw):
                n = int.from_bytes(raw[idx : idx + 4], "big")
                kind = raw[idx + 4 : idx + 8].decode("latin1")
                if kind in ("tEXt", "zTXt", "IEND"):
                    pos.append(kind)
                idx += 12 + n
            self.assertEqual(pos[-5:], ["tEXt", "tEXt", "zTXt", "zTXt", "IEND"])

    def test_center_crop_to_2_3(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.png"
            Image.new("RGB", (1000, 600), (200, 100, 50)).save(src)
            portrait = make_portrait(src, 800, 1200)
            out = Path(td) / "portrait.png"
            out.write_bytes(portrait)
            with Image.open(out) as im:
                self.assertEqual(im.size, (800, 1200))


if __name__ == "__main__":
    unittest.main()
