import unittest

from middleware.interaction_core import InteractionCore
from middleware.medical_workflow import MedicalWorkflow
from middleware.interaction_delivery import DeliveryOrchestrator
from middleware.interaction_voice import CoreVoiceTurnProvider
from middleware.session import SessionStore
from middleware.voice import SpeechPayload, UploadedAudio, VoiceProviderSettings, VoiceTurn
from middleware.tests.test_interaction_core import FakeIntentRecognizer, FakePipeline


class FakeSpeechToText:
    def transcribe(self, audio, settings):
        return "預約醫療服務"


class FakeTextToSpeech:
    def synthesize(self, text, settings):
        return SpeechPayload(b"audio", "audio/mpeg")


class BrokenTextToSpeech:
    def synthesize(self, text, settings):
        raise RuntimeError("provider unavailable")


class CoreVoiceTurnProviderTests(unittest.TestCase):
    def test_audio_and_transcript_enter_the_same_core_contract(self):
        core = InteractionCore(
            SessionStore(),
            MedicalWorkflow(FakePipeline(), "PAT-DEMO-001", "Bearer demo"),
            intent_recognizer=FakeIntentRecognizer(),
        )
        provider = CoreVoiceTurnProvider(
            core,
            DeliveryOrchestrator(),
            stt=FakeSpeechToText(),
            tts=FakeTextToSpeech(),
            settings=VoiceProviderSettings(),
        )
        result = provider.handle_turn(VoiceTurn(
            session_id="S-VOICE-CORE",
            turn_id="T-1",
            audio=UploadedAudio(b"audio", "audio/webm"),
        ))
        self.assertEqual(result.metadata["task"]["current_step"], "select_service")
        self.assertEqual(result.metadata["speech_audio"]["status"], "ready")
        self.assertIsNotNone(result.speech)
        state = core.sessions.get_or_create("S-VOICE-CORE")
        self.assertEqual(state.task["type"], "medical_appointment")

    def test_tts_failure_does_not_fail_the_interaction(self):
        core = InteractionCore(
            SessionStore(),
            MedicalWorkflow(FakePipeline(), "PAT-DEMO-001", "Bearer demo"),
            intent_recognizer=FakeIntentRecognizer(),
        )
        provider = CoreVoiceTurnProvider(
            core,
            DeliveryOrchestrator(),
            stt=FakeSpeechToText(),
            tts=BrokenTextToSpeech(),
            settings=VoiceProviderSettings(),
        )
        result = provider.handle_turn(VoiceTurn(
            session_id="S-VOICE-TTS",
            turn_id="T-2",
            audio=UploadedAudio(b"audio", "audio/webm"),
        ))
        self.assertEqual(result.metadata["task"]["current_step"], "select_service")
        self.assertEqual(result.metadata["speech_audio"]["status"], "unavailable")
        self.assertIsNone(result.speech)


if __name__ == "__main__":
    unittest.main()
