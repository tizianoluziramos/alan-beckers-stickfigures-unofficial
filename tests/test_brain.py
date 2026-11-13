import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from desktop_ai.brain import BrainSettings, PERSONALITIES, Reaction, build_request, request_reaction, system_prompt


class ModelServer(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, dict(self.headers), payload))
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/stolen")
            self.end_headers()
            return
        if self.path.startswith("/error"):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"DO NOT ECHO SENSITIVE REQUEST CONTENT")
            return
        reaction = json.dumps({"speech": "¡Ajá, una ventana!", "action": "point", "emotion": "curious", "target_x": 0.8})
        if self.path.endswith("/api/chat"):
            result = {"message": {"content": reaction}}
        else:
            result = {"choices": [{"message": {"content": reaction}}]}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def log_message(self, *args):
        pass


class BrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ModelServer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        ModelServer.requests.clear()

    def test_real_ollama_request_includes_image_and_personality(self):
        result = request_reaction(BrainSettings(endpoint=self.endpoint), "Yellow", "¿Qué ves?", b"jpeg-image")
        path, headers, payload = ModelServer.requests[-1]
        self.assertEqual(path, "/api/chat")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["format"], "json")
        self.assertEqual(base64.b64decode(payload["messages"][-1]["images"][0]), b"jpeg-image")
        self.assertIn("Yellow", payload["messages"][0]["content"])
        self.assertEqual(result.action, "point")
        self.assertEqual(result.target_x, 0.8)

    def test_real_openai_request_uses_bearer_and_multimodal_content(self):
        request_reaction(BrainSettings("openai", self.endpoint + "/v1", "vision-model", "session-secret"), "Orange", "Mirá", b"jpeg")
        path, headers, payload = ModelServer.requests[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer session-secret")
        self.assertTrue(payload["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_text_only_turn_has_no_image_and_does_not_claim_vision(self):
        for provider in ("openai", "ollama"):
            _, _, payload = build_request(BrainSettings(provider, self.endpoint), "Blue", "Hola", None, [])
            turn = payload["messages"][-1]
            self.assertNotIn("images", turn)
            content = turn["content"] if provider == "ollama" else turn["content"][0]["text"]
            self.assertIn("no hay captura", content)
            self.assertNotIn("image_url", json.dumps(turn))

    def test_history_is_bounded(self):
        history = [{"role": "user", "content": str(i)} for i in range(30)]
        _, _, payload = build_request(BrainSettings(), "Green", "Hola", None, history)
        self.assertEqual(len(payload["messages"]), 14)
        self.assertEqual(payload["messages"][1]["content"], "18")

    def test_invalid_model_commands_cannot_escape_animation_protocol(self):
        reaction = Reaction.parse(json.dumps({"speech": "x" * 1000, "action": ["execute"], "emotion": {}, "target_x": float("nan")}))
        self.assertEqual(reaction.action, "idle")
        self.assertEqual(reaction.emotion, "calm")
        self.assertIsNone(reaction.target_x)
        self.assertEqual(len(reaction.speech), 180)
        self.assertEqual(Reaction.parse('{"target_x": 500}').target_x, 1)
        self.assertIsNone(Reaction.parse('{"target_x": true}').target_x)
        with self.assertRaises(ValueError):
            Reaction.parse('["not an object"]')
        with self.assertRaises(ValueError):
            Reaction.parse('not json')

    def test_fenced_json_is_supported(self):
        self.assertEqual(Reaction.parse('```json\n{"action":"wave"}\n```').action, "wave")

    def test_error_does_not_echo_response_body(self):
        with self.assertRaisesRegex(ValueError, "HTTP 401") as caught:
            request_reaction(BrainSettings(endpoint=self.endpoint + "/error"), "Red", "Hola")
        self.assertNotIn("SENSITIVE", str(caught.exception))

    def test_redirect_does_not_forward_credentials_or_capture(self):
        with self.assertRaisesRegex(ValueError, "HTTP 302"):
            request_reaction(BrainSettings("openai", self.endpoint + "/redirect", "vision", "secret"), "Red", "Mirá", b"private-image")
        self.assertEqual(len(ModelServer.requests), 1)

    def test_invalid_endpoints(self):
        for url in ("file:///tmp/config", "ftp://server", "https://key:secret@server", "https://server?q=secret"):
            with self.assertRaises(ValueError):
                BrainSettings(endpoint=url).validate()

    def test_every_character_has_a_resolved_prompt(self):
        for character in PERSONALITIES:
            prompt = system_prompt(character)
            self.assertNotIn("{{PERSONALITY}}", prompt)
            self.assertIn(PERSONALITIES[character][1], prompt)


if __name__ == "__main__":
    unittest.main()
