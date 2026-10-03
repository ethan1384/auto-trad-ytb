"""Whisper loads on the configured device and keeps working without CUDA."""

from __future__ import annotations

import sys
import types

import pytest

from app.providers.local import _load_whisper


class _FakeWhisper:
    calls: list[dict[str, object]] = []
    fail_on: set[str] = set()

    def __init__(self, name: str, **kwargs: object) -> None:
        _FakeWhisper.calls.append({"name": name, **kwargs})
        if kwargs.get("device") in _FakeWhisper.fail_on:
            raise RuntimeError("Library libcublas.so.12 is not found")


@pytest.fixture(autouse=True)
def fake_faster_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeWhisper.calls = []
    _FakeWhisper.fail_on = set()
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = _FakeWhisper  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)


def test_cpu_stays_int8() -> None:
    _load_whisper("small")
    assert _FakeWhisper.calls == [
        {"name": "small", "device": "cpu", "compute_type": "int8", "cpu_threads": _FakeWhisper.calls[0]["cpu_threads"]}
    ]


def test_cuda_uses_float16() -> None:
    _load_whisper("small", "cuda")
    assert _FakeWhisper.calls == [{"name": "small", "device": "cuda", "compute_type": "float16"}]


def test_missing_cuda_libraries_fall_back_to_cpu() -> None:
    _FakeWhisper.fail_on = {"cuda"}
    model = _load_whisper("small", "cuda")
    assert isinstance(model, _FakeWhisper)
    assert [call["device"] for call in _FakeWhisper.calls] == ["cuda", "cpu"]
    assert _FakeWhisper.calls[1]["compute_type"] == "int8"
