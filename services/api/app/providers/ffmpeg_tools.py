"""FFmpeg helpers used by the local pipeline. No ML imports."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.providers.base import TranscriptSegment


def srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list[TranscriptSegment]) -> str:
    blocks: list[str] = []
    index = 1
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        start = max(segment.start, 0.0)
        end = segment.end if segment.end > start else start + 0.4
        blocks.append(f"{index}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text}\n")
        index += 1
    return "\n".join(blocks)


def atempo_chain(speed: float) -> str:
    """ffmpeg atempo accepts 0.5–2.0, so larger changes are chained."""
    if speed <= 0:
        raise ValueError("speed must be positive")
    parts: list[str] = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.4f}")
    return ",".join(parts)


def run_cmd(args: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(args, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown error").strip()
        raise RuntimeError(f"{Path(args[0]).name} failed: {detail[-1800:]}")


def probe_duration(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {(proc.stderr or '').strip()[-800:]}")
    return float(proc.stdout.strip())


# OmniVoice's tokenizer is 24 kHz. A 16 kHz dub throws away the brightness
# that makes the clone recognizable.
DUB_SAMPLE_RATE = 24000


def write_silence(dest: Path, duration: float, sample_rate: int = DUB_SAMPLE_RATE) -> None:
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl=mono",
            "-t",
            f"{max(duration, 0.01):.3f}",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )


def to_wav(src: Path, dest: Path, sample_rate: int = DUB_SAMPLE_RATE) -> None:
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )


# Slowing a line further than this turns the words into a smear. Pad silence instead.
MIN_FIT_SPEED = 0.9


def fit_wav(
    src: Path,
    dest: Path,
    slot_seconds: float,
    sample_rate: int = DUB_SAMPLE_RATE,
    duration: float | None = None,
) -> None:
    """Fit src into the slot. Pass duration when the caller already probed src."""
    slot = max(slot_seconds, 0.2)
    duration = max(probe_duration(src) if duration is None else duration, 0.05)
    speed = duration / slot
    if speed < MIN_FIT_SPEED:
        audio_filter = f"apad=whole_dur={slot:.3f},atrim=0:{slot:.3f}"
    else:
        audio_filter = f"{atempo_chain(speed)},apad=whole_dur={slot:.3f},atrim=0:{slot:.3f}"
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-af",
            audio_filter,
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )


def concat_wavs(paths: list[Path], dest: Path) -> None:
    if not paths:
        raise RuntimeError("No audio pieces to concatenate")
    if len(paths) == 1:
        to_wav(paths[0], dest)
        return
    listing = dest.with_suffix(".txt")
    listing.write_text("\n".join(f"file '{path}'" for path in paths), encoding="utf-8")
    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(dest)])
