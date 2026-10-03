from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.accents import resolve_accent


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_language: str = Field(default="en", min_length=2, max_length=16)
    target_language: str = Field(default="fr", min_length=2, max_length=16)
    target_accent: str | None = None
    voice_consent: bool = False
    include_subtitles: bool = True

    @model_validator(mode="after")
    def _apply_accent(self) -> "ProjectCreate":
        self.target_accent = resolve_accent(self.target_language, self.target_accent)
        return self


class ProjectUpdate(BaseModel):
    include_subtitles: bool | None = None
    target_accent: str | None = None

    @field_validator("target_accent")
    @classmethod
    def _accent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return resolve_accent("fr", value)


class ProjectRead(BaseModel):
    id: uuid.UUID
    name: str
    source_language: str
    target_language: str
    target_accent: str | None = None
    voice_consent: bool
    include_subtitles: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="video/mp4")


class UploadUrlResponse(BaseModel):
    asset_id: uuid.UUID
    storage_key: str
    upload_url: str
    headers: dict[str, str] = Field(default_factory=dict)


class AssetConfirmRequest(BaseModel):
    asset_id: uuid.UUID


class AssetRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    storage_key: str
    mime_type: str | None
    meta: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class JobCreate(BaseModel):
    source_asset_id: uuid.UUID | None = None


class JobStageRead(BaseModel):
    id: uuid.UUID
    name: str
    position: int
    status: str
    attempt: int
    detail: dict
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class JobRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    current_stage: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    stages: list[JobStageRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ArtifactRead(BaseModel):
    id: uuid.UUID
    kind: str
    storage_key: str
    download_url: str | None = None
    mime_type: str | None = None
