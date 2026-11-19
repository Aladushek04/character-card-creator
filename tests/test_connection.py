import json
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


LM_MODELS = {
    "models": [
        {
            "type": "llm",
            "key": "qwen3.8-27b-uncensored-hauhaucs-aggressive-mtp",
            "display_name": "Qwen3.8 27B Uncensored HauhauCS Aggressive",
            "quantization": {"name": "IQ3_M", "bits_per_weight": 3},
            "params_string": "27B",
            "max_context_length": 262144,
            "capabilities": {"vision": True, "trained_for_tool_use": True,
                             "reasoning": {"allowed_options": ["off", "on"], "default": "on"}},
            "loaded_instances": [{
                "id": "qwen3.8-27b-uncensored-hauhaucs-aggressive-mtp@iq3_m",
                "config": {"context_length": 65024},
            }],
        }
    ]
}


def fake_get_lmstudio(url, path):
    if path == "/health":
        raise OSError("unexpected endpoint")
    if path == "/v1/models":
        return {
            "object": "list",
            "data": [{"id": "qwen3.8-27b-uncensored-hauhaucs-aggressive-mtp@iq3_m",
                      "object": "model", "owned_by": "organization_owner"}],
        }
    if path == "/api/v1/models":
        return LM_MODELS
    raise OSError("unexpected endpoint")


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

    def test_error_object_from_props_is_not_misclassified(self):
        def getter(url, path):
            if path == "/props":
                return {"error": "Unexpected endpoint or method. (GET /props)"}
            if path == "/slots":
                return {"error": "Unexpected endpoint or method. (GET /slots)"}
            return fake_get_lmstudio(url, path)

        conn = ConnectionState("http://127.0.0.1:1234", get_json=getter)
        summary = conn.probe()
        self.assertEqual(summary["api_flavor"], "LM Studio")
        self.assertFalse(summary["props_available"])
        self.assertEqual(summary["context"], 65024)

    def test_lm_studio_probe(self):
        conn = ConnectionState(
            "http://127.0.0.1:1234", get_json=fake_get_lmstudio, allow_remote=False
        )
        summary = conn.probe()
        self.assertTrue(summary["online"])
        self.assertEqual(summary["api_flavor"], "LM Studio")
        self.assertEqual(summary["context"], 65024)
        self.assertEqual(summary["max_context"], 262144)
        self.assertTrue(summary["vision"])
        self.assertTrue(summary["ready"])
        details = summary["model_details"][summary["selected_model"]]
        self.assertEqual(details["quant"], "IQ3_M")
        self.assertEqual(details["key"], "qwen3.8-27b-uncensored-hauhaucs-aggressive-mtp")
        self.assertTrue(details["reasoning"])
        self.assertTrue(conn.make_client().disable_reasoning)

    def test_lm_studio_unloaded_is_not_ready(self):
        def getter(url, path):
            if path == "/api/v1/models":
                payload = json.loads(json.dumps(LM_MODELS))
                payload["models"][0]["loaded_instances"] = []
                return payload
            return fake_get_lmstudio(url, path)

        conn = ConnectionState("http://127.0.0.1:1234", get_json=getter)
        summary = conn.probe()
        self.assertEqual(summary["api_flavor"], "LM Studio")
        self.assertFalse(summary["ready"])
        self.assertEqual(summary["loaded_instances"], [])

    def test_lm_studio_load_model(self):
        calls = []

        def poster(url, path, payload):
            calls.append((path, payload))
            return {"status": "loaded"}

        conn = ConnectionState(
            "http://127.0.0.1:1234", get_json=fake_get_lmstudio, post_json=poster
        )
        conn.probe()
        conn.load_model(context_length=16384)
        self.assertEqual(calls[0][0], "/api/v1/models/load")
        self.assertEqual(calls[0][1]["context_length"], 16384)
        self.assertEqual(
            calls[0][1]["model"], "qwen3.8-27b-uncensored-hauhaucs-aggressive-mtp"
        )

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
