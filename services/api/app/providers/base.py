from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    source_text: str = ""


def replace_segment_text(segment: TranscriptSegment, text: str) -> TranscriptSegment:
    """New segment text, same timing, speaker, and original wording."""
    return TranscriptSegment(
        segment.start,
        segment.end,
        text,
        speaker=segment.speaker,
        source_text=segment.source_text or segment.text,
    )


@dataclass
class TranscriptResult:
    language: str
    segments: list[TranscriptSegment]
    raw_text: str


@dataclass
class TranslationResult:
    source_language: str
    target_language: str
    segments: list[TranscriptSegment]
    raw_text: str


@dataclass
class RewriteResult:
    text: str
    segments: list[TranscriptSegment]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SynthesisResult:
    audio_key: str
    duration_seconds: float
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class LipSyncResult:
    video_key: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderResult:
    video_key: str
    subtitle_key: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class TranscriptionProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_key: str, language: str | None = None) -> TranscriptResult: ...


class TranslationProvider(ABC):
    @abstractmethod
    def translate(
        self, transcript: TranscriptResult, source_language: str, target_language: str
    ) -> TranslationResult: ...


class RewriteProvider(ABC):
    @abstractmethod
    def rewrite(
        self,
        translation: TranslationResult,
        target_language: str,
        accent: str | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> RewriteResult: ...


class VoiceSynthesisProvider(ABC):
    @abstractmethod
    def synthesize(
        self,
        script: RewriteResult,
        voice_ref_key: str | None,
        target_language: str,
        output_key: str,
        accent: str | None = None,
        stop: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> SynthesisResult: ...


class LipSyncProvider(ABC):
    @abstractmethod
    def sync(self, video_key: str, audio_key: str, output_key: str) -> LipSyncResult: ...


class MediaRenderer(ABC):
    @abstractmethod
    def extract_audio(self, video_key: str, output_key: str, voice_key: str | None = None) -> str: ...

    @abstractmethod
    def align_audio(self, audio_key: str, target_duration: float, output_key: str) -> str: ...

    @abstractmethod
    def render(
        self, video_key: str, audio_key: str, output_key: str, subtitle_text: str | None = None
    ) -> RenderResult: ...
