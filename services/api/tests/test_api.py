from __future__ import annotations

from dubbing_shared import PIPELINE_ORDER, JobStatus
from fastapi.testclient import TestClient
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import Asset, Job, JobStage, Project
from app.pipeline import PipelineRunner
from app.providers.ffmpeg_tools import atempo_chain, segments_to_srt, srt_timestamp
from app.providers.mock import MockTranscriptionProvider
from app.providers.base import TranscriptSegment


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def ensure_bucket(self) -> None:
        return None

    def build_key(self, project_id, kind: str, filename: str) -> str:
        return f"projects/{project_id}/{kind}/{filename}"

    def presigned_put(self, key: str, content_type: str, expires: int = 3600) -> str:
        return f"https://example.test/upload/{key}"

    def put_bytes(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
        self.objects[key] = body

    def put_json(self, key: str, payload: dict) -> None:
        import json

        self.put_bytes(key, json.dumps(payload).encode(), "application/json")

    def exists(self, key: str) -> bool:
        return key in self.objects

    def object_size(self, key: str) -> int:
        return len(self.objects[key])


def test_health() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    app.dependency_overrides.clear()


def test_mock_transcription() -> None:
    result = MockTranscriptionProvider().transcribe("audio.wav", "en")
    assert result.raw_text
    assert result.segments


def test_srt_and_atempo() -> None:
    assert srt_timestamp(65.5) == "00:01:05,500"
    srt = segments_to_srt([TranscriptSegment(0.0, 1.2, "Hello")])
    assert "Hello" in srt
    assert atempo_chain(1.0) == "atempo=1.0000"
    assert atempo_chain(4.0).startswith("atempo=2.0")


def test_pipeline_runner_mock(monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "mock")
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    storage = MemoryStorage()

    project = Project(name="Demo", source_language="en", target_language="fr", voice_consent=True)
    db.add(project)
    db.flush()
    source_key = f"projects/{project.id}/source_video/demo.mp4"
    storage.objects[source_key] = b"x" * 64
    db.add(
        Asset(
            project_id=project.id,
            kind="source_video",
            storage_key=source_key,
            mime_type="video/mp4",
            meta={"confirmed": True},
        )
    )
    job = Job(project_id=project.id, status=JobStatus.PENDING, current_stage=PIPELINE_ORDER[0])
    db.add(job)
    db.flush()
    for idx, stage in enumerate(PIPELINE_ORDER):
        db.add(JobStage(job_id=job.id, name=stage, position=idx, status="pending"))
    db.commit()

    PipelineRunner(db, storage=storage).run(job.id)  # type: ignore[arg-type]
    db.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert any(k.endswith(".mp4") for k in storage.objects)
    assert any(k.endswith(".srt") for k in storage.objects)


def test_pipeline_skips_subtitles_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "mock")
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    storage = MemoryStorage()

    project = Project(
        name="No subs",
        source_language="en",
        target_language="fr",
        voice_consent=True,
        include_subtitles=False,
    )
    db.add(project)
    db.flush()
    source_key = f"projects/{project.id}/source_video/demo.mp4"
    storage.objects[source_key] = b"x" * 64
    db.add(
        Asset(
            project_id=project.id,
            kind="source_video",
            storage_key=source_key,
            mime_type="video/mp4",
            meta={"confirmed": True},
        )
    )
    job = Job(project_id=project.id, status=JobStatus.PENDING, current_stage=PIPELINE_ORDER[0])
    db.add(job)
    db.flush()
    for idx, stage in enumerate(PIPELINE_ORDER):
        db.add(JobStage(job_id=job.id, name=stage, position=idx, status="pending"))
    db.commit()

    PipelineRunner(db, storage=storage).run(job.id)  # type: ignore[arg-type]
    db.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert not any(k.endswith(".srt") for k in storage.objects)


def test_cancel_running_job(monkeypatch) -> None:
    killed: list[str] = []
    monkeypatch.setattr(
        "app.celery_app.terminate_pipeline_task",
        lambda task_id: killed.append(task_id),
    )
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    project = Project(name="Stop", source_language="en", target_language="fr", voice_consent=True)
    db.add(project)
    db.flush()
    job = Job(
        project_id=project.id,
        status=JobStatus.RUNNING,
        current_stage="synthesize",
        celery_task_id="task-1",
    )
    db.add(job)
    db.flush()
    db.add(JobStage(job_id=job.id, name="synthesize", position=5, status="running"))
    db.commit()

    from app.services.projects import ProjectService

    stopped = ProjectService(db, storage=MemoryStorage()).cancel_job(job.id)  # type: ignore[arg-type]
    assert stopped.status == JobStatus.CANCELLED
    assert stopped.error == "Stopped"
    assert killed == ["task-1"]
    assert stopped.stages[0].status == "failed"
    assert stopped.stages[0].detail["error"] == "Stopped"
