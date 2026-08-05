import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from middleware.intent import KeywordIntentRecognizer
from middleware.server import create_application, create_http_server
from middleware.voice import (
    MAX_AUDIO_BYTES,
    SpeechPayload,
    UnavailableVoiceTurnProvider,
    VoiceProviderSettings,
    VoiceProviderError,
    VoiceTurnResult,
)
from middleware.voice_transport import parse_voice_multipart


def multipart(fields, audio, content_type="audio/webm", boundary="PonteVoiceBoundary"):
    parts = []
    for name, value in fields.items():
        parts.extend((
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode(),
            b"\r\n",
        ))
    parts.extend((
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="audio"; filename="turn.webm"\r\n',
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        audio,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ))
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


class FakeMcpClient:
    def start(self):
        return None

    def close(self):
        return None

    def call_tool(self, name, arguments):
        return {"request_id": "REQ-VOICE-TEST", "data": {}}


class FakeVoiceProvider:
    def __init__(self):
        self.turns = []

    def handle_turn(self, turn):
        self.turns.append(turn)
        return VoiceTurnResult(
            {"transcript": "test transcript", "handled": True},
            SpeechPayload(b"fake-speech", "audio/mpeg"),
        )


class VoiceMultipartTests(unittest.TestCase):
    def test_parser_accepts_webm_and_ogg(self):
        for content_type in ("audio/webm", "audio/ogg"):
            header, body = multipart(
                {"session_id": "S-voice", "turn_id": "T-1"},
                b"audio-bytes",
                content_type,
            )
            turn = parse_voice_multipart(header, body)
            self.assertEqual(turn.audio.content_type, content_type)
            self.assertEqual(turn.session_id, "S-voice")

    def test_parser_rejects_unsupported_type_and_oversized_audio(self):
        header, body = multipart(
            {"session_id": "S-voice", "turn_id": "T-1"}, b"audio", "audio/mp4"
        )
        with self.assertRaisesRegex(ValueError, "content type"):
            parse_voice_multipart(header, body)

        header, body = multipart(
            {"session_id": "S-voice", "turn_id": "T-1"}, b"x" * (MAX_AUDIO_BYTES + 1)
        )
        with self.assertRaisesRegex(ValueError, "must not exceed"):
            parse_voice_multipart(header, body)

    def test_parser_validates_required_identifiers(self):
        header, body = multipart({"session_id": "has spaces", "turn_id": "T-1"}, b"audio")
        with self.assertRaisesRegex(ValueError, "session_id"):
            parse_voice_multipart(header, body)

    def test_unavailable_provider_is_explicit(self):
        header, body = multipart({"session_id": "S-voice", "turn_id": "T-1"}, b"audio")
        with self.assertRaises(VoiceProviderError) as raised:
            UnavailableVoiceTurnProvider().handle_turn(parse_voice_multipart(header, body))
        self.assertEqual(raised.exception.code, "VOICE_PROVIDER_UNAVAILABLE")

    def test_cloud_adapter_settings_are_configurable_without_selecting_a_vendor(self):
        settings = VoiceProviderSettings.from_env({
            "PONTE_VOICE_STT_URL": "https://speech.example/transcribe",
            "PONTE_VOICE_STT_MODEL": "asr-model",
            "PONTE_VOICE_TTS_URL": "https://speech.example/synthesize",
            "PONTE_VOICE_TTS_VOICE": "cantonese",
        })
        self.assertEqual(settings.stt_model, "asr-model")
        self.assertEqual(settings.tts_voice, "cantonese")
        with self.assertRaisesRegex(ValueError, "PONTE_VOICE_STT_URL"):
            VoiceProviderSettings.from_env({"PONTE_VOICE_STT_URL": "file:///not-a-service"})


class VoiceRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = FakeVoiceProvider()
        cls.application = create_application(
            "http://backend.test",
            "PAT-DEMO-001",
            "Bearer test",
            mcp_client=FakeMcpClient(),
            intent_recognizer=KeywordIntentRecognizer(),
            voice_turn_provider=cls.provider,
        )
        cls.server = create_http_server("127.0.0.1", 0, cls.application)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, data=None, headers=None):
        request = Request(self.base_url + path, data=data, method=method, headers=headers or {})
        return self.opener.open(request)

    def test_post_returns_metadata_and_get_returns_session_bound_speech(self):
        content_type, body = multipart({"session_id": "S-route", "turn_id": "T-route"}, b"webm")
        with self.request("POST", "/api/voice/turn", body, {"Content-Type": content_type}) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["result"]["transcript"], "test transcript")
        self.assertEqual(payload["voice_turn"]["audio"]["byte_length"], 4)
        self.assertEqual(
            payload["voice_turn"]["speech"]["url"],
            "/api/voice/turn/T-route/speech?session_id=S-route",
        )
        self.assertEqual(self.provider.turns[-1].audio.content, b"webm")

        with self.request("GET", "/api/voice/turn/T-route/speech?session_id=S-route") as response:
            self.assertEqual(response.headers["Content-Type"], "audio/mpeg")
            self.assertEqual(response.read(), b"fake-speech")

        with self.assertRaises(HTTPError) as raised:
            self.request("GET", "/api/voice/turn/T-route/speech?session_id=S-other")
        self.assertEqual(raised.exception.code, 404)
        self.assertEqual(json.loads(raised.exception.read())["error"]["code"], "SPEECH_NOT_FOUND")

    def test_route_rejects_oversized_and_invalid_audio_before_provider(self):
        content_type, body = multipart({"session_id": "S-limit", "turn_id": "T-limit"}, b"x" * (MAX_AUDIO_BYTES + 1))
        with self.assertRaises(HTTPError) as raised:
            self.request("POST", "/api/voice/turn", body, {"Content-Type": content_type})
        self.assertEqual(raised.exception.code, 413)
        self.assertEqual(json.loads(raised.exception.read())["error"]["code"], "VOICE_AUDIO_TOO_LARGE")

        content_type, body = multipart({"session_id": "S-bad", "turn_id": "T-bad"}, b"audio", "audio/mp4")
        with self.assertRaises(HTTPError) as raised:
            self.request("POST", "/api/voice/turn", body, {"Content-Type": content_type})
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(json.loads(raised.exception.read())["error"]["code"], "INVALID_VOICE_REQUEST")


if __name__ == "__main__":
    unittest.main()
