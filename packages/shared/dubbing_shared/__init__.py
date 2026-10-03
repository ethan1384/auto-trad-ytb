"""Shared enums and helpers for API + worker."""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStage(StrEnum):
    INGEST = "ingest"
    EXTRACT_AUDIO = "extract_audio"
    TRANSCRIBE = "transcribe"
    TRANSLATE = "translate"
    REWRITE = "rewrite"
    SYNTHESIZE = "synthesize"
    ALIGN = "align"
    LIPSYNC = "lipsync"
    RENDER = "render"
    COMPLETE = "complete"


PIPELINE_ORDER: tuple[PipelineStage, ...] = (
    PipelineStage.INGEST,
    PipelineStage.EXTRACT_AUDIO,
    PipelineStage.TRANSCRIBE,
    PipelineStage.TRANSLATE,
    PipelineStage.REWRITE,
    PipelineStage.SYNTHESIZE,
    PipelineStage.ALIGN,
    PipelineStage.LIPSYNC,
    PipelineStage.RENDER,
    PipelineStage.COMPLETE,
)


class AssetKind(StrEnum):
    SOURCE_VIDEO = "source_video"
    AUDIO = "audio"
    TRANSCRIPT = "transcript"
    SCRIPT = "script"
    VOICE = "voice"
    RENDER = "render"
    SUBTITLES = "subtitles"
