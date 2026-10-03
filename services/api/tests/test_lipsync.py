from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.ffmpeg_tools import probe_duration, run_cmd
from app.providers.local import LocalLipSyncProvider, _encode


class _Store:
    def __init__(self) -> None:
        self.copied: tuple[str, str, str] | None = None

    def copy_object(self, source: str, dest: str, content_type: str) -> None:
        self.copied = (source, dest, content_type)


def test_lipsync_keeps_the_original_picture() -> None:
    store = _Store()
    result = LocalLipSyncProvider(store).sync("src.mp4", "voice.wav", "out.mp4")  # type: ignore[arg-type]
    assert result.meta["provider"] == "passthrough"
    assert "original picture" in str(result.meta["note"])
    assert store.copied == ("src.mp4", "out.mp4", "video/mp4")


def test_render_keeps_the_picture_when_the_dub_ends_early(tmp_path: Path) -> None:
    video = tmp_path / "in.mp4"
    audio = tmp_path / "in.wav"
    out = tmp_path / "out.mp4"
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x120:r=25:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ]
    )
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=24000:duration=1",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ]
    )
    _encode(video, audio, out, tmp_path, burn=False)
    picture = probe_duration(video)
    rendered = probe_duration(out)
    assert rendered == pytest.approx(picture, abs=0.15)
    assert rendered > 1.5
