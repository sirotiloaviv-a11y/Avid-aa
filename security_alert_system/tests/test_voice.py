"""Tests for the voice round trip: voice note in, voice note out.

The speech provider and Telegram are both stubbed, so these run with no API
key and no network. What they cover is the part this project owns: the reply
medium matching the question medium, and every failure path still delivering
the answer somehow.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from security_alert_system.config import Config
from security_alert_system.notifier import Notifier
from security_alert_system.sources.telegram_channels import TelegramChannelMonitor
from security_alert_system.state import StateStore
from security_alert_system.voice import (
    LocalWhisperVoice,
    NullSpeaker,
    OpenAIVoice,
    VoiceError,
    build_voice,
)

OGG = b"OggS\x00fake-opus-payload"


class StubTelegram:
    """Records what was sent and how — text vs voice is the thing under test."""

    def __init__(self, file_path="voice/file_1.oga", audio=OGG):
        self.texts: list[str] = []
        self.voices: list[bytes] = []
        self.downloads: list[str] = []
        self._file_path = file_path
        self._audio = audio

    async def send_message(self, chat_id, text, **_kw):
        self.texts.append(text)
        return {"message_id": len(self.texts)}

    async def send_voice(self, chat_id, audio, **_kw):
        self.voices.append(audio)
        return {"message_id": len(self.voices)}

    async def send_photo(self, *a, **k):
        return {}

    async def get_file_path(self, file_id):
        return self._file_path

    async def download_file(self, path, **_kw):
        self.downloads.append(path)
        return self._audio


class StubVoice:
    """A transcriber+speaker pair with controllable failures."""

    name = "stub"

    def __init__(self, heard="מה המצב?", audio=b"OggS-reply",
                 transcribe_error=None, speak_error=None):
        self._heard = heard
        self._audio = audio
        self._transcribe_error = transcribe_error
        self._speak_error = speak_error
        self.spoke: list[str] = []

    async def transcribe(self, audio, filename="voice.ogg"):
        if self._transcribe_error:
            raise self._transcribe_error
        return self._heard

    async def speak(self, text):
        if self._speak_error:
            raise self._speak_error
        self.spoke.append(text)
        return self._audio


class StubAssistant:
    def __init__(self, answer="הכול תקין."):
        self.answer = answer
        self.asked: list[str] = []

    async def reply(self, text):
        self.asked.append(text)
        return self.answer

    def reset(self):
        pass


class VoiceRoundTripCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, reply_mode="match", voice=None, assistant=None, telegram=None):
        config = Config()
        config.alert_chat_id = "42"
        config.assistant_enabled = True
        config.voice_enabled = True
        config.voice_reply_mode = reply_mode

        self.telegram = telegram or StubTelegram()
        self.voice = voice if voice is not None else StubVoice()
        self.assistant = assistant or StubAssistant()
        notifier = Notifier(self.telegram, "42")
        return TelegramChannelMonitor(
            config,
            self.telegram,
            notifier,
            StateStore(Path(self.tmp.name) / "seen.json"),
            assistant=self.assistant,
            transcriber=self.voice,
            speaker=self.voice,
        )

    @staticmethod
    def voice_update(chat_id="42"):
        return {
            "update_id": 1,
            "message": {
                "message_id": 5,
                "chat": {"id": chat_id, "type": "private"},
                "voice": {"file_id": "AwACAgQ", "duration": 3},
                "date": 1,
            },
        }

    @staticmethod
    def text_update(text="מה המצב?", chat_id="42"):
        return {
            "update_id": 2,
            "message": {
                "message_id": 6,
                "chat": {"id": chat_id, "type": "private"},
                "text": text,
                "date": 1,
            },
        }


class TestReplyMedium(VoiceRoundTripCase):
    async def test_voice_question_gets_a_voice_answer(self):
        monitor = self.build(reply_mode="match")
        await monitor._handle_update(self.voice_update())

        self.assertEqual(self.telegram.downloads, ["voice/file_1.oga"])
        self.assertEqual(self.assistant.asked, ["מה המצב?"])
        self.assertEqual(len(self.telegram.voices), 1)
        self.assertEqual(self.telegram.texts, [])   # nothing typed back

    async def test_typed_question_gets_a_typed_answer(self):
        monitor = self.build(reply_mode="match")
        await monitor._handle_update(self.text_update())

        self.assertEqual(len(self.telegram.texts), 1)
        self.assertEqual(self.telegram.voices, [])

    async def test_voice_mode_speaks_even_for_typed_questions(self):
        monitor = self.build(reply_mode="voice")
        await monitor._handle_update(self.text_update())
        self.assertEqual(len(self.telegram.voices), 1)
        self.assertEqual(self.telegram.texts, [])

    async def test_text_mode_never_speaks(self):
        monitor = self.build(reply_mode="text")
        await monitor._handle_update(self.voice_update())
        self.assertEqual(self.telegram.voices, [])
        self.assertEqual(len(self.telegram.texts), 1)

    async def test_both_mode_sends_each_once(self):
        monitor = self.build(reply_mode="both")
        await monitor._handle_update(self.voice_update())
        self.assertEqual(len(self.telegram.voices), 1)
        self.assertEqual(len(self.telegram.texts), 1)


class TestVoiceFailurePaths(VoiceRoundTripCase):
    """Every failure must still end with the owner getting an answer."""

    async def test_synthesis_failure_falls_back_to_text(self):
        voice = StubVoice(speak_error=VoiceError("tts down"))
        monitor = self.build(reply_mode="match", voice=voice)
        with self.assertLogs(
            "security_alert_system.sources.telegram_channels", "ERROR"
        ):
            await monitor._handle_update(self.voice_update())
        self.assertEqual(self.telegram.voices, [])
        self.assertEqual(len(self.telegram.texts), 1)
        self.assertIn("הכול תקין", self.telegram.texts[0])

    async def test_transcription_failure_reports_and_stops(self):
        voice = StubVoice(transcribe_error=VoiceError("stt down"))
        monitor = self.build(reply_mode="match", voice=voice)
        with self.assertLogs(
            "security_alert_system.sources.telegram_channels", "ERROR"
        ):
            await monitor._handle_update(self.voice_update())
        # The model is never asked about audio that could not be heard.
        self.assertEqual(self.assistant.asked, [])
        self.assertIn("לא הצלחתי לתמלל", self.telegram.texts[0])

    async def test_empty_transcript_is_not_sent_to_the_model(self):
        monitor = self.build(reply_mode="match", voice=StubVoice(heard="   "))
        await monitor._handle_update(self.voice_update())
        self.assertEqual(self.assistant.asked, [])

    async def test_voice_without_a_transcriber_says_so(self):
        config = Config()
        config.alert_chat_id = "42"
        config.assistant_enabled = True
        telegram = StubTelegram()
        monitor = TelegramChannelMonitor(
            config, telegram, Notifier(telegram, "42"),
            StateStore(Path(self.tmp.name) / "s.json"),
            assistant=StubAssistant(), transcriber=None, speaker=None,
        )
        await monitor._handle_update(self.voice_update())
        self.assertIn("תמלול לא מוגדר", telegram.texts[0])

    async def test_stranger_voice_note_is_ignored(self):
        monitor = self.build(reply_mode="match")
        with self.assertLogs(
            "security_alert_system.sources.telegram_channels", "WARNING"
        ):
            await monitor._handle_update(self.voice_update(chat_id="999"))
        # No download, no transcription, no model call — nothing paid for.
        self.assertEqual(self.telegram.downloads, [])
        self.assertEqual(self.assistant.asked, [])
        self.assertEqual(self.telegram.voices, [])


class TestBuildVoice(unittest.TestCase):
    def _config(self, **kw):
        config = Config()
        config.voice_enabled = True
        for key, value in kw.items():
            setattr(config, key, value)
        return config

    def test_disabled_returns_null_speaker(self):
        config = self._config()
        config.voice_enabled = False
        transcriber, speaker = build_voice(config)
        self.assertIsNone(transcriber)
        self.assertIsInstance(speaker, NullSpeaker)

    def test_openai_provider_pairs_one_object(self):
        config = self._config(voice_provider="openai", openai_api_key="sk-test")
        transcriber, speaker = build_voice(config)
        self.assertIsInstance(transcriber, OpenAIVoice)
        self.assertIs(transcriber, speaker)

    def test_local_provider_without_openai_key_has_no_speaker(self):
        config = self._config(voice_provider="local", openai_api_key="")
        transcriber, speaker = build_voice(config)
        self.assertIsInstance(transcriber, LocalWhisperVoice)
        self.assertIsInstance(speaker, NullSpeaker)

    def test_local_transcribe_with_hosted_speech(self):
        config = self._config(voice_provider="local", openai_api_key="sk-test")
        transcriber, speaker = build_voice(config)
        self.assertIsInstance(transcriber, LocalWhisperVoice)
        self.assertIsInstance(speaker, OpenAIVoice)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            build_voice(self._config(voice_provider="bogus"))

    def test_openai_requires_a_key(self):
        with self.assertRaises(ValueError):
            OpenAIVoice(api_key="")

    def test_null_speaker_returns_none(self):
        self.assertIsNone(asyncio.run(NullSpeaker().speak("שלום")))


class TestVoiceConfigValidation(unittest.TestCase):
    def test_voice_without_assistant_is_rejected(self):
        config = Config()
        config.bot_token, config.alert_chat_id = "t", "1"
        config.voice_enabled = True
        config.assistant_enabled = False
        self.assertTrue(any("nothing to talk to" in p for p in config.validate()))

    def test_openai_provider_needs_a_key(self):
        config = Config()
        config.bot_token, config.alert_chat_id = "t", "1"
        config.voice_enabled = True
        config.assistant_enabled = True
        config.anthropic_api_key = "sk-ant"
        config.voice_provider = "openai"
        self.assertTrue(any("OPENAI_API_KEY" in p for p in config.validate()))

    def test_bad_reply_mode_is_rejected(self):
        config = Config()
        config.bot_token, config.alert_chat_id = "t", "1"
        config.voice_reply_mode = "shout"
        self.assertTrue(any("VOICE_REPLY_MODE" in p for p in config.validate()))


if __name__ == "__main__":
    unittest.main()
