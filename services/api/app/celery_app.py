import logging

from celery import Celery

from app.config import get_settings

log = logging.getLogger(__name__)

settings = get_settings()

celery = Celery("dubbing", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    imports=("app.celery_app",),
)


def terminate_pipeline_task(task_id: str) -> None:
    """Kill the worker process running this task.

    OmniVoice holds the CPU inside one generate() call. Revoke alone waits
    until that call returns. SIGKILL cuts it.
    """
    celery.control.revoke(task_id, terminate=True, signal="SIGKILL")


def find_pipeline_task_id(job_id: str) -> str | None:
    """Find a task started before its id was stored on the job row."""
    try:
        active = celery.control.inspect(timeout=1.0).active() or {}
    except Exception as exc:  # noqa: BLE001 — inspect is best-effort
        log.warning("could not list active tasks: %s", exc)
        return None
    needle = str(job_id)
    for tasks in active.values():
        for task in tasks or []:
            if task.get("name") != "app.tasks.run_pipeline_job":
                continue
            if needle in str(task.get("args")):
                task_id = task.get("id")
                if isinstance(task_id, str) and task_id:
                    return task_id
    return None


@celery.task(name="app.tasks.run_pipeline_job")
def run_pipeline_job(job_id: str) -> str:
    import uuid

    from app.db import SessionLocal
    from app.pipeline import PipelineRunner

    db = SessionLocal()
    try:
        PipelineRunner(db).run(uuid.UUID(job_id))
        return job_id
    finally:
        db.close()
