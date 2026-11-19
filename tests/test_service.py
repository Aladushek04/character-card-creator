import json
import tempfile
import unittest
from pathlib import Path

from cardgen.png_io import make_portrait
from cardgen.schema import build_card
from service.chat import ChatEngine
from service.photo import format_analysis
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


class FakeClient:
    def tokenize(self, text: str) -> int:
        return len(text) // 4

    def chat_text(self, messages, gen_cfg, max_tokens=256) -> str:
        return "Я отвечаю как персонаж."


class StoreTests(unittest.TestCase):
    def test_create_list_get_chat(self):
        with tempfile.TemporaryDirectory() as td:
            store = CharacterStore(Path(td) / "characters")
            card = build_card(DRAFT, CARD_CFG)
            portrait = make_portrait(None, 800, 1200, "Nyx")
            slug = store.create(
                card, portrait, bio="A short biography", analysis={"overall": "tall"},
                brief="concept",
            )
            self.assertEqual(slug, "nyx")
            items = store.list()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["name"], "Nyx")
            got = store.get(slug)
            self.assertEqual(got["chat"], [])
            self.assertEqual(got["bio"], "A short biography")
            self.assertEqual(got["meta"]["photo_analysis"]["overall"], "tall")
            self.assertTrue(got["portrait"].is_file())
            store.save_chat(slug, [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ])
            self.assertEqual(len(store.get(slug)["chat"]), 2)
            store.clear_chat(slug)
            self.assertEqual(store.get(slug)["chat"], [])

    def test_import_card(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = CharacterStore(root / "characters")
            card = build_card(DRAFT, CARD_CFG)
            from cardgen.png_io import write_card_png

            src = write_card_png(
                card, make_portrait(None, 800, 1200, "Nyx"), root / "source.png"
            )
            slug = store.import_card(src)
            self.assertEqual(store.get(slug)["card"]["data"]["name"], "Nyx")
            self.assertTrue((root / "characters" / slug / "card.png").is_file())


class ChatTests(unittest.TestCase):
    def test_one_character_one_chat_and_trimming(self):
        with tempfile.TemporaryDirectory() as td:
            store = CharacterStore(Path(td) / "characters")
            card = build_card(DRAFT, CARD_CFG)
            slug = store.create(card, make_portrait(None, 800, 1200, "Nyx"))
            engine = ChatEngine(store, FakeClient(), {
                "generation": {"temperature": 0.9, "top_p": 0.95, "top_k": 40,
                               "repeat_penalty": 1.05, "max_tokens": 100},
                "service": {"chat_context_budget": 10, "chat_max_tokens": 50},
            })
            reply = engine.send(slug, "Привет")
            self.assertEqual(reply, "Я отвечаю как персонаж.")
            self.assertEqual(len(store.get(slug)["chat"]), 2)

            # A second character must not see the first character's history.
            other = dict(DRAFT, name="Iris")
            slug2 = store.create(build_card(other, CARD_CFG), make_portrait(None, 800, 1200, "Iris"))
            self.assertEqual(store.get(slug2)["chat"], [])
            engine.send(slug2, "Привет")
            self.assertEqual(len(store.get(slug)["chat"]), 2)
            self.assertEqual(len(store.get(slug2)["chat"]), 2)

    def test_system_prompt_is_character_specific(self):
        with tempfile.TemporaryDirectory() as td:
            store = CharacterStore(Path(td) / "characters")
            card = build_card(DRAFT, CARD_CFG)
            slug = store.create(card, make_portrait(None, 800, 1200, "Nyx"))
            engine = ChatEngine(store, FakeClient(), {"generation": {}, "service": {}})
            prompt = engine.system_prompt(store.get(slug))
            self.assertIn("Nyx", prompt)
            self.assertNotIn("{{char}}", prompt)
            self.assertNotIn("{{user}}", prompt)
            self.assertIn("Never speak", prompt)


class PhotoTests(unittest.TestCase):
    def test_format_analysis(self):
        text = format_analysis({
            "overall": "tall woman",
            "hair": "platinum blonde",
            "eyes": "green",
            "face": "angular",
            "body_build": "curvy",
            "distinctive_marks": ["tattoo on wrist"],
            "attire": "silk robe",
            "intimate_features": {"chest": "full", "waist": "narrow", "hips": "wide",
                                  "legs": "long", "skin": "smooth",
                                  "intimate_attire": "lace", "notes": "visible tattoos"},
        })
        self.assertIn("platinum blonde", text)
        self.assertIn("Intimate attire: lace", text)
        self.assertIn("tattoo on wrist", text)


if __name__ == "__main__":
    unittest.main()
