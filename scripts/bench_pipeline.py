"""Profile dubbing jobs end to end with the local providers.

Runs the real PipelineRunner on a source clip with an in-memory SQLite DB and
a directory standing in for S3. Several jobs run back to back in one process,
as in the Celery worker, so job 1 pays the cold model loads and later jobs show
the recurring cost. Each job writes per-stage wall time, subprocess / HTTP /
SQL counters, a cProfile dump, and fingerprints of every output so a later run
can be compared against this one.

    services/api/.venv/bin/python scripts/bench_pipeline.py CLIP.mp4 --out .bench/before
    services/api/.venv/bin/python scripts/bench_pipeline.py --compare .bench/before .bench/after --job 2
"""

from __future__ import annotations

import argparse
import array
import cProfile
import hashlib
import json
import os
import pstats
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))


class Counters:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.calls: dict[str, int] = defaultdict(int)
        self.seconds: dict[str, float] = defaultdict(float)
        self.stage = "setup"
        self.by_stage: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))

    def add(self, name: str, seconds: float) -> None:
        with self.lock:
            self.calls[name] += 1
            self.seconds[name] += seconds
            row = self.by_stage[self.stage][name]
            row[0] += 1
            row[1] += seconds


COUNTERS = Counters()


@contextmanager
def timed(name: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        COUNTERS.add(name, time.perf_counter() - start)


def wrap(owner, attr: str, name: str) -> None:
    original = getattr(owner, attr)

    def wrapper(*args, **kwargs):
        with timed(name):
            return original(*args, **kwargs)

    setattr(owner, attr, wrapper)


class FileStorage:
    """Same surface as StorageClient, backed by a directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def ensure_bucket(self) -> None:
        return None

    def exists(self, key: str) -> bool:
        with timed("storage.head"):
            return self._path(key).is_file()

    def object_size(self, key: str) -> int:
        with timed("storage.head"):
            return self._path(key).stat().st_size

    def upload_path(self, key: str, path: Path, content_type: str) -> None:
        with timed("storage.upload"):
            dest = self._path(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)

    def download(self, key: str, dest: Path) -> None:
        with timed("storage.download"):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self._path(key), dest)

    def copy_object(self, source_key: str, dest_key: str, content_type: str) -> None:
        with timed("storage.copy"):
            dest = self._path(dest_key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self._path(source_key), dest)

    def put_bytes(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
        with timed("storage.put"):
            dest = self._path(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)

    def put_json(self, key: str, payload: dict) -> None:
        self.put_bytes(key, json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default).encode())


def _json_default(value):
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def instrument() -> None:
    real_run = subprocess.run

    def run(args, *rest, **kwargs):
        program = Path(str(args[0])).name if isinstance(args, (list, tuple)) and args else "proc"
        with timed(f"proc.{program}"):
            return real_run(args, *rest, **kwargs)

    subprocess.run = run  # type: ignore[assignment]

    import httpx

    wrap(httpx, "post", "http.post")
    wrap(httpx, "get", "http.get")

    from app.providers import local, speaker_diarize, speakers, voice_clone

    wrap(local, "_load_whisper" if hasattr(local, "_load_whisper") else "_whisper_model", "load.whisper")
    wrap(voice_clone, "_load_model", "load.omnivoice")
    wrap(voice_clone, "_voice_prompt", "omnivoice.voice_prompt")
    wrap(voice_clone, "_write_wav", "omnivoice.write_wav")
    wrap(speakers, "read_pcm16", "speakers.read_pcm16")
    wrap(speakers, "write_pcm16", "speakers.write_pcm16")
    wrap(speakers, "_compress_silence", "speakers.compress_silence")
    wrap(speaker_diarize, "diarize_turns", "diarize.turns")
    wrap(speaker_diarize, "_load_diarizer", "load.diarizer")
    # local.py imported these by name, so patch the names it calls.
    wrap(local, "separate_accompaniment", "render.demucs")
    wrap(local, "mix_dub_over_background", "render.mix")
    wrap(local, "extract_soundtrack", "render.extract_soundtrack")
    wrap(local, "_encode", "render.encode")
    wrap(local, "write_speaker_refs", "synth.write_refs")
    wrap(local, "assign_speakers", "transcribe.assign_speakers")
    wrap(local, "_argos_translate", "translate.argos_setup")
    wrap(local.LocalVoiceSynthesisProvider, "_lay_timeline", "synth.lay_timeline")

    original_write = voice_clone.write_cloned_lines

    def write_cloned_lines(*args, **kwargs):
        with timed("omnivoice.write_cloned_lines"):
            return original_write(*args, **kwargs)

    voice_clone.write_cloned_lines = write_cloned_lines

    original_batch = voice_clone.render_cloned_batch

    def render_cloned_batch(lines, *args, **kwargs):
        with timed(f"omnivoice.batch[{len(lines)}]"):
            return original_batch(lines, *args, **kwargs)

    voice_clone.render_cloned_batch = render_cloned_batch


def sqlite_session():
    from sqlalchemy import JSON, create_engine, event
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    Base.metadata.create_all(bind=engine)

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("t0", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        start = conn.info["t0"].pop()
        verb = statement.strip().split(None, 1)[0].upper()
        COUNTERS.add(f"sql.{verb}", time.perf_counter() - start)

    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def pcm_digest(path: Path) -> dict:
    """Decoded audio fingerprint. Container metadata does not affect it."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "s16le", "-ac", "1", "-"],
        capture_output=True,
    )
    raw = proc.stdout
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    return {"pcm_sha": hashlib.sha256(raw).hexdigest()[:16], "samples": len(samples)}


def seed_everything(seed: int | None) -> None:
    if seed is None:
        return
    import random

    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def peak_rss_mb() -> float:
    import resource

    # macOS reports bytes, Linux kilobytes.
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1 << 20) if sys.platform == "darwin" else raw / 1024


def run(args: argparse.Namespace) -> None:
    os.environ["PROVIDER_MODE"] = "local"
    if args.no_rewrite:
        os.environ["OLLAMA_BASE_URL"] = ""
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    instrument()

    from dubbing_shared import PIPELINE_ORDER, AssetKind, JobStatus, StageStatus

    from app.models import Asset, Job, JobStage, Project
    from app.pipeline import PipelineRunner

    storage = FileStorage(out / "s3")
    db = sqlite_session()
    project = Project(
        name="bench",
        source_language=args.source,
        target_language=args.target,
        target_accent=args.accent,
        voice_consent=True,
        include_subtitles=not args.no_subtitles,
    )
    db.add(project)
    db.flush()
    key = f"projects/{project.id}/source_video/clip.mp4"
    (out / "s3" / key).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.clip, out / "s3" / key)
    db.add(Asset(project_id=project.id, kind=AssetKind.SOURCE_VIDEO, storage_key=key, mime_type="video/mp4", meta={}))
    db.commit()

    for number in range(1, args.repeat + 1):
        job = Job(project_id=project.id, status=JobStatus.QUEUED, current_stage=PIPELINE_ORDER[0])
        db.add(job)
        db.flush()
        for index, name in enumerate(PIPELINE_ORDER):
            db.add(JobStage(job_id=job.id, name=name, position=index, status=StageStatus.PENDING))
        db.commit()
        job_id = job.id

        runner = PipelineRunner(db, storage=storage)  # type: ignore[arg-type]
        original_mark_running = runner._mark_running

        def mark_running(job_row, stage, _original=original_mark_running):
            COUNTERS.stage = stage.name
            return _original(job_row, stage)

        runner._mark_running = mark_running  # type: ignore[method-assign]

        COUNTERS.reset()
        seed_everything(args.seed)
        profiler = cProfile.Profile()
        started = time.perf_counter()
        profiler.enable()
        error = None
        try:
            runner.run(job_id)
        except Exception as exc:  # noqa: BLE001
            error = repr(exc)
        profiler.disable()
        total = time.perf_counter() - started
        profiler.dump_stats(out / f"profile-{number}.prof")

        db.expire_all()
        job = db.get(Job, job_id)
        stages = []
        for stage in sorted(job.stages, key=lambda row: row.position):
            seconds = None
            if stage.started_at and stage.finished_at:
                seconds = round((stage.finished_at - stage.started_at).total_seconds(), 3)
            stages.append({"name": stage.name, "status": stage.status, "seconds": seconds, "detail": stage.detail})

        fingerprints = {}
        s3 = out / "s3"
        for path in sorted(s3.rglob("*")):
            if not path.is_file() or str(job_id) not in path.name:
                continue
            rel = str(path.relative_to(s3)).replace(str(project.id), "P").replace(str(job_id), "J")
            entry: dict = {"sha": sha(path), "bytes": path.stat().st_size}
            if path.suffix in {".wav", ".mp4"}:
                entry.update(pcm_digest(path))
            if path.suffix == ".json":
                entry["json"] = json.loads(path.read_text())
            if path.suffix == ".srt":
                entry["text"] = path.read_text()
            fingerprints[rel] = entry

        report = {
            "clip": str(args.clip),
            "job": number,
            "status": job.status,
            "error": error or job.error,
            "total_seconds": round(total, 3),
            "peak_rss_mb": round(peak_rss_mb(), 1),
            "stages": stages,
            "counters": {
                name: [COUNTERS.calls[name], round(COUNTERS.seconds[name], 3)] for name in sorted(COUNTERS.calls)
            },
            "by_stage": {
                stage: {name: [row[0], round(row[1], 3)] for name, row in sorted(rows.items())}
                for stage, rows in COUNTERS.by_stage.items()
            },
            "outputs": fingerprints,
        }
        (out / f"report-{number}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=_json_default)
        )
        print(f"\n===== job {number}/{args.repeat}")
        print_report(report)
        stats = pstats.Stats(str(out / f"profile-{number}.prof"))
        with (out / f"profile-{number}.txt").open("w") as handle:
            stats.stream = handle
            stats.sort_stats("cumulative").print_stats(60)
            stats.sort_stats("tottime").print_stats(40)


def print_report(report: dict) -> None:
    print(f"status={report['status']} total={report['total_seconds']}s peak_rss={report['peak_rss_mb']} MB")
    if report["error"]:
        print("error:", report["error"])
    print("stage                seconds")
    for stage in report["stages"]:
        print(f"  {stage['name']:<18} {stage['seconds'] if stage['seconds'] is not None else '-'}")
    print("counter                               calls   seconds")
    for name, (calls, seconds) in report["counters"].items():
        print(f"  {name:<36} {calls:>5}   {seconds:>8.3f}")


def compare(before_dir: str, after_dir: str, job: int) -> None:
    before = json.loads((Path(before_dir) / f"report-{job}.json").read_text())
    after = json.loads((Path(after_dir) / f"report-{job}.json").read_text())
    print(f"job {job}: total {before['total_seconds']}s -> {after['total_seconds']}s")
    print(f"peak rss: {before['peak_rss_mb']} -> {after['peak_rss_mb']} MB")
    print("stage                before    after")
    after_stages = {row["name"]: row for row in after["stages"]}
    for row in before["stages"]:
        other = after_stages.get(row["name"], {})
        print(f"  {row['name']:<18} {row['seconds']!s:>8} {other.get('seconds')!s:>8}")
    print("outputs")
    for key in sorted(set(before["outputs"]) | set(after["outputs"])):
        left = before["outputs"].get(key)
        right = after["outputs"].get(key)
        if left is None or right is None:
            print(f"  {key}: only in {'after' if left is None else 'before'}")
            continue
        parts = [f"bytes={'same' if left['sha'] == right['sha'] else 'DIFF'}"]
        if "pcm_sha" in left:
            parts.append(f"pcm={'same' if left['pcm_sha'] == right.get('pcm_sha') else 'DIFF'}")
        if "json" in left:
            parts.append(f"json={'same' if left['json'] == right.get('json') else 'DIFF'}")
        print(f"  {key}: {' '.join(parts)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("clip", nargs="?")
    parser.add_argument("--out", default=".bench/run")
    parser.add_argument("--source", default="en")
    parser.add_argument("--target", default="fr")
    parser.add_argument("--accent", default="fr-CA")
    parser.add_argument("--no-subtitles", action="store_true")
    parser.add_argument("--no-rewrite", action="store_true", help="Leave Ollama out (Argos lines are kept)")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--repeat", type=int, default=2, help="Jobs run back to back in one process")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    parser.add_argument("--job", type=int, default=2, help="Which job report to compare")
    args = parser.parse_args()
    if args.compare:
        compare(*args.compare, args.job)
        return
    if not args.clip:
        parser.error("clip is required")
    run(args)


if __name__ == "__main__":
    main()
