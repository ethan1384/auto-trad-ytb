from __future__ import annotations

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
    TranscriptSegment,
    TranscriptionProvider,
    TranslationProvider,
    TranslationResult,
    VoiceSynthesisProvider,
    replace_segment_text,
)
from app.storage import StorageClient


class MockTranscriptionProvider(TranscriptionProvider):
    def transcribe(self, audio_key: str, language: str | None = None) -> TranscriptResult:
        lang = language or "en"
        segments = [
            TranscriptSegment(0.0, 2.5, "Hello creators, welcome back."),
            TranscriptSegment(2.5, 5.0, "Today we translate this video."),
        ]
        return TranscriptResult(
            language=lang,
            segments=segments,
            raw_text=" ".join(s.text for s in segments),
        )


class MockTranslationProvider(TranslationProvider):
    def translate(
        self, transcript: TranscriptResult, source_language: str, target_language: str
    ) -> TranslationResult:
        mapping = {
            "en->fr": [
                "Bonjour les créateurs, content de vous revoir.",
                "Aujourd'hui, on traduit cette vidéo.",
            ],
            "en->es": [
                "Hola creadores, bienvenidos de nuevo.",
                "Hoy traducimos este video.",
            ],
        }
        lines = mapping.get(f"{source_language}->{target_language}")
        if not lines:
            lines = [f"[{target_language}] {s.text}" for s in transcript.segments]
        segments = [
            replace_segment_text(s, lines[i] if i < len(lines) else f"[{target_language}] {s.text}")
            for i, s in enumerate(transcript.segments)
        ]
        return TranslationResult(
            source_language=source_language,
            target_language=target_language,
            segments=segments,
            raw_text=" ".join(s.text for s in segments),
        )


class MockRewriteProvider(RewriteProvider):
    def rewrite(
        self,
        translation: TranslationResult,
        target_language: str,
        accent: str | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> RewriteResult:
        del progress
        # Light naturalization: keep text, mark as rewritten.
        text = translation.raw_text
        return RewriteResult(
            text=text,
            segments=list(translation.segments),
            meta={"provider": "mock", "lang": target_language, "accent": accent},
        )


class MockVoiceSynthesisProvider(VoiceSynthesisProvider):
    def __init__(self, storage: StorageClient) -> None:
        self.storage = storage

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
        del stop, progress
        payload = (
            f"MOCK AUDIO\nlang={target_language}\naccent={accent or ''}\n"
            f"text={script.text}\nref={voice_ref_key or 'none'}\n"
        )
        self.storage.put_bytes(output_key, payload.encode("utf-8"), "audio/wav")
        duration = max(1.0, sum(s.end - s.start for s in script.segments))
        return SynthesisResult(audio_key=output_key, duration_seconds=duration, meta={"provider": "mock"})


class MockLipSyncProvider(LipSyncProvider):
    def __init__(self, storage: StorageClient) -> None:
        self.storage = storage

    def sync(self, video_key: str, audio_key: str, output_key: str) -> LipSyncResult:
        payload = f"MOCK LIPSYNC\nvideo={video_key}\naudio={audio_key}\n"
        self.storage.put_bytes(output_key, payload.encode("utf-8"), "video/mp4")
        return LipSyncResult(video_key=output_key, meta={"provider": "mock"})


class MockMediaRenderer(MediaRenderer):
    def __init__(self, storage: StorageClient) -> None:
        self.storage = storage

    def extract_audio(self, video_key: str, output_key: str, voice_key: str | None = None) -> str:
        self.storage.put_bytes(output_key, f"MOCK WAV from {video_key}".encode(), "audio/wav")
        if voice_key:
            self.storage.put_bytes(voice_key, f"MOCK VOICE WAV from {video_key}".encode(), "audio/wav")
        return output_key

    def align_audio(self, audio_key: str, target_duration: float, output_key: str) -> str:
        self.storage.put_bytes(
            output_key,
            f"MOCK ALIGNED\nsrc={audio_key}\nduration={target_duration}".encode(),
            "audio/wav",
        )
        return output_key

    def render(
        self, video_key: str, audio_key: str, output_key: str, subtitle_text: str | None = None
    ) -> RenderResult:
        self.storage.put_bytes(
            output_key,
            f"MOCK RENDER\nvideo={video_key}\naudio={audio_key}\n".encode(),
            "video/mp4",
        )
        subtitle_key = None
        if subtitle_text:
            subtitle_key = output_key.rsplit(".", 1)[0] + ".srt"
            self.storage.put_bytes(subtitle_key, subtitle_text.encode("utf-8"), "application/x-subrip")
        return RenderResult(video_key=output_key, subtitle_key=subtitle_key, meta={"provider": "mock"})
