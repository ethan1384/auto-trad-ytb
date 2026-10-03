from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    ArtifactRead,
    AssetConfirmRequest,
    AssetRead,
    JobCreate,
    JobRead,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services.projects import ProjectService
from app.storage import StorageClient

router = APIRouter()


def _service(db: Session = Depends(get_db)) -> ProjectService:
    return ProjectService(db)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(service: ProjectService = Depends(_service)) -> list[ProjectRead]:
    return [ProjectRead.model_validate(p) for p in service.list_projects()]


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, service: ProjectService = Depends(_service)) -> ProjectRead:
    return ProjectRead.model_validate(service.create_project(payload))


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, service: ProjectService = Depends(_service)) -> ProjectRead:
    return ProjectRead.model_validate(service.get_project(project_id))


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    service: ProjectService = Depends(_service),
) -> ProjectRead:
    return ProjectRead.model_validate(service.update_project(project_id, payload))


@router.post("/projects/{project_id}/assets/upload-url", response_model=UploadUrlResponse)
def create_upload_url(
    project_id: uuid.UUID,
    payload: UploadUrlRequest,
    service: ProjectService = Depends(_service),
) -> UploadUrlResponse:
    asset, url = service.create_upload(project_id, payload)
    return UploadUrlResponse(
        asset_id=asset.id,
        storage_key=asset.storage_key,
        upload_url=url,
        headers={"Content-Type": payload.content_type},
    )


@router.post("/projects/{project_id}/assets", response_model=AssetRead, status_code=201)
async def upload_asset(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    service: ProjectService = Depends(_service),
) -> AssetRead:
    if not file.filename:
        raise HTTPException(status_code=400, detail="A video file is required")
    content_type = file.content_type or "video/mp4"
    if content_type in {"application/octet-stream", "binary/octet-stream"}:
        content_type = "video/mp4"
    asset = service.save_source_upload(project_id, file.filename, content_type, file.file)
    return AssetRead.model_validate(asset)


@router.post("/projects/{project_id}/assets/confirm", response_model=AssetRead)
def confirm_asset(
    project_id: uuid.UUID,
    payload: AssetConfirmRequest,
    service: ProjectService = Depends(_service),
) -> AssetRead:
    return AssetRead.model_validate(service.confirm_asset(project_id, payload.asset_id))


@router.post("/projects/{project_id}/jobs", response_model=JobRead, status_code=201)
def create_job(
    project_id: uuid.UUID,
    payload: JobCreate,
    service: ProjectService = Depends(_service),
    db: Session = Depends(get_db),
) -> JobRead:
    from dubbing_shared import JobStatus

    from app.celery_app import run_pipeline_job

    job = service.create_job(project_id, payload)
    job.status = JobStatus.QUEUED
    db.commit()
    result = run_pipeline_job.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()
    db.refresh(job)
    return JobRead.model_validate(service.get_job(job.id))


@router.get("/projects/{project_id}/jobs/latest", response_model=JobRead | None)
def latest_job(project_id: uuid.UUID, service: ProjectService = Depends(_service)) -> JobRead | None:
    job = service.latest_job(project_id)
    if job is None:
        return None
    return JobRead.model_validate(job)


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: uuid.UUID, service: ProjectService = Depends(_service)) -> JobRead:
    return JobRead.model_validate(service.get_job(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job(job_id: uuid.UUID, service: ProjectService = Depends(_service)) -> JobRead:
    return JobRead.model_validate(service.cancel_job(job_id))


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactRead])
def list_artifacts(
    project_id: uuid.UUID,
    service: ProjectService = Depends(_service),
) -> list[ArtifactRead]:
    storage = StorageClient()
    artifacts: list[ArtifactRead] = []
    for asset in service.list_project_artifacts(project_id):
        try:
            url = storage.presigned_get(asset.storage_key)
        except Exception:
            url = None
        artifacts.append(
            ArtifactRead(
                id=asset.id,
                kind=asset.kind,
                storage_key=asset.storage_key,
                download_url=url,
                mime_type=asset.mime_type,
            )
        )
    return artifacts
