"""Keep music, effects, and room tone under the dubbed voice.

Demucs splits the original soundtrack into vocals and everything else. Render
mixes that accompaniment back under the new voice, and ducks it only while
someone is speaking so the dub stays clear.
"""

from __future__ import annotations

import array
import importlib.util
import os
import sys
import wave
from pathlib import Path

from app.providers.ffmpeg_tools import probe_duration, run_cmd

# htdemucs is the default Hybrid Transformer model. Two stems is enough:
# we only need the accompaniment, not a drum/bass split.
DEMUCS_MODEL = os.environ.get("DEMUCS_MODEL", "htdemucs")


def separate_accompaniment(source: Path, dest: Path, work: Path) -> None:
    """Write the original soundtrack with the voice removed."""
    if importlib.util.find_spec("demucs") is None:
        raise RuntimeError(
            "demucs is not installed. The worker needs it to keep music and other sounds "
            "under the dubbed voice."
        )
    work.mkdir(parents=True, exist_ok=True)
    # Demucs asks torchaudio to write the stems. Current torchaudio refuses
    # unless TorchCodec is installed, so the wav is written here instead.
    _use_wav_writer()
    from demucs.separate import main

    try:
        main(
            [
                "--two-stems",
                "vocals",
                "-n",
                DEMUCS_MODEL,
                "--shifts",
                "0",
                "-o",
                str(work),
                str(source),
            ]
        )
    except SystemExit as exc:
        raise RuntimeError(f"demucs exited with status {exc.code}") from exc
    matches = sorted(work.rglob("no_vocals.wav"))
    if not matches:
        raise RuntimeError("demucs did not write a no_vocals stem")
    dest.write_bytes(matches[0].read_bytes())


def _use_wav_writer() -> None:
    import demucs.audio as audio
    import demucs.separate as separate

    def save_audio(
        wav: object,
        path: str,
        samplerate: int,
        bitrate: int = 320,
        clip: str = "rescale",
        bits_per_sample: int = 16,
        as_float: bool = False,
        preset: int = 2,
    ) -> None:
        del bitrate, bits_per_sample, as_float, preset
        clipped = audio.prevent_clip(wav, mode=clip)
        write_pcm16_wav(Path(path), _tensor_pcm16(clipped), int(clipped.shape[0]), samplerate)

    separate.save_audio = save_audio


def _tensor_pcm16(wav: object) -> array.array:
    import torch

    data = wav.detach().cpu().to(torch.float32).clamp(-1, 1)  # type: ignore[attr-defined]
    if data.ndim == 1:
        data = data.unsqueeze(0)
    pcm = data.transpose(0, 1).contiguous().mul(32767).round().clamp(-32768, 32767).to(torch.int16)
    samples = array.array("h")
    samples.frombytes(pcm.numpy().tobytes())
    return samples


def write_pcm16_wav(path: Path, interleaved: array.array, channels: int, samplerate: int) -> None:
    """Write little-endian 16-bit PCM. Demucs stems use this instead of torchaudio."""
    if sys.byteorder != "little":
        interleaved = array.array("h", interleaved)
        interleaved.byteswap()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(samplerate)
        handle.writeframes(interleaved.tobytes())


def mix_dub_over_background(background: Path, voice: Path, dest: Path) -> None:
    """Place the dubbed voice on the accompaniment and leave the gaps open."""
    span = max(probe_duration(background), probe_duration(voice), 0.2)
    length = f"{span:.3f}"
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(background),
            "-i",
            str(voice),
            "-filter_complex",
            (
                f"[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo,aresample=44100,"
                f"apad=whole_dur={length},atrim=0:{length},volume=1.0[bg];"
                f"[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo,aresample=44100,"
                f"apad=whole_dur={length},atrim=0:{length},volume=1.15,asplit=2[sc][dub];"
                "[bg][sc]sidechaincompress=threshold=0.04:ratio=4:attack=20:release=280[ducked];"
                "[ducked][dub]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                "alimiter=limit=0.95[out]"
            ),
            "-map",
            "[out]",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )


def extract_soundtrack(src: Path, dest: Path) -> None:
    """Stereo extract of the picture's own audio, at the rate Demucs expects."""
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )
