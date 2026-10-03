"""Who is speaking, from the soundtrack rather than from Whisper's cuts.

A real conversation leaves almost no gap between turns, so a vector built from
the last few seconds mixes both people. Pyannote's segmentation model finds the
turns first. A 3D-Speaker embedding then clusters those turns. Both files are
ONNX weights loaded by sherpa-onnx. If they cannot be downloaded, the caller
keeps the per-line Titanet split.
"""

from __future__ import annotations

import logging
import os
import tarfile
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

SEGMENTATION_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
)
# On the mother-and-daughter clip, 0.92 still splits the mother and 0.93 keeps
# her as one voice while the daughter stays another. A larger value merges more.
CLUSTER_THRESHOLD = 0.93
# Short enough to keep a question such as "elle a fait quoi ?".
MIN_DURATION_ON = 0.2
MIN_DURATION_OFF = 0.2
# 2, 4, and 8 threads give the same turns; 8 runs in about 60 % of the time.
NUM_THREADS = max(2, min(8, os.cpu_count() or 2))

_diarizer = None


def diarize_turns(samples: list[float], sample_rate: int) -> list[tuple[float, float, int]] | None:
    """Speech turns as (start, end, speaker). None when the models are missing."""
    diarizer = _load_diarizer()
    if diarizer is None or not samples:
        return None
    audio = _resample(samples, sample_rate, int(diarizer.sample_rate))
    try:
        result = diarizer.process(audio).sort_by_start_time()
    except Exception as exc:
        log.warning("speaker diarization failed: %s", exc)
        return None
    turns = [(float(row.start), float(row.end), int(row.speaker)) for row in result]
    if not turns:
        return None
    return turns


def _load_diarizer():
    global _diarizer
    if _diarizer is not None:
        return _diarizer
    try:
        import sherpa_onnx
    except ImportError:
        log.info("sherpa-onnx is not installed; speaker split uses the per-line embedding")
        return None
    segmentation = _segmentation_path()
    embedding = _embedding_path()
    if segmentation is None or embedding is None:
        return None
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
            num_threads=NUM_THREADS,
            debug=False,
            provider="cpu",
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(embedding),
            num_threads=NUM_THREADS,
            debug=False,
            provider="cpu",
        ),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=CLUSTER_THRESHOLD),
        min_duration_on=MIN_DURATION_ON,
        min_duration_off=MIN_DURATION_OFF,
    )
    if not config.validate():
        log.warning("speaker diarization config is invalid")
        return None
    _diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    return _diarizer


def _cache_dir() -> Path:
    return Path.home() / ".cache" / "dubbing"


def _segmentation_path() -> Path | None:
    override = os.environ.get("SPEAKER_SEGMENTATION_PATH", "").strip()
    dest = Path(override) if override else _cache_dir() / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    archive = _cache_dir() / "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
    log.info("downloading speaker segmentation model to %s", dest)
    try:
        urllib.request.urlretrieve(SEGMENTATION_URL, archive)
        with tarfile.open(archive, "r:bz2") as bundle:
            member = next(
                (
                    item
                    for item in bundle.getmembers()
                    if item.name.endswith("/model.onnx") or item.name == "model.onnx"
                ),
                None,
            )
            if member is None:
                return None
            extracted = bundle.extractfile(member)
            if extracted is None:
                return None
            dest.write_bytes(extracted.read())
    except (OSError, tarfile.TarError) as exc:
        log.warning("speaker segmentation download failed: %s", exc)
        return None
    finally:
        archive.unlink(missing_ok=True)
    if not dest.is_file() or dest.stat().st_size < 1_000_000:
        return None
    return dest


def _embedding_path() -> Path | None:
    override = os.environ.get("SPEAKER_DIARIZATION_EMBEDDING", "").strip()
    dest = (
        Path(override)
        if override
        else _cache_dir() / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
    )
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading speaker diarization embedding to %s", dest)
    try:
        urllib.request.urlretrieve(EMBEDDING_URL, dest)
    except OSError as exc:
        log.warning("speaker diarization embedding download failed: %s", exc)
        return None
    if not dest.is_file() or dest.stat().st_size < 1_000_000:
        return None
    return dest


def _resample(samples: list[float], source_rate: int, target_rate: int) -> list[float]:
    if source_rate == target_rate or source_rate <= 0 or not samples:
        return samples
    count = max(1, int(len(samples) * target_rate / source_rate))
    last = len(samples) - 1
    resampled: list[float] = []
    for index in range(count):
        position = index * source_rate / target_rate
        left = min(int(position), last)
        right = min(left + 1, last)
        mix = position - left
        resampled.append(samples[left] * (1 - mix) + samples[right] * mix)
    return resampled
