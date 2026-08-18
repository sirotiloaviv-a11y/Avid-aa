"""Voice in, voice out — talk to the assistant with headphones on.

Telegram already carries this: you hold the mic button, speak Hebrew, and the
bot receives a voice message. This module turns that into text, and turns the
answer back into a voice note that auto-plays in your ear. No second app, no
phone call, nothing to install on the phone.

    you (voice) ──► Telegram ──► transcribe ──► assistant ──► speak ──► voice note

FORMAT — the detail that makes or breaks it
-------------------------------------------
Telegram voice messages are **OPUS in an OGG container**, and ``sendVoice``
requires the same on the way back. Send an MP3 and Telegram accepts it but
renders a music file: no waveform, no auto-play, useless in a pocket. OpenAI's
speech endpoint can emit opus directly, so the round trip needs no ffmpeg and
no transcoding step.

PROVIDERS
---------
Claude does not do speech-to-text or text-to-speech, so this needs a second
provider. The interfaces below are the whole integration surface — swapping to
Google, Azure, ElevenLabs, or a local model is a new subclass and one config
line, not a rewrite.

* :class:`OpenAIVoice` — hosted, fast, good Hebrew, needs OPENAI_API_KEY.
* :class:`LocalWhisperVoice` — transcription only, runs on your own machine
  with no API key and no audio leaving it. Slower, and needs faster-whisper.

Written against the two HTTP endpoints directly rather than the openai SDK:
they are two stable calls, and httpx is already a dependency here.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

import httpx

log = logging.getLogger(__name__)

OPENAI_ROOT = "https://api.openai.com/v1"

# Telegram caps bot downloads at 20 MB; a voice note is far smaller, so
# anything near this is not speech and should not reach a paid endpoint.
MAX_AUDIO_BYTES = 20 * 1024 * 1024
# Speaking takes real time and real money. Past this the reply goes out as
# text instead of a two-minute monologue in his ear.
MAX_SPEAK_CHARS = 700


class VoiceError(RuntimeError):
    """Transcription or synthesis failed in a way worth reporting."""


class Transcriber(ABC):
    """Speech in."""

    name = "base"

    @abstractmethod
    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        """Return the spoken text, or "" when nothing intelligible was heard."""


class Speaker(ABC):
    """Speech out."""

    name = "base"

    @abstractmethod
    async def speak(self, text: str) -> bytes | None:
        """Return OGG/OPUS audio, or None when synthesis is unavailable."""


class OpenAIVoice(Transcriber, Speaker):
    """Hosted transcription and synthesis through the OpenAI audio endpoints."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        transcribe_model: str = "whisper-1",
        speak_model: str = "gpt-4o-mini-tts",
        voice: str = "shimmer",
        language: str = "he",
        timeout: int = 60,
    ):
        if not api_key:
            raise ValueError("OpenAI voice needs an API key.")
        self._api_key = api_key
        self._transcribe_model = transcribe_model
        self._speak_model = speak_model
        self._voice = voice
        self._language = language
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceError("audio is too large to transcribe")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(
                    f"{OPENAI_ROOT}/audio/transcriptions",
                    headers=self._headers(),
                    data={
                        "model": self._transcribe_model,
                        # Naming the language markedly improves Hebrew accuracy
                        # and stops short clips being detected as Arabic.
                        "language": self._language,
                        "response_format": "text",
                    },
                    files={"file": (filename, audio, "audio/ogg")},
                )
            except httpx.HTTPError as exc:
                raise VoiceError(f"transcription request failed: {exc}") from exc

        if response.status_code >= 400:
            raise VoiceError(
                f"transcription failed: HTTP {response.status_code} {response.text[:200]}"
            )
        return response.text.strip()

    async def speak(self, text: str) -> bytes | None:
        text = text.strip()
        if not text:
            return None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(
                    f"{OPENAI_ROOT}/audio/speech",
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json={
                        "model": self._speak_model,
                        "input": text[:MAX_SPEAK_CHARS],
                        "voice": self._voice,
                        # opus in ogg — exactly what sendVoice wants, so there
                        # is no transcoding step and no ffmpeg dependency.
                        "response_format": "opus",
                    },
                )
            except httpx.HTTPError as exc:
                raise VoiceError(f"speech request failed: {exc}") from exc

        if response.status_code >= 400:
            raise VoiceError(
                f"speech failed: HTTP {response.status_code} {response.text[:200]}"
            )
        return response.content


class LocalWhisperVoice(Transcriber):
    """Transcribe on your own machine — no API key, no audio leaving the host.

    Needs ``faster-whisper`` (``pip install faster-whisper``). The model is
    loaded once on first use and kept; the first call therefore pays a download
    and load cost that later calls do not. Runs in a worker thread because the
    underlying library is synchronous and would otherwise stall the event loop
    and the alert monitor along with it.
    """

    name = "local-whisper"

    def __init__(self, model_size: str = "small", language: str = "he", device: str = "cpu"):
        self._model_size = model_size
        self._language = language
        self._device = device
        self._model = None
        self._lock = asyncio.Lock()

    async def _ensure_model(self):
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:  # pragma: no cover - env dependent
                    raise VoiceError(
                        "faster-whisper is not installed; pip install faster-whisper"
                    ) from exc
                log.info("Loading whisper model '%s' (first use is slow).", self._model_size)
                self._model = await asyncio.to_thread(
                    WhisperModel, self._model_size, device=self._device, compute_type="int8"
                )
        return self._model

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        import tempfile
        from pathlib import Path

        model = await self._ensure_model()

        def run() -> str:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / filename
                path.write_bytes(audio)
                segments, _info = model.transcribe(str(path), language=self._language)
                return " ".join(segment.text for segment in segments).strip()

        return await asyncio.to_thread(run)


class NullSpeaker(Speaker):
    """No synthesis configured — replies stay text."""

    name = "none"

    async def speak(self, text: str) -> bytes | None:
        return None


def build_voice(config) -> tuple[Transcriber | None, Speaker]:
    """Assemble the pair named by config. Returns (transcriber, speaker)."""
    provider = (config.voice_provider or "").strip().lower()

    if not config.voice_enabled or provider in {"", "none"}:
        return None, NullSpeaker()

    if provider == "openai":
        voice = OpenAIVoice(
            api_key=config.openai_api_key,
            transcribe_model=config.voice_transcribe_model,
            speak_model=config.voice_speak_model,
            voice=config.voice_name,
        )
        return voice, voice

    if provider == "local":
        transcriber = LocalWhisperVoice(model_size=config.voice_whisper_model)
        # Local transcription with no local synthesis: he can speak to it, it
        # answers in text. Deliberate — offline Hebrew TTS is poor enough that
        # a bad voice is worse than no voice.
        if config.openai_api_key:
            return transcriber, OpenAIVoice(
                api_key=config.openai_api_key,
                speak_model=config.voice_speak_model,
                voice=config.voice_name,
            )
        return transcriber, NullSpeaker()

    raise ValueError(f"Unknown VOICE_PROVIDER '{provider}' (use openai, local or none)")
