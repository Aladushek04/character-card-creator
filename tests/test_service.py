import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from cardgen.png_io import make_portrait, write_card_png
from cardgen.schema import build_card
from service.photo import UnderageSubject, analyze_photos, format_analyses
from service.store import CharacterStore

DRAFT = {
    "name": "Nyx",
    "tagline": "A nocturnal archivist who trades in secrets.",
    "description": ("{{char}} is 34. {{char}} watches {{user}} in silence. " * 90)[:3800],
    "first_mes": ("*{{char}} greets {{user}}.* " + "Rain taps the glass. " * 80)[:1200],
    "creator_notes": "A quiet archivist for slow-burn adult roleplay.",
    "tags": ["female", "nsfw", "mature", "adult"],
}
CARD_CFG = {"creator": "a1adu6ek", "character_version": "1.0"}

ANALYSIS = {
    "age_presentation": "adult",
    "overall": "tall woman",
    "hair": "platinum blonde",
    "eyes": "green",
    "face": "angular",
    "body_build": "curvy",
    "distinctive_marks": ["tattoo on wrist"],
    "attire": "silk robe",
    "intimate_features": {
        "chest": "full", "waist": "narrow", "hips": "wide", "legs": "long",
        "skin": "smooth", "intimate_attire": "lace", "notes": "visible tattoos",
    },
}


class FakeAnalysisClient:
    def __init__(self, underage_at=None):
        self.underage_at = underage_at
        self.calls = 0

    def chat_json(self, messages, schema, cfg):
        self.calls += 1
        result = json.loads(json.dumps(ANALYSIS))
        if self.underage_at == self.calls:
            result["age_presentation"] = "underage"
        return result, {"completion_tokens": 100}


class StoreTests(unittest.TestCase):
    def test_create_list_get_and_references(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = CharacterStore(root / "characters")
            photos = []
            for i in range(3):
                p = root / f"photo{i}.png"
                Image.new("RGB", (100 + i, 200), (30, 40, 50)).save(p)
                photos.append(p)
            card = build_card(DRAFT, CARD_CFG)
            slug = store.create(
                card,
                make_portrait(None, 800, 1200, "Nyx"),
                bio="A short biography",
                photos=photos,
                analyses=[ANALYSIS],
                brief="concept",
            )
            self.assertEqual(slug, "nyx")
            items = store.list()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["name"], "Nyx")
            got = store.get(slug)
            self.assertEqual(got["bio"], "A short biography")
            self.assertEqual(len(got["references"]), 3)
            self.assertEqual(got["meta"]["photo_analyses"], [ANALYSIS])
            self.assertTrue(got["portrait"].is_file())
            self.assertFalse((root / "characters" / slug / "chat.json").exists())

    def test_import_card(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = CharacterStore(root / "characters")
            card = build_card(DRAFT, CARD_CFG)
            src = write_card_png(
                card, make_portrait(None, 800, 1200, "Nyx"), root / "source.png"
            )
            slug = store.import_card(src)
            self.assertEqual(store.get(slug)["card"]["data"]["name"], "Nyx")
            self.assertTrue((root / "characters" / slug / "card.png").is_file())


class PhotoTests(unittest.TestCase):
    def test_analyze_multiple_and_format(self):
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for i in range(3):
                p = Path(td) / f"p{i}.png"
                Image.new("RGB", (60, 80), (10, 20, 30)).save(p)
                paths.append(p)
            client = FakeAnalysisClient()
            results = analyze_photos(client, paths, {"temperature": 0.2}, confirm_adult=True)
            self.assertEqual(len(results), 3)
            self.assertEqual(client.calls, 3)
            text = format_analyses(results)
            self.assertIn("PHOTO 1", text)
            self.assertIn("PHOTO 3", text)
            self.assertIn("platinum blonde", text)
            self.assertIn("Intimate attire: lace", text)

    def test_underage_photo_blocks_all(self):
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for i in range(3):
                p = Path(td) / f"p{i}.png"
                Image.new("RGB", (60, 80), (10, 20, 30)).save(p)
                paths.append(p)
            with self.assertRaises(UnderageSubject):
                analyze_photos(
                    FakeAnalysisClient(underage_at=2), paths,
                    {"temperature": 0.2}, confirm_adult=True,
                )


if __name__ == "__main__":
    unittest.main()
