"""Zero-shot voice cloning with OmniVoice.

One cloned prompt is built per speaker from a short sample of their original
speech. Lines of that voice with similar lengths are decoded together.
"""

from __future__ import annotations

import array
import logging
import sys
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_model = None
# OmniVoice's own default. Fewer steps on CPU made the French unintelligible.
_num_step = 32
# Their default of 2 already follows the reference. A higher scale keeps the
# decode on that voice instead of drifting toward a generic one.
_guidance_scale = 3.0
# One generate() call. Guidance already doubles the forward batch, and every
# line is padded to the longest, so a small lot of similar lengths is the
# speedup that still fits in CPU memory.
_BATCH_SIZE = 4
_BATCH_DURATION_RATIO = 1.5
_prompts: dict[tuple[str, str], object] = {}


@dataclass(frozen=True)
class CloneLine:
    text: str
    ref_audio: Path
    ref_text: str
    dest: Path
    duration: float | None


def clear_prompts() -> None:
    _prompts.clear()


def speaking_duration(text: str, slot: float | None) -> float | None:
    """Follow the original line when it fits, and leave the pace alone when it does not.

    A slot much shorter than the words made OmniVoice invent a noise in front
    of the line. A slot much longer made it drone. In between, matching the
    original window keeps the person's rhythm.
    """
    if slot is None or slot < 0.4:
        return None
    words = max(1, len(text.split()))
    natural = max(0.5, words / 2.3)
    if slot < natural * 0.85:
        return None
    if slot > natural * 1.8:
        return round(natural * 1.15, 3)
    return round(float(slot), 3)


def plan_clone_batches(lengths: list[float]) -> list[list[int]]:
    """Group line indexes into lots of at most four similar lengths.

    OmniVoice pads a lot to its longest line. A much longer line would spend
    the extra steps on that padding, so it waits for the next lot.
    """
    if not lengths:
        return []
    order = sorted(range(len(lengths)), key=lambda index: (lengths[index], index))
    batches: list[list[int]] = []
    current: list[int] = []
    for index in order:
        if current:
            shortest = max(lengths[current[0]], 1e-3)
            stretched = lengths[index] > shortest * _BATCH_DURATION_RATIO
            if len(current) >= _BATCH_SIZE or stretched:
                batches.append(current)
                current = []
        current.append(index)
    if current:
        batches.append(current)
    return batches


class JobStopped(Exception):
    """Raised between clone batches when the user stops the job."""


def write_cloned_lines(
    lines: list[CloneLine],
    *,
    language: str | None = None,
    stop: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Speak every line. One voice and similar lengths share a generate() call."""
    total = len(lines)
    done = 0
    if progress is not None:
        progress(done, total)
    grouped: dict[tuple[str, str], list[CloneLine]] = {}
    for line in lines:
        grouped.setdefault((str(line.ref_audio), line.ref_text.strip()), []).append(line)
    for (ref_audio, ref_text), group in grouped.items():
        lengths = [_batch_length(line) for line in group]
        for indexes in plan_clone_batches(lengths):
            if callable(stop) and stop():
                raise JobStopped("Stopped")
            render_cloned_batch(
                [group[index] for index in indexes],
                Path(ref_audio),
                ref_text,
                language=language,
            )
            done += len(indexes)
            if progress is not None:
                progress(done, total)


def render_cloned(
    text: str,
    ref_audio: Path,
    ref_text: str,
    dest: Path,
    *,
    language: str | None = None,
    duration: float | None = None,
) -> None:
    model = _load_model()
    spoken = text.strip()
    if not spoken:
        raise RuntimeError("Cannot clone an empty line")
    kwargs = _generate_kwargs(model, [spoken], ref_audio, ref_text, language, [_fit_duration(duration)])
    audio = model.generate(**kwargs)
    rate = int(getattr(model, "sampling_rate", 24000) or 24000)
    _write_wav(dest, audio, rate)


def render_cloned_batch(
    lines: list[CloneLine],
    ref_audio: Path,
    ref_text: str,
    *,
    language: str | None = None,
) -> None:
    if len(lines) == 1:
        line = lines[0]
        render_cloned(
            line.text,
            ref_audio,
            ref_text,
            line.dest,
            language=language,
            duration=line.duration,
        )
        return
    model = _load_model()
    texts = [line.text.strip() for line in lines]
    if any(not text for text in texts):
        raise RuntimeError("Cannot clone an empty line")
    durations = [_fit_duration(line.duration) for line in lines]
    kwargs = _generate_kwargs(model, texts, ref_audio, ref_text, language, durations)
    log.info("cloning %d lines in one pass", len(lines))
    audios = model.generate(**kwargs)
    if not isinstance(audios, (list, tuple)) or len(audios) != len(lines):
        raise RuntimeError("OmniVoice returned an unexpected batch")
    rate = int(getattr(model, "sampling_rate", 24000) or 24000)
    for line, audio in zip(lines, audios, strict=True):
        _write_wav(line.dest, audio, rate)


def _batch_length(line: CloneLine) -> float:
    if line.duration is not None:
        return line.duration
    words = max(1, len(line.text.split()))
    return max(0.5, words / 2.3)


def _fit_duration(duration: float | None) -> float | None:
    # Only a duration that already fits the words. A forced short slot
    # invented a noise in front of the line.
    if duration is None or duration < 0.4:
        return None
    return float(duration)


def _generate_kwargs(
    model: object,
    texts: list[str],
    ref_audio: Path,
    ref_text: str,
    language: str | None,
    durations: list[float | None],
) -> dict:
    kwargs: dict = {
        "text": texts[0] if len(texts) == 1 else texts,
        "num_step": _num_step,
        "guidance_scale": _guidance_scale,
    }
    if language:
        kwargs["language"] = language
    if any(item is not None for item in durations):
        kwargs["duration"] = durations[0] if len(durations) == 1 else durations
    prompt = _voice_prompt(model, ref_audio, ref_text)
    if prompt is not None:
        kwargs["voice_clone_prompt"] = prompt
    else:
        kwargs["ref_audio"] = str(ref_audio)
        if ref_text.strip():
            kwargs["ref_text"] = ref_text.strip()
    return kwargs


def _voice_prompt(model: object, ref_audio: Path, ref_text: str) -> object | None:
    key = (str(ref_audio), ref_text.strip())
    prompt = _prompts.get(key)
    if prompt is not None:
        return prompt
    create = getattr(model, "create_voice_clone_prompt", None)
    if create is None:
        return None
    prompt_kwargs: dict = {"ref_audio": str(ref_audio)}
    if ref_text.strip():
        prompt_kwargs["ref_text"] = ref_text.strip()
    prompt = create(**prompt_kwargs)
    _prompts[key] = prompt
    return prompt


def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        from omnivoice import OmniVoice
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "OmniVoice is not installed in the worker, so each speaker's voice cannot be cloned. "
            "Rebuild the worker image and run the job again."
        ) from exc

    if torch.cuda.is_available():
        device, dtype = "cuda:0", torch.float16
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        device, dtype = "mps", torch.float32
    else:
        device, dtype = "cpu", torch.float32

    log.info("loading OmniVoice on %s", device)
    _model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=dtype)
    return _model


def _write_wav(dest: Path, audio: object, sample_rate: int) -> None:
    import numpy as np

    data = audio[0] if isinstance(audio, (list, tuple)) else audio
    if isinstance(data, (list, tuple)):
        data = data[0]
    samples = np.asarray(data, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 2.0:
        samples = samples / 32768.0
    samples = np.clip(samples, -1.0, 1.0)
    ints = array.array("h", (int(sample * 32767) for sample in samples.tolist()))
    if sys.byteorder != "little":
        ints.byteswap()
    with wave.open(str(dest), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(ints.tobytes())
