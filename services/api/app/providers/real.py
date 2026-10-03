from __future__ import annotations

"""Real provider stubs — wired later behind the same interfaces as mocks."""

from collections.abc import Callable

from app.providers.base import (
    LipSyncProvider,
    LipSyncResult,
    MediaRenderer,
    RenderResult,
    RewriteProvider,
    RewriteResult,
    SynthesisResult,
    TranscriptResult,
    TranscriptionProvider,
    TranslationProvider,
    TranslationResult,
    VoiceSynthesisProvider,
)


class FasterWhisperTranscriptionProvider(TranscriptionProvider):
    def transcribe(self, audio_key: str, language: str | None = None) -> TranscriptResult:
        raise NotImplementedError("faster-whisper integration pending; use PROVIDER_MODE=mock")


class ArgosTranslationProvider(TranslationProvider):
    def translate(
        self, transcript: TranscriptResult, source_language: str, target_language: str
    ) -> TranslationResult:
        raise NotImplementedError("Argos Translate integration pending; use PROVIDER_MODE=mock")


class VllmRewriteProvider(RewriteProvider):
    def rewrite(
        self,
        translation: TranslationResult,
        target_language: str,
        accent: str | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> RewriteResult:
        del accent, progress
        raise NotImplementedError("vLLM rewrite integration pending; use PROVIDER_MODE=mock")


class OmniVoiceSynthesisProvider(VoiceSynthesisProvider):
    def synthesize(
        self,
        script: RewriteResult,
        voice_ref_key: str | None,
        target_language: str,
        output_key: str,
        accent: str | None = None,
        stop: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> SynthesisResult:
        del accent, stop, progress
        raise NotImplementedError("OmniVoice integration pending; use PROVIDER_MODE=mock")


class DisabledLipSyncProvider(LipSyncProvider):
    def sync(self, video_key: str, audio_key: str, output_key: str) -> LipSyncResult:
        raise NotImplementedError(
            "Mouth redraw is disabled. The original picture is kept; use PROVIDER_MODE=local."
        )


class FfmpegMediaRenderer(MediaRenderer):
    def extract_audio(self, video_key: str, output_key: str, voice_key: str | None = None) -> str:
        del voice_key
        raise NotImplementedError("FFmpeg extract pending; use PROVIDER_MODE=mock")

    def align_audio(self, audio_key: str, target_duration: float, output_key: str) -> str:
        raise NotImplementedError("FFmpeg align pending; use PROVIDER_MODE=mock")

    def render(
        self, video_key: str, audio_key: str, output_key: str, subtitle_text: str | None = None
    ) -> RenderResult:
        raise NotImplementedError("FFmpeg render pending; use PROVIDER_MODE=mock")
