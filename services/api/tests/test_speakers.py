from __future__ import annotations

import math
import shutil
from pathlib import Path

import pytest

from app.providers.base import RewriteResult, TranscriptSegment, replace_segment_text
from app.providers.ffmpeg_tools import DUB_SAMPLE_RATE, fit_wav, run_cmd
from app.providers.local import LocalMediaRenderer, LocalVoiceSynthesisProvider
from app.providers.speakers import (
    _cluster,
    _drop_nested_turns,
    _labels_from_turns,
    _split_interruptions,
    assign_speakers,
    read_pcm16,
    write_pcm16,
    write_speaker_refs,
)
from app.providers.voice_clone import (
    CloneLine,
    clear_prompts,
    plan_clone_batches,
    render_cloned_batch,
    speaking_duration,
    write_cloned_lines,
)


def _buzz(f0: float, seconds: float, sample_rate: int = 16000, brightness: float = 0.2) -> list[float]:
    count = int(seconds * sample_rate)
    samples: list[float] = []
    acc = 0.0
    for index in range(count):
        phase = 2 * math.pi * f0 * index / sample_rate
        sample = 0.0
        harmonic = 1
        while harmonic * f0 < 3500:
            sample += math.sin(phase * harmonic) / harmonic
            harmonic += 1
        acc += 0.15 * (sample - acc)
        mixed = sample * (1 - brightness) + (sample - acc) * brightness
        samples.append(mixed)
    peak = max(abs(sample) for sample in samples) or 1.0
    return [sample / peak * 0.55 for sample in samples]


def _wav_with_regions(path: Path, regions: list[tuple[float, float, list[float]]], sample_rate: int = 16000) -> None:
    total = max(int(end * sample_rate) for _, end, _ in regions) + 1
    samples = [0.0] * total
    for start, _end, clip in regions:
        offset = int(start * sample_rate)
        for index, sample in enumerate(clip):
            if offset + index < total:
                samples[offset + index] = sample
    write_pcm16(path, samples, sample_rate)


def test_same_voice_stays_one_speaker(tmp_path: Path) -> None:
    wav = tmp_path / "same.wav"
    tone = _buzz(140, 0.8)
    _wav_with_regions(wav, [(0.0, 0.8, tone), (1.1, 1.9, tone)])
    segments = [
        TranscriptSegment(0.0, 0.8, "Hello there"),
        TranscriptSegment(1.1, 1.9, "Nice to meet you"),
    ]
    assert assign_speakers(wav, segments) == ["spk0"]
    assert segments[0].source_text == "Hello there"
    assert segments[1].speaker == "spk0"


def test_short_clip_does_not_invent_a_speaker() -> None:
    main = [1.0, 0.0]
    blurt = [0.0, 1.0]
    labels = _cluster([main, blurt], 0.55, durations=[2.0, 0.4])
    assert labels == [0, 0]


def test_short_ambiguous_line_can_be_its_own_speaker() -> None:
    main = [1.0, 0.0]
    side = 0.43
    other = [side, (1 - side * side) ** 0.5]
    labels = _cluster([main, other], 0.55, durations=[3.0, 0.9])
    assert labels == [0, 1]


def test_a_long_unclear_voice_still_splits() -> None:
    main = [1.0, 0.0]
    side = 0.43
    other = [side, (1 - side * side) ** 0.5]
    labels = _cluster([main, other], 0.55, durations=[3.0, 3.0])
    assert labels == [0, 1]


def test_a_short_line_that_matches_nobody_is_a_new_speaker() -> None:
    main = [1.0, 0.0]
    other = [0.0, 1.0]
    labels = _cluster([main, other], 0.55, durations=[3.0, 0.9])
    assert labels == [0, 1]


def test_a_long_different_voice_still_splits() -> None:
    main = [1.0, 0.0]
    other = [0.0, 1.0]
    labels = _cluster([main, other], 0.55, durations=[2.0, 2.0])
    assert labels == [0, 1]


def test_dialogue_questions_stay_with_the_person_who_asked() -> None:
    """The mother-and-daughter clip: a short question is not the answer before it."""
    mother = 1
    daughter = 0
    segments = [
        TranscriptSegment(6.46, 7.62, "La fille, elle était méchante, attention."),
        TranscriptSegment(7.90, 11.36, "Puis elle était plus vieille que moi et elle me harcelait."),
        TranscriptSegment(15.54, 18.60, "Non, mais il est pas sorti complètement."),
        TranscriptSegment(18.90, 19.76, "Non, mais elle a fait quoi ?"),
        TranscriptSegment(19.76, 22.04, "Elle est partie avec l'œil ou elle a essayé de le remettre ?"),
        TranscriptSegment(22.04, 23.74, "Oui, oui, elle a essayé de le remettre."),
        TranscriptSegment(51.34, 52.04, "C'est horrible."),
    ]
    turns = [
        (6.46, 11.36, mother),
        (15.54, 18.90, mother),
        (18.90, 22.04, daughter),
        (22.04, 28.12, mother),
        (51.34, 52.04, daughter),
        (52.34, 58.78, mother),
    ]
    labels = _labels_from_turns(segments, turns)
    assert labels[0] == labels[1] == mother
    assert labels[3] == daughter
    assert labels[4] == daughter
    assert labels[5] == mother
    assert labels[6] == daughter


def test_a_short_overlap_is_not_a_new_speaker() -> None:
    turns = [
        (39.13, 58.96, 1),
        (43.55, 44.21, 2),
    ]
    assert _drop_nested_turns(turns) == [(39.13, 58.96, 1)]


def test_a_short_question_turn_is_kept() -> None:
    turns = [
        (15.54, 18.90, 1),
        (18.90, 19.76, 0),
        (22.04, 28.12, 1),
    ]
    assert _drop_nested_turns(turns) == turns


def test_a_gap_follows_the_nearest_turn() -> None:
    segments = [TranscriptSegment(10.0, 10.4, "Hein ?")]
    turns = [(0.0, 2.0, 0), (12.0, 14.0, 1)]
    assert _labels_from_turns(segments, turns) == [1]


def test_an_interruption_is_cut_into_both_speakers() -> None:
    """The second person starts before the first has finished. Each keeps their words."""
    segment = TranscriptSegment(
        10.0,
        16.0,
        "on va continuer attends je parlais encore",
        source_text="on va continuer attends je parlais encore",
    )
    words = [
        (10.0, 10.4, "on"),
        (10.5, 10.9, "va"),
        (11.0, 11.8, "continuer"),
        (12.4, 13.2, "attends"),
        (13.4, 13.8, "je"),
        (13.9, 14.4, "parlais"),
        (14.6, 15.6, "encore"),
    ]
    turns = [(10.0, 12.6, 0), (12.0, 16.0, 1)]
    pieces = _split_interruptions([segment], turns, words)
    assert [speaker for speaker, _segment in pieces] == [0, 1]
    assert pieces[0][1].text == "on va continuer"
    assert pieces[1][1].text == "attends je parlais encore"
    assert pieces[0][1].end <= pieces[1][1].start + 0.05


def test_a_cut_in_that_continues_past_the_line_is_split() -> None:
    segment = TranscriptSegment(19.76, 22.04, "Elle est partie avec l'œil ou essayé")
    words = [
        (19.80, 20.10, "Elle"),
        (20.15, 20.50, "est"),
        (20.55, 20.90, "partie"),
        (21.00, 21.30, "avec"),
        (21.35, 21.55, "l'œil"),
        (21.60, 21.80, "ou"),
        (21.85, 22.00, "essayé"),
    ]
    turns = [(18.85, 22.15, 0), (20.91, 25.60, 1)]
    pieces = _split_interruptions([segment], turns, words)
    assert [speaker for speaker, _segment in pieces] == [0, 1]
    assert pieces[0][1].text.startswith("Elle")
    assert pieces[1][1].text.endswith("essayé")


def test_one_speaker_is_not_cut_mid_sentence() -> None:
    segment = TranscriptSegment(6.46, 11.36, "La fille était méchante puis plus vieille")
    words = [
        (6.50, 6.90, "La"),
        (7.00, 7.40, "fille"),
        (7.90, 8.40, "était"),
        (8.50, 9.20, "méchante"),
        (9.40, 10.20, "puis"),
        (10.30, 11.20, "plus"),
    ]
    turns = [(6.40, 11.50, 1)]
    pieces = _split_interruptions([segment], turns, words)
    assert len(pieces) == 1
    assert pieces[0][0] == 1
    assert pieces[0][1].text == segment.text


def test_long_slot_does_not_ask_the_clone_to_drone() -> None:
    assert speaking_duration("Salut", 1.2) == pytest.approx(0.575)
    assert speaking_duration("un deux trois quatre", 2.0) == pytest.approx(2.0)
    # Six words do not fit in two seconds. Forcing that slot invented a noise.
    assert speaking_duration("un deux trois quatre cinq six", 2.0) is None


def test_similar_lines_share_one_lot() -> None:
    assert plan_clone_batches([1.0, 1.1, 1.05, 1.2]) == [[0, 2, 1, 3]]


def test_a_much_longer_line_waits_for_the_next_lot() -> None:
    assert plan_clone_batches([1.0, 1.1, 4.0]) == [[0, 1], [2]]


def test_a_lot_stops_at_four_lines() -> None:
    assert plan_clone_batches([1.0, 1.0, 1.0, 1.0, 1.05]) == [[0, 1, 2, 3], [4]]


def test_batch_keeps_steps_and_reuses_the_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_prompts()
    calls: list[dict] = []
    created: list[dict] = []

    class Fake:
        sampling_rate = 24000

        def create_voice_clone_prompt(self, **kwargs: object) -> dict:
            created.append(kwargs)
            return {"ref_text": kwargs.get("ref_text")}

        def generate(self, **kwargs: object) -> list[object]:
            calls.append(kwargs)
            text = kwargs["text"]
            count = 1 if isinstance(text, str) else len(text)
            return [object() for _ in range(count)]

    monkeypatch.setattr("app.providers.voice_clone._load_model", lambda: Fake())
    monkeypatch.setattr(
        "app.providers.voice_clone._write_wav",
        lambda dest, audio, rate: dest.write_bytes(b"RIFF"),
    )
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"")
    lines = [
        CloneLine("un deux trois quatre", ref, "Hello there", tmp_path / "a.wav", 2.0),
        CloneLine("un deux trois cinq", ref, "Hello there", tmp_path / "b.wav", 2.1),
    ]
    render_cloned_batch(lines, ref, "Hello there", language="fr")
    render_cloned_batch(lines, ref, "Hello there", language="fr")
    assert len(created) == 1
    assert calls[0]["text"] == ["un deux trois quatre", "un deux trois cinq"]
    assert calls[0]["num_step"] == 32
    assert calls[0]["guidance_scale"] == 3.0
    assert calls[0]["language"] == "fr"
    assert calls[0]["duration"] == [2.0, 2.1]
    assert calls[0]["voice_clone_prompt"] is calls[1]["voice_clone_prompt"]


def test_each_voice_is_batched_on_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake(lines: list[CloneLine], ref_audio: Path, ref_text: str, *, language: str | None = None) -> None:
        del ref_audio, language
        calls.append(([line.text for line in lines], ref_text))

    monkeypatch.setattr("app.providers.voice_clone.render_cloned_batch", fake)
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    write_cloned_lines(
        [
            CloneLine("un", first, "ref a", tmp_path / "1.wav", 1.0),
            CloneLine("deux", second, "ref b", tmp_path / "2.wav", 1.0),
            CloneLine("trois", first, "ref a", tmp_path / "3.wav", 1.05),
        ],
        language="fr",
    )
    assert calls == [(["un", "trois"], "ref a"), (["deux"], "ref b")]


def test_clone_progress_counts_finished_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(lines: list[CloneLine], ref_audio: Path, ref_text: str, *, language: str | None = None) -> None:
        del lines, ref_audio, ref_text, language

    monkeypatch.setattr("app.providers.voice_clone.render_cloned_batch", fake)
    seen: list[tuple[int, int]] = []
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    write_cloned_lines(
        [
            CloneLine("un", first, "ref a", tmp_path / "1.wav", 1.0),
            CloneLine("deux", second, "ref b", tmp_path / "2.wav", 1.0),
            CloneLine("trois", first, "ref a", tmp_path / "3.wav", 1.05),
        ],
        language="fr",
        progress=lambda done, total: seen.append((done, total)),
    )
    assert seen == [(0, 3), (2, 3), (3, 3)]


def test_voice_sample_keeps_the_band_the_clone_hears(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required")
    video = tmp_path / "clip.mp4"
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000:duration=0.4",
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
    stored: dict[str, bytes] = {"in.mp4": video.read_bytes()}

    class Storage:
        def download(self, key: str, dest: Path) -> None:
            dest.write_bytes(stored[key])

        def upload_path(self, key: str, path: Path, content_type: str) -> None:
            del content_type
            stored[key] = path.read_bytes()

    LocalMediaRenderer(Storage()).extract_audio("in.mp4", "speech.wav", voice_key="voice.wav")  # type: ignore[arg-type]
    assert _wav_rate(stored["speech.wav"]) == 16000
    assert _wav_rate(stored["voice.wav"]) == DUB_SAMPLE_RATE


def _wav_rate(payload: bytes) -> int:
    import io
    import wave

    with wave.open(io.BytesIO(payload), "rb") as handle:
        return handle.getframerate()


def test_fit_wav_pads_a_short_line(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg required")
    src = tmp_path / "in.wav"
    dest = tmp_path / "out.wav"
    write_pcm16(src, _buzz(180, 0.35), 16000)
    fit_wav(src, dest, 1.2)
    samples, rate = read_pcm16(dest)
    assert len(samples) / rate == pytest.approx(1.2, abs=0.08)
    tail = samples[int(0.7 * rate) :]
    rms = math.sqrt(sum(sample * sample for sample in tail) / len(tail))
    assert rms < 0.02


def test_embedding_match_keeps_two_voices_apart() -> None:
    main = [1.0, 0.0]
    other = [0.0, 1.0]
    close = [0.95, 0.3122]
    labels = _cluster([main, close, other], 0.55)
    assert labels == [0, 0, 1]


def test_different_voices_get_their_own_speaker(tmp_path: Path) -> None:
    wav = tmp_path / "split.wav"
    _wav_with_regions(
        wav,
        [
            (0.0, 1.3, _buzz(110, 1.3, brightness=0.05)),
            (2.0, 3.3, _buzz(240, 1.3, brightness=0.85)),
        ],
    )
    segments = [
        TranscriptSegment(0.0, 1.3, "First person speaking"),
        TranscriptSegment(2.0, 3.3, "Second person answering"),
    ]
    assert assign_speakers(wav, segments) == ["spk0", "spk1"]


def test_reference_keeps_original_words(tmp_path: Path) -> None:
    wav = tmp_path / "refs.wav"
    _wav_with_regions(
        wav,
        [
            (0.0, 1.2, _buzz(110, 1.2)),
            (1.6, 3.0, _buzz(220, 1.4, brightness=0.8)),
        ],
    )
    segments = [
        TranscriptSegment(0.0, 1.2, "Salut", speaker="spk0", source_text="Hello there"),
        TranscriptSegment(1.6, 3.0, "La suite", speaker="spk1", source_text="Here is more"),
    ]
    refs = write_speaker_refs(wav, segments, tmp_path / "out")
    assert refs["spk0"].ref_text == "Hello there"
    assert refs["spk1"].ref_text == "Here is more"
    assert refs["spk0"].wav_path.read_bytes() != refs["spk1"].wav_path.read_bytes()


def test_reference_drops_the_pause_and_keeps_both_phrases(tmp_path: Path) -> None:
    wav = tmp_path / "pause.wav"
    _wav_with_regions(
        wav,
        [
            (0.0, 1.2, _buzz(140, 1.2)),
            (1.8, 3.0, _buzz(140, 1.2)),
        ],
    )
    segments = [
        TranscriptSegment(0.0, 1.2, "A", speaker="spk0", source_text="Hello there friend"),
        TranscriptSegment(1.8, 3.0, "B", speaker="spk0", source_text="More words now"),
    ]
    refs = write_speaker_refs(wav, segments, tmp_path / "out")
    samples, rate = read_pcm16(refs["spk0"].wav_path)
    assert refs["spk0"].ref_text == "Hello there friend More words now"
    assert 2.0 < len(samples) / rate < 2.85


def test_reference_uses_the_opening_not_a_later_block(tmp_path: Path) -> None:
    wav = tmp_path / "opening.wav"
    _wav_with_regions(
        wav,
        [
            (0.0, 3.2, _buzz(140, 3.2)),
            (3.4, 7.2, _buzz(140, 3.8)),
            (8.0, 17.5, _buzz(180, 9.5)),
        ],
    )
    segments = [
        TranscriptSegment(0.0, 3.2, "A", speaker="spk0", source_text="Opening line of the host"),
        TranscriptSegment(3.4, 7.2, "B", speaker="spk0", source_text="Still the same person"),
        TranscriptSegment(8.0, 17.5, "C", speaker="spk0", source_text="Later monologue should not replace the opening"),
    ]
    refs = write_speaker_refs(wav, segments, tmp_path / "out")
    assert refs["spk0"].ref_text.startswith("Opening line")
    assert "Later monologue" not in refs["spk0"].ref_text


def test_reference_keeps_a_second_phrase_past_eight_seconds(tmp_path: Path) -> None:
    wav = tmp_path / "long.wav"
    _wav_with_regions(
        wav,
        [
            (0.0, 4.6, _buzz(140, 4.6)),
            (4.7, 9.3, _buzz(140, 4.6)),
        ],
    )
    segments = [
        TranscriptSegment(0.0, 4.6, "A", speaker="spk0", source_text="First long phrase here"),
        TranscriptSegment(4.7, 9.3, "B", speaker="spk0", source_text="Second long phrase here"),
    ]
    refs = write_speaker_refs(wav, segments, tmp_path / "out")
    assert "Second long phrase" in refs["spk0"].ref_text


def test_replace_segment_text_keeps_speaker() -> None:
    original = TranscriptSegment(0.0, 1.0, "Hello", speaker="spk1", source_text="Hello")
    updated = replace_segment_text(original, "Bonjour")
    assert updated.text == "Bonjour"
    assert updated.speaker == "spk1"
    assert updated.source_text == "Hello"


def test_synthesis_clones_each_speaker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg required")

    calls: list[tuple[str, str]] = []

    def fake_render(text: str, ref_audio: Path, ref_text: str, dest: Path, **kwargs: object) -> None:
        calls.append((text, ref_text, kwargs.get("language"), kwargs.get("duration")))
        write_pcm16(dest, _buzz(180, 0.4), 16000)

    monkeypatch.setattr("app.providers.voice_clone.render_cloned", fake_render)
    monkeypatch.setattr("app.providers.voice_clone.clear_prompts", lambda: None)

    source = tmp_path / "source.wav"
    _wav_with_regions(
        source,
        [
            (0.0, 1.2, _buzz(110, 1.2)),
            (1.6, 3.0, _buzz(220, 1.4, brightness=0.8)),
        ],
    )
    stored: dict[str, bytes] = {"audio.wav": source.read_bytes()}

    class Storage:
        def download(self, key: str, dest: Path) -> None:
            dest.write_bytes(stored[key])

        def upload_path(self, key: str, path: Path, content_type: str) -> None:
            stored[key] = path.read_bytes()

    script = RewriteResult(
        text="Salut. La suite.",
        segments=[
            TranscriptSegment(0.0, 1.2, "Salut", speaker="spk0", source_text="Hello there"),
            TranscriptSegment(1.6, 3.0, "La suite", speaker="spk1", source_text="Here is more"),
        ],
    )
    result = LocalVoiceSynthesisProvider(Storage()).synthesize(  # type: ignore[arg-type]
        script, "audio.wav", "fr", "voice.wav"
    )
    assert result.meta["voice_clone"] is True
    assert result.meta["speakers"] == ["spk0", "spk1"]
    assert [(text, ref) for text, ref, _lang, _slot in calls] == [
        ("Salut", "Hello there"),
        ("La suite", "Here is more"),
    ]
    assert calls[0][2] == "fr"
    assert calls[0][3] == pytest.approx(0.575)
    assert calls[1][3] == pytest.approx(1.4)
    assert stored["voice.wav"][:4] == b"RIFF"


def test_clone_uses_the_original_lines_not_the_packed_phrase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg required")

    calls: list[str] = []

    def fake_render(text: str, ref_audio: Path, ref_text: str, dest: Path, **kwargs: object) -> None:
        del text, ref_audio, kwargs
        calls.append(ref_text)
        write_pcm16(dest, _buzz(180, 0.4), 16000)

    monkeypatch.setattr("app.providers.voice_clone.render_cloned", fake_render)
    monkeypatch.setattr("app.providers.voice_clone.clear_prompts", lambda: None)

    source = tmp_path / "source.wav"
    _wav_with_regions(source, [(0.0, 2.4, _buzz(140, 2.4))])
    stored: dict[str, bytes] = {"audio.wav": source.read_bytes()}

    class Storage:
        def download(self, key: str, dest: Path) -> None:
            dest.write_bytes(stored[key])

        def upload_path(self, key: str, path: Path, content_type: str) -> None:
            stored[key] = path.read_bytes()

    script = RewriteResult(
        text="Phrase collée.",
        segments=[
            TranscriptSegment(
                0.0,
                2.4,
                "Phrase collée pour le doublage français",
                speaker="spk0",
                source_text="packed words that do not match one breath",
            )
        ],
        meta={
            "reference_segments": [
                TranscriptSegment(0.0, 1.1, "Hello", speaker="spk0", source_text="Hello there"),
                TranscriptSegment(1.2, 2.4, "More", speaker="spk0", source_text="Here is more"),
            ]
        },
    )
    LocalVoiceSynthesisProvider(Storage()).synthesize(script, "audio.wav", "fr", "voice.wav")  # type: ignore[arg-type]
    assert calls == ["Hello there Here is more"]


def test_same_speaker_lines_are_cloned_together(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg required")

    calls: list[list[str]] = []

    def fake(lines: list[CloneLine], ref_audio: Path, ref_text: str, *, language: str | None = None) -> None:
        del ref_audio, ref_text
        calls.append([line.text for line in lines])
        assert language == "fr"
        for line in lines:
            write_pcm16(line.dest, _buzz(180, 0.4), 16000)

    monkeypatch.setattr("app.providers.voice_clone.render_cloned_batch", fake)
    monkeypatch.setattr("app.providers.voice_clone.clear_prompts", lambda: None)

    source = tmp_path / "source.wav"
    _wav_with_regions(source, [(0.0, 6.7, _buzz(140, 6.7))])
    stored: dict[str, bytes] = {"audio.wav": source.read_bytes()}

    class Storage:
        def download(self, key: str, dest: Path) -> None:
            dest.write_bytes(stored[key])

        def upload_path(self, key: str, path: Path, content_type: str) -> None:
            stored[key] = path.read_bytes()

    script = RewriteResult(
        text="Trois lignes.",
        segments=[
            TranscriptSegment(0.0, 2.0, "un deux trois quatre", speaker="spk0", source_text="Hello there friend"),
            TranscriptSegment(2.2, 4.3, "un deux trois cinq", speaker="spk0", source_text="And another line"),
            TranscriptSegment(4.5, 6.7, "un deux trois six", speaker="spk0", source_text="Then the last one"),
        ],
    )
    LocalVoiceSynthesisProvider(Storage()).synthesize(script, "audio.wav", "fr", "voice.wav")  # type: ignore[arg-type]
    assert calls == [["un deux trois quatre", "un deux trois cinq", "un deux trois six"]]
    assert stored["voice.wav"][:4] == b"RIFF"


def test_france_accent_still_clones_the_original_speaker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg required")

    calls: list[str] = []

    def fake(lines: list[CloneLine], ref_audio: Path, ref_text: str, *, language: str | None = None) -> None:
        del ref_text
        assert ref_audio.is_file()
        assert language == "fr"
        calls.extend(line.text for line in lines)
        for line in lines:
            write_pcm16(line.dest, _buzz(180, 0.4), 16000)

    monkeypatch.setattr("app.providers.voice_clone.render_cloned_batch", fake)
    monkeypatch.setattr("app.providers.voice_clone.clear_prompts", lambda: None)

    source = tmp_path / "source.wav"
    _wav_with_regions(source, [(0.0, 1.2, _buzz(140, 1.2))])
    stored: dict[str, bytes] = {"audio.wav": source.read_bytes()}

    class Storage:
        def download(self, key: str, dest: Path) -> None:
            dest.write_bytes(stored[key])

        def upload_path(self, key: str, path: Path, content_type: str) -> None:
            del content_type
            stored[key] = path.read_bytes()

    script = RewriteResult(
        text="Bonjour.",
        segments=[TranscriptSegment(0.0, 1.2, "Bonjour", speaker="spk0", source_text="Hello")],
    )
    result = LocalVoiceSynthesisProvider(Storage()).synthesize(  # type: ignore[arg-type]
        script, "audio.wav", "fr", "voice.wav", accent="fr-FR"
    )
    assert calls == ["Bonjour"]
    assert result.meta["voice_clone"] is True
    assert result.meta["provider"] == "omnivoice"
    assert result.meta["accent"] == "fr-FR"
    assert stored["voice.wav"][:4] == b"RIFF"


def test_synthesis_refuses_a_catalog_voice(tmp_path: Path) -> None:
    del tmp_path
    script = RewriteResult(
        text="Bonjour.",
        segments=[TranscriptSegment(0.0, 1.2, "Bonjour", speaker="spk0", source_text="Hello")],
    )

    class Storage:
        def download(self, key: str, dest: Path) -> None:
            raise AssertionError(key)

        def upload_path(self, key: str, path: Path, content_type: str) -> None:
            raise AssertionError(key)

    with pytest.raises(RuntimeError, match="catalog voice"):
        LocalVoiceSynthesisProvider(Storage()).synthesize(  # type: ignore[arg-type]
            script, None, "fr", "voice.wav", accent="fr-BE"
        )
