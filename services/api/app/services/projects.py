from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import BinaryIO

from dubbing_shared import PIPELINE_ORDER, AssetKind, JobStatus, StageStatus
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.accents import resolve_accent
from app.models import Asset, Job, JobStage, Project
from app.schemas import JobCreate, ProjectCreate, ProjectUpdate, UploadUrlRequest
from app.storage import StorageClient

log = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, db: Session, storage: StorageClient | None = None) -> None:
        self.db = db
        self.storage = storage or StorageClient()

    def list_projects(self) -> list[Project]:
        return list(self.db.scalars(select(Project).order_by(Project.created_at.desc())))

    def get_project(self, project_id: uuid.UUID) -> Project:
        project = self.db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return project

    def create_project(self, payload: ProjectCreate) -> Project:
        project = Project(
            name=payload.name,
            source_language=payload.source_language,
            target_language=payload.target_language,
            target_accent=payload.target_accent,
            voice_consent=payload.voice_consent,
            include_subtitles=payload.include_subtitles,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def update_project(self, project_id: uuid.UUID, payload: ProjectUpdate) -> Project:
        project = self.get_project(project_id)
        if "include_subtitles" in payload.model_fields_set and payload.include_subtitles is not None:
            project.include_subtitles = payload.include_subtitles
        if "target_accent" in payload.model_fields_set:
            project.target_accent = resolve_accent(project.target_language, payload.target_accent)
        self.db.commit()
        self.db.refresh(project)
        return project

    def create_upload(self, project_id: uuid.UUID, payload: UploadUrlRequest) -> tuple[Asset, str]:
        project = self.get_project(project_id)
        try:
            self.storage.ensure_bucket()
        except Exception:
            # Bucket may be created by minio-init; ignore flaky local races.
            pass
        key = self.storage.build_key(project.id, AssetKind.SOURCE_VIDEO, payload.filename)
        asset = Asset(
            project_id=project.id,
            kind=AssetKind.SOURCE_VIDEO,
            storage_key=key,
            mime_type=payload.content_type,
            meta={"filename": payload.filename, "confirmed": False},
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        url = self.storage.presigned_put(key, payload.content_type)
        return asset, url

    def save_source_upload(
        self, project_id: uuid.UUID, filename: str, content_type: str, body: BinaryIO
    ) -> Asset:
        project = self.get_project(project_id)
        self.storage.ensure_bucket()
        key = self.storage.build_key(project.id, AssetKind.SOURCE_VIDEO, filename)
        if hasattr(body, "seek"):
            body.seek(0)
        self.storage.upload_fileobj(key, body, content_type)
        size = self.storage.object_size(key)
        if size < 32:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
        asset = Asset(
            project_id=project.id,
            kind=AssetKind.SOURCE_VIDEO,
            storage_key=key,
            mime_type=content_type,
            meta={"filename": filename, "confirmed": True, "size": size},
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def confirm_asset(self, project_id: uuid.UUID, asset_id: uuid.UUID) -> Asset:
        self.get_project(project_id)
        asset = self.db.get(Asset, asset_id)
        if not asset or asset.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        meta = dict(asset.meta or {})
        meta["confirmed"] = True
        asset.meta = meta
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def create_job(self, project_id: uuid.UUID, payload: JobCreate) -> Job:
        project = self.get_project(project_id)
        if not project.voice_consent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Voice cloning consent is required before starting a job",
            )

        source: Asset | None = None
        if payload.source_asset_id:
            source = self.db.get(Asset, payload.source_asset_id)
            if not source or source.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source asset not found")
            if not self.storage.exists(source.storage_key) or self.storage.object_size(source.storage_key) < 32:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Source video is missing or incomplete. Upload the file again.",
                )
        else:
            source = self._usable_source(project_id)
            if not source:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Upload a source video before starting a job",
                )

        job = Job(project_id=project.id, status=JobStatus.PENDING, current_stage=PIPELINE_ORDER[0])
        self.db.add(job)
        self.db.flush()
        for idx, stage in enumerate(PIPELINE_ORDER):
            self.db.add(
                JobStage(
                    job_id=job.id,
                    name=stage,
                    position=idx,
                    status=StageStatus.PENDING,
                )
            )
        self.db.commit()
        job = self.db.scalars(
            select(Job).where(Job.id == job.id).options(selectinload(Job.stages))
        ).one()
        return job

    def latest_job(self, project_id: uuid.UUID) -> Job | None:
        self.get_project(project_id)
        return self.db.scalars(
            select(Job)
            .where(Job.project_id == project_id)
            .options(selectinload(Job.stages))
            .order_by(Job.created_at.desc())
        ).first()

    def _usable_source(self, project_id: uuid.UUID) -> Asset | None:
        candidates = self.db.scalars(
            select(Asset)
            .where(Asset.project_id == project_id, Asset.kind == AssetKind.SOURCE_VIDEO)
            .order_by(Asset.created_at.desc())
        )
        for candidate in candidates:
            try:
                if self.storage.exists(candidate.storage_key) and self.storage.object_size(candidate.storage_key) >= 32:
                    return candidate
            except Exception:
                continue
        return None

    def cancel_job(self, job_id: uuid.UUID) -> Job:
        job = self.get_job(job_id)
        if job.status == JobStatus.CANCELLED:
            return job
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This translation is already finished",
            )
        now = datetime.now(timezone.utc)
        job.status = JobStatus.CANCELLED
        job.error = "Stopped"
        for stage in job.stages:
            if stage.status == StageStatus.RUNNING:
                stage.status = StageStatus.FAILED
                stage.detail = {"error": "Stopped"}
                stage.finished_at = now
        self.db.commit()
        self.db.refresh(job)
        self._kill_worker(job)
        return job

    def _kill_worker(self, job: Job) -> None:
        from app.celery_app import find_pipeline_task_id, terminate_pipeline_task

        task_id = job.celery_task_id or find_pipeline_task_id(str(job.id))
        if not task_id:
            log.warning("job %s has no celery task to stop", job.id)
            return
        if not job.celery_task_id:
            job.celery_task_id = task_id
            self.db.commit()
        terminate_pipeline_task(task_id)

    def get_job(self, job_id: uuid.UUID) -> Job:
        job = self.db.scalars(
            select(Job).where(Job.id == job_id).options(selectinload(Job.stages))
        ).first()
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return job

    def list_project_artifacts(self, project_id: uuid.UUID) -> list[Asset]:
        self.get_project(project_id)
        return list(
            self.db.scalars(
                select(Asset).where(Asset.project_id == project_id).order_by(Asset.created_at.desc())
            )
        )
