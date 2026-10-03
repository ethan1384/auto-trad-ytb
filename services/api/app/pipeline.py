from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from dubbing_shared import PIPELINE_ORDER, AssetKind, JobStatus, PipelineStage, StageStatus
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Asset, Job, JobStage
from app.providers import get_providers
from app.providers.voice_clone import JobStopped as CloneStopped
from app.providers.ffmpeg_tools import segments_to_srt
from app.providers.speakers import labeled_text, speaker_ids
from app.storage import StorageClient

log = logging.getLogger(__name__)


class JobStopped(Exception):
    """The user stopped this job. Leave the cancelled row as it is."""


class PipelineRunner:
    """Executes a single job end-to-end using configured providers."""

    def __init__(self, db: Session, storage: StorageClient | None = None) -> None:
        self.db = db
        self.storage = storage or StorageClient()
        self.providers = get_providers(storage=self.storage)

    def run(self, job_id: uuid.UUID) -> None:
        job = self.db.scalars(
            select(Job).where(Job.id == job_id).options(selectinload(Job.stages), selectinload(Job.project))
        ).one()
        if job.status == JobStatus.CANCELLED:
            log.info("job %s was stopped before it started", job_id)
            return
        job.status = JobStatus.RUNNING
        self.db.commit()

        try:
            source = self._source_video(job.project_id)
            if not source:
                raise RuntimeError("Source video is missing or incomplete. Upload the file again.")

            video_key = source.storage_key
            audio_key = ""
            voice_key = ""
            transcript = None
            translation = None
            rewrite = None
            synth = None
            aligned_key = ""
            lipsync = None

            for stage_name in PIPELINE_ORDER:
                self._ensure_active(job)
                stage = self._stage(job, stage_name)
                log.info("job %s stage %s", job.id, stage_name)
                self._mark_running(job, stage)
                detail: dict = {}

                if stage_name == PipelineStage.INGEST:
                    detail = {"storage_key": video_key}
                elif stage_name == PipelineStage.EXTRACT_AUDIO:
                    audio_key = f"projects/{job.project_id}/audio/{job.id}.wav"
                    voice_key = f"projects/{job.project_id}/audio/{job.id}.voice.wav"
                    self.providers.media.extract_audio(video_key, audio_key, voice_key=voice_key)
                    self._save_asset(job.project_id, AssetKind.AUDIO, audio_key, "audio/wav")
                    detail = {"audio_key": audio_key, "voice_key": voice_key}
                elif stage_name == PipelineStage.TRANSCRIBE:
                    transcript = self.providers.transcription.transcribe(
                        audio_key, language=job.project.source_language
                    )
                    t_key = f"projects/{job.project_id}/transcript/{job.id}.json"
                    self.storage.put_json(
                        t_key,
                        {
                            "language": transcript.language,
                            "text": transcript.raw_text,
                            "segments": [s.__dict__ for s in transcript.segments],
                        },
                    )
                    self._save_asset(job.project_id, AssetKind.TRANSCRIPT, t_key, "application/json")
                    detail = {
                        "text": labeled_text(transcript.segments) or transcript.raw_text,
                        "speakers": speaker_ids(transcript.segments),
                    }
                elif stage_name == PipelineStage.TRANSLATE:
                    assert transcript is not None
                    translation = self.providers.translation.translate(
                        transcript, job.project.source_language, job.project.target_language
                    )
                    detail = {
                        "text": labeled_text(translation.segments) or translation.raw_text,
                        "speakers": speaker_ids(translation.segments),
                    }
                elif stage_name == PipelineStage.REWRITE:
                    assert translation is not None
                    rewrite = self.providers.rewrite.rewrite(
                        translation,
                        job.project.target_language,
                        accent=job.project.target_accent,
                        progress=self._progress(job, stage, "lines"),
                    )
                    s_key = f"projects/{job.project_id}/script/{job.id}.json"
                    self.storage.put_json(s_key, {"text": rewrite.text, "segments": [s.__dict__ for s in rewrite.segments]})
                    self._save_asset(job.project_id, AssetKind.SCRIPT, s_key, "application/json")
                    detail = {
                        "text": labeled_text(rewrite.segments) or rewrite.text,
                        "speakers": speaker_ids(rewrite.segments),
                        "rewrite": rewrite.meta.get("provider"),
                        "rewritten_lines": rewrite.meta.get("rewritten_lines", 0),
                    }
                elif stage_name == PipelineStage.SYNTHESIZE:
                    assert rewrite is not None
                    out = f"projects/{job.project_id}/voice/{job.id}.wav"
                    synth = self.providers.voice.synthesize(
                        rewrite,
                        voice_ref_key=voice_key or audio_key or None,
                        target_language=job.project.target_language,
                        output_key=out,
                        accent=job.project.target_accent,
                        stop=lambda: self._is_stopped(job.id),
                        progress=self._progress(job, stage, "lines"),
                    )
                    self._save_asset(job.project_id, AssetKind.VOICE, synth.audio_key, "audio/wav")
                    detail = {"audio_key": synth.audio_key, "duration": synth.duration_seconds, **synth.meta}
                elif stage_name == PipelineStage.ALIGN:
                    assert synth is not None and rewrite is not None
                    target_duration = max(s.end for s in rewrite.segments) if rewrite.segments else synth.duration_seconds
                    aligned_key = f"projects/{job.project_id}/voice/{job.id}_aligned.wav"
                    self.providers.media.align_audio(synth.audio_key, target_duration, aligned_key)
                    detail = {"aligned_key": aligned_key, "target_duration": target_duration}
                elif stage_name == PipelineStage.LIPSYNC:
                    out = f"projects/{job.project_id}/lipsync/{job.id}.mp4"
                    lipsync = self.providers.lipsync.sync(video_key, aligned_key or synth.audio_key, out)  # type: ignore[union-attr]
                    detail = {"video_key": lipsync.video_key, **lipsync.meta}
                elif stage_name == PipelineStage.RENDER:
                    assert rewrite is not None
                    out = f"projects/{job.project_id}/render/{job.id}.mp4"
                    video_in = lipsync.video_key if lipsync else video_key
                    audio_in = aligned_key or (synth.audio_key if synth else audio_key)
                    subtitle_text = (
                        segments_to_srt(rewrite.segments) if job.project.include_subtitles else None
                    )
                    result = self.providers.media.render(
                        video_in, audio_in, out, subtitle_text=subtitle_text
                    )
                    self._save_asset(job.project_id, AssetKind.RENDER, result.video_key, "video/mp4")
                    if result.subtitle_key:
                        self._save_asset(job.project_id, AssetKind.SUBTITLES, result.subtitle_key, "application/x-subrip")
                    detail = {"video_key": result.video_key, "subtitle_key": result.subtitle_key, **result.meta}
                elif stage_name == PipelineStage.COMPLETE:
                    detail = {"done": True}

                self._ensure_active(job)
                self._mark_succeeded(job, stage, detail)

            self._ensure_active(job)
            job.status = JobStatus.COMPLETED
            job.current_stage = PipelineStage.COMPLETE
            job.error = None
            self.db.commit()
        except (JobStopped, CloneStopped):
            log.info("job %s stopped", job_id)
            return
        except Exception as exc:  # noqa: BLE001 — surface to job row
            self.db.rollback()
            job = self.db.get(Job, job_id)
            if job and job.status == JobStatus.CANCELLED:
                return
            if job:
                job.status = JobStatus.FAILED
                job.error = str(exc)[:4000]
                for stage in job.stages:
                    if stage.status == StageStatus.RUNNING:
                        stage.status = StageStatus.FAILED
                        stage.detail = {"error": str(exc)[:2000]}
                        stage.finished_at = datetime.now(timezone.utc)
                self.db.commit()
            raise

    def _source_video(self, project_id: uuid.UUID) -> Asset | None:
        rows = self.db.scalars(
            select(Asset)
            .where(Asset.project_id == project_id, Asset.kind == AssetKind.SOURCE_VIDEO)
            .order_by(Asset.created_at.desc())
        )
        for row in rows:
            try:
                if self.storage.exists(row.storage_key) and self.storage.object_size(row.storage_key) >= 32:
                    return row
            except Exception:
                continue
        return None

    def _save_asset(self, project_id: uuid.UUID, kind: str, key: str, mime: str) -> Asset:
        asset = Asset(project_id=project_id, kind=kind, storage_key=key, mime_type=mime, meta={})
        self.db.add(asset)
        self.db.commit()
        return asset

    def _stage(self, job: Job, name: str) -> JobStage:
        for stage in job.stages:
            if stage.name == name:
                return stage
        raise RuntimeError(f"Missing stage {name}")

    def _is_stopped(self, job_id: uuid.UUID) -> bool:
        self.db.expire_all()
        status = self.db.scalar(select(Job.status).where(Job.id == job_id))
        return status == JobStatus.CANCELLED

    def _ensure_active(self, job: Job) -> None:
        if self._is_stopped(job.id):
            raise JobStopped()

    def _progress(self, job: Job, stage: JobStage, unit: str) -> Callable[[int, int], None]:
        """Persist how far a long stage has gotten so the dashboard can estimate the rest."""

        def report(done: int, total: int) -> None:
            if self._is_stopped(job.id):
                raise JobStopped()
            stage.detail = {"done": int(done), "total": int(total), "unit": unit}
            self.db.commit()

        return report

    def _mark_running(self, job: Job, stage: JobStage) -> None:
        self._ensure_active(job)
        stage.status = StageStatus.RUNNING
        stage.attempt += 1
        stage.started_at = datetime.now(timezone.utc)
        stage.finished_at = None
        job.current_stage = stage.name
        self.db.commit()

    def _mark_succeeded(self, job: Job, stage: JobStage, detail: dict) -> None:
        stage.status = StageStatus.SUCCEEDED
        stage.detail = detail
        stage.finished_at = datetime.now(timezone.utc)
        self.db.commit()
