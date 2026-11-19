import unittest

from service.connection import ConnectionState

HEALTH = {"status": "ok"}
MODELS = {
    "object": "list",
    "data": [
        {"id": "model-a", "object": "model", "owned_by": "local", "modalities": ["text", "image"]},
        {"id": "model-b", "object": "model", "owned_by": "local", "modalities": ["text"]},
    ],
}
PROPS = {
    "default_generation_settings": {"n_ctx": 65536},
    "model_alias": "model-a",
    "model_path": "E:/models/model-a.gguf",
    "modalities": {"vision": True, "video": False, "audio": False},
    "build_info": "bmoe 0.46.0",
    "is_sleeping": False,
    "total_slots": 1,
}
SLOTS = [{"id": 0, "n_ctx": 65536, "is_processing": False}]


def fake_get(url, path):
    return {
        "/health": HEALTH,
        "/v1/models": MODELS,
        "/props": PROPS,
        "/slots": SLOTS,
    }[path]


def fake_get_no_props(url, path):
    if path == "/props":
        raise OSError("404")
    return fake_get(url, path)


class ConnectionTests(unittest.TestCase):
    def make(self, get_json=fake_get, **kwargs):
        return ConnectionState(
            "http://127.0.0.1:8765", get_json=get_json, allow_remote=False, **kwargs
        )

    def test_loopback_only(self):
        conn = self.make()
        self.assertEqual(conn.validate("http://localhost:8080/"), "http://localhost:8080")
        with self.assertRaises(ValueError):
            conn.validate("http://example.com:8080")
        with self.assertRaises(ValueError):
            conn.validate("ftp://127.0.0.1:8765")
        remote = self.make()
        remote.allow_remote = True
        self.assertEqual(remote.validate("http://example.com:8080"), "http://example.com:8080")

    def test_probe_full_capabilities(self):
        conn = self.make()
        summary = conn.probe()
        self.assertTrue(summary["online"])
        self.assertTrue(summary["ready"])
        self.assertEqual(summary["context"], 65536)
        self.assertTrue(summary["vision"])
        self.assertEqual(summary["loaded_model"], "model-a")
        self.assertEqual(summary["selected_model"], "model-a")
        self.assertEqual(len(summary["models"]), 2)
        self.assertEqual(summary["build_info"], "bmoe 0.46.0")
        self.assertEqual(summary["slots"][0]["n_ctx"], 65536)

    def test_probe_without_props(self):
        conn = self.make(fake_get_no_props)
        summary = conn.probe()
        self.assertFalse(summary["props_available"])
        self.assertEqual(summary["context"], 65536)  # from /slots
        self.assertTrue(summary["vision"])  # from /v1/models modalities
        self.assertEqual(summary["loaded_model"], "")

    def test_offline(self):
        def offline(url, path):
            raise OSError("connection refused")

        conn = self.make(offline)
        summary = conn.probe()
        self.assertFalse(summary["online"])
        self.assertFalse(summary["ready"])
        self.assertIn("connection refused", summary["error"])

    def test_model_selection_and_override(self):
        conn = self.make()
        conn.probe()
        conn.set_model("model-b")
        self.assertEqual(conn.selected_model, "model-b")
        conn.set_model("missing")
        self.assertEqual(conn.selected_model, "model-b")
        client = conn.make_client()
        self.assertEqual(client.model, "model-b")
        self.assertEqual(client.base_url, "http://127.0.0.1:8765")
        config = {"server": {"base_url": "old", "model": "old", "timeout_s": 5}, "generation": {}}
        overridden = conn.config_override(config)
        self.assertEqual(overridden["server"]["base_url"], "http://127.0.0.1:8765")
        self.assertEqual(overridden["server"]["model"], "model-b")
        self.assertEqual(config["server"]["base_url"], "old")


if __name__ == "__main__":
    unittest.main()
