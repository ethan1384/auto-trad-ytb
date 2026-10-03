"""Speaker embeddings with Titanet-small.

Pitch and spectral shape collapse two people recorded on the same microphone.
A speaker-recognition model scores who is talking, not the words or the room.
The ONNX file is downloaded into the cache on first use. If it is missing,
diarization falls back to the spectral clustering.
"""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/nemo_en_titanet_small.onnx"
)
# Same person on this clip scores about 0.63–0.80. A different voice stays under 0.55.
EMBED_MATCH = 0.55

_extractor = None


def embed_clips(clips: list[list[float]], sample_rate: int) -> list[list[float] | None] | None:
    """One unit vector per clip. None when the model cannot be loaded."""
    extractor = _load_extractor()
    if extractor is None:
        return None
    vectors: list[list[float] | None] = []
    for clip in clips:
        vectors.append(_embed_one(extractor, clip, sample_rate))
    return vectors


def _load_extractor():
    global _extractor
    if _extractor is not None:
        return _extractor
    try:
        import sherpa_onnx
    except ImportError:
        log.info("sherpa-onnx is not installed; speaker split uses pitch and timbre")
        return None
    model = _model_path()
    if model is None:
        return None
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(model),
        num_threads=2,
        debug=False,
        provider="cpu",
    )
    _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
    return _extractor


def _model_path() -> Path | None:
    override = os.environ.get("SPEAKER_MODEL_PATH", "").strip()
    dest = Path(override) if override else Path.home() / ".cache" / "dubbing" / "nemo_en_titanet_small.onnx"
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading speaker model to %s", dest)
    try:
        urllib.request.urlretrieve(MODEL_URL, dest)
    except OSError as exc:
        log.warning("speaker model download failed: %s", exc)
        return None
    if not dest.is_file() or dest.stat().st_size < 1_000_000:
        return None
    return dest


def _embed_one(extractor, clip: list[float], sample_rate: int) -> list[float] | None:
    if len(clip) < int(0.45 * sample_rate):
        return None
    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate, clip)
    stream.input_finished()
    if not extractor.is_ready(stream):
        return None
    values = list(extractor.compute(stream))
    norm = sum(value * value for value in values) ** 0.5
    if norm < 1e-6:
        return None
    return [value / norm for value in values]
