"""The dubbed voice sits on the original music and room tone."""

from __future__ import annotations

import array
import math
import shutil
import wave
from pathlib import Path

import pytest

from app.providers.ffmpeg_tools import run_cmd, write_silence
from app.providers.local import LocalMediaRenderer
from app.providers.speakers import read_pcm16
from app.providers.stems import mix_dub_over_background, separate_accompaniment, write_pcm16_wav


def test_mix_keeps_background_and_voice(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required")
    background = tmp_path / "bg.wav"
    voice = tmp_path / "voice.wav"
    mixed = tmp_path / "mix.wav"
    _tone(background, 220, 1.2)
    _tone(voice, 880, 1.2)
    mix_dub_over_background(background, voice, mixed)
    samples, rate = read_pcm16(mixed)
    assert _tone_energy(samples, rate, 220) > 0.02
    assert _tone_energy(samples, rate, 880) > 0.02


def test_gaps_in_the_dub_keep_the_background(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required")
    background = tmp_path / "bg.wav"
    voice = tmp_path / "voice.wav"
    mixed = tmp_path / "mix.wav"
    _tone(background, 220, 1.2)
    write_silence(voice, 1.2)
    mix_dub_over_background(background, voice, mixed)
    samples, rate = read_pcm16(mixed)
    assert _rms(samples) > 0.05
    assert _tone_energy(samples, rate, 220) > 0.02


def test_render_muxes_the_original_ambience(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg required")
    video = tmp_path / "clip.mp4"
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=44100:duration=1.0",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=10:d=1.0",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ]
    )
    voice = tmp_path / "voice.wav"
    write_silence(voice, 1.0)
    stored: dict[str, bytes] = {"in.mp4": video.read_bytes(), "voice.wav": voice.read_bytes()}

    def keep_everything(source: Path, dest: Path, work: Path) -> None:
        del work
        dest.write_bytes(source.read_bytes())

    monkeypatch.setattr("app.providers.local.separate_accompaniment", keep_everything)

    class Storage:
        def download(self, key: str, dest: Path) -> None:
            dest.write_bytes(stored[key])

        def upload_path(self, key: str, path: Path, content_type: str) -> None:
            del content_type
            stored[key] = path.read_bytes()

    result = LocalMediaRenderer(Storage()).render("in.mp4", "voice.wav", "out.mp4")  # type: ignore[arg-type]
    assert result.meta["background"] == "kept"
    rendered = tmp_path / "out.mp4"
    rendered.write_bytes(stored["out.mp4"])
    soundtrack = tmp_path / "out.wav"
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(rendered),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(soundtrack),
        ]
    )
    samples, rate = read_pcm16(soundtrack)
    assert _rms(samples) > 0.02
    assert _tone_energy(samples, rate, 220) > 0.01


def test_missing_separator_fails_the_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required")

    def unavailable(source: Path, dest: Path, work: Path) -> None:
        del source, dest, work
        raise RuntimeError("demucs is not installed")

    monkeypatch.setattr("app.providers.local.separate_accompaniment", unavailable)
    video = tmp_path / "clip.mp4"
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=44100:duration=0.4",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=10:d=0.4",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ]
    )
    voice = tmp_path / "voice.wav"
    write_silence(voice, 0.4)
    stored = {"in.mp4": video.read_bytes(), "voice.wav": voice.read_bytes()}

    class Storage:
        def download(self, key: str, dest: Path) -> None:
            dest.write_bytes(stored[key])

        def upload_path(self, key: str, path: Path, content_type: str) -> None:
            del key, path, content_type

    with pytest.raises(RuntimeError, match="Background separation failed"):
        LocalMediaRenderer(Storage()).render("in.mp4", "voice.wav", "out.mp4")  # type: ignore[arg-type]


def test_pcm16_writer_keeps_stereo_samples(tmp_path: Path) -> None:
    dest = tmp_path / "stem.wav"
    write_pcm16_wav(dest, array.array("h", [0, 16000, 0, -16000, 1000, -1000]), 2, 44100)
    with wave.open(str(dest), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getframerate() == 44100
        assert handle.getnframes() == 3
        assert array.array("h", handle.readframes(3)) == array.array("h", [0, 16000, 0, -16000, 1000, -1000])


def test_separate_requires_demucs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.providers.stems.importlib.util.find_spec", lambda name: None)
    with pytest.raises(RuntimeError, match="demucs is not installed"):
        separate_accompaniment(tmp_path / "in.wav", tmp_path / "out.wav", tmp_path / "work")


def _tone(dest: Path, frequency: float, duration: float) -> None:
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=44100:duration={duration}",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )


def _rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _tone_energy(samples: list[float], rate: int, frequency: float) -> float:
    if not samples:
        return 0.0
    step = 2 * math.pi * frequency / rate
    sine = 0.0
    cosine = 0.0
    for index, sample in enumerate(samples):
        angle = step * index
        sine += sample * math.sin(angle)
        cosine += sample * math.cos(angle)
    return math.sqrt(sine * sine + cosine * cosine) / len(samples)
