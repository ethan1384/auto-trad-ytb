"""Assign a speaker id to each transcript line and cut a voice sample per person.

A dialogue is diarized first: each line goes to the person whose turn covers
that time. The per-line embedding remains only when that model is missing.
OmniVoice then clones each sample for the dub.
"""

from __future__ import annotations

import array
import math
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from app.providers.base import TranscriptSegment

MIN_EMBED_SECONDS = 0.35
MAX_EMBED_SECONDS = 6.0
# OmniVoice clones best from about 3–10s of the person's own speech.
MAX_REF_SECONDS = 10.0
MIN_REF_SECONDS = 2.5
# Under a second, a line stays with the person already talking unless it
# matches nobody. Short Titanet windows of the same voice sit near 0.5.
MIN_NEW_SPEAKER_SECONDS = 1.0
# Look back across a short breath so two sentences from one person match,
# but stop at a real pause so the next person is not mixed in.
CONTEXT_SECONDS = 4.5
CONTEXT_GAP = 0.40
# Cosine similarity at or above this joins a line to an existing speaker.
SPECTRAL_MATCH = 0.86


@dataclass
class SpeakerReference:
    speaker: str
    wav_path: Path
    ref_text: str


def speaker_ids(segments: list[TranscriptSegment]) -> list[str]:
    seen: list[str] = []
    for segment in segments:
        if segment.speaker and segment.speaker not in seen:
            seen.append(segment.speaker)
    return seen


def labeled_text(segments: list[TranscriptSegment]) -> str:
    lines: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if segment.speaker:
            lines.append(f"[{segment.speaker}] {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def assign_speakers(
    wav_path: Path,
    segments: list[TranscriptSegment],
    words: list[tuple[float, float, str]] | None = None,
) -> list[str]:
    """Label each segment in time order. Sets speaker and source_text.

    When one person cuts in on the other, the line is split so each keeps
    the words spoken on their side of the interruption.
    """
    samples, sample_rate = read_pcm16(wav_path)
    for segment in segments:
        if not segment.source_text:
            segment.source_text = segment.text
    turns = _diarized_turns(samples, sample_rate)
    if turns:
        pieces = _split_interruptions(segments, turns, words or [])
        names = _names_in_order([speaker for speaker, _segment in pieces])
        segments.clear()
        for name, (_speaker, segment) in zip(names, pieces, strict=True):
            segment.speaker = name
            segments.append(segment)
        return speaker_ids(segments)
    bounds = _context_bounds(segments)
    clips = [_clip(samples, sample_rate, start, end) for start, end in bounds]
    durations = [max(0.0, segment.end - segment.start) for segment in segments]
    labels = _speaker_labels(clips, sample_rate, durations)
    labels = _attach_short_replies(segments, labels)
    names = _names_in_order(labels)
    for segment, name in zip(segments, names, strict=True):
        segment.speaker = name
    return speaker_ids(segments)


def write_speaker_refs(
    source_wav: Path, segments: list[TranscriptSegment], dest_dir: Path
) -> dict[str, SpeakerReference]:
    """Cut a short original-voice sample and its transcript for each speaker."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    samples, sample_rate = read_pcm16(source_wav)
    grouped: dict[str, list[TranscriptSegment]] = {}
    for segment in segments:
        grouped.setdefault(segment.speaker or "spk0", []).append(segment)
    if not grouped:
        raise RuntimeError("No speech segments to clone")

    refs: dict[str, SpeakerReference] = {}
    for speaker, rows in grouped.items():
        chosen = _reference_span(rows)
        clip = _compress_silence(_join_clips(samples, sample_rate, chosen), sample_rate)
        if len(clip) < int(0.2 * sample_rate):
            continue
        path = dest_dir / f"{speaker}.wav"
        write_pcm16(path, clip, sample_rate)
        text = " ".join(row.source_text.strip() for row in chosen if row.source_text.strip())
        refs[speaker] = SpeakerReference(speaker=speaker, wav_path=path, ref_text=text)
    if not refs:
        raise RuntimeError("Could not extract a voice sample from the video")
    return refs


def read_pcm16(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise RuntimeError(f"Expected 16-bit WAV, got sample width {width}")
    ints = array.array("h")
    ints.frombytes(raw)
    if sys.byteorder != "little":
        ints.byteswap()
    if channels == 1:
        return [sample / 32768.0 for sample in ints], rate
    mixed: list[float] = []
    for index in range(0, len(ints), channels):
        mixed.append(sum(ints[index : index + channels]) / channels / 32768.0)
    return mixed, rate


def write_pcm16(path: Path, samples: list[float], sample_rate: int) -> None:
    ints = array.array(
        "h",
        (max(-32767, min(32767, int(sample * 32767))) for sample in samples),
    )
    if sys.byteorder != "little":
        ints.byteswap()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(ints.tobytes())


def _context_bounds(segments: list[TranscriptSegment]) -> list[tuple[float, float]]:
    """A few seconds of the current turn, so one voice is not split every sentence."""
    bounds: list[tuple[float, float]] = []
    run_start = segments[0].start if segments else 0.0
    previous_end = run_start
    for index, segment in enumerate(segments):
        opens_with_someone_else = _opens_turn(segment)
        if index and (segment.start - previous_end >= CONTEXT_GAP or opens_with_someone_else):
            run_start = segment.start
        left = max(run_start, segment.end - CONTEXT_SECONDS)
        bounds.append((left, max(segment.end, left)))
        previous_end = segment.end
    return bounds


# A cut-in shorter than this stays on the line. A real interruption is longer.
MIN_INTERRUPTION_SECONDS = 0.35


def _diarized_turns(samples: list[float], sample_rate: int) -> list[tuple[float, float, int]] | None:
    from app.providers.speaker_diarize import diarize_turns

    turns = diarize_turns(samples, sample_rate)
    if not turns:
        return None
    kept = _drop_nested_turns(turns)
    if not kept:
        return None
    return kept


def _split_interruptions(
    segments: list[TranscriptSegment],
    turns: list[tuple[float, float, int]],
    words: list[tuple[float, float, str]],
) -> list[tuple[int, TranscriptSegment]]:
    """Cut a line where a second person has their own stretch of it."""
    pieces: list[tuple[int, TranscriptSegment]] = []
    for segment in segments:
        slices = _speaker_slices(segment.start, segment.end, turns)
        speakers = {speaker for _start, _end, speaker in slices}
        if len(speakers) < 2:
            speaker = _speaker_at(segment.start, segment.end, turns)
            if speaker is None:
                speaker = slices[0][2] if slices else 0
            pieces.append((speaker, _retimed(segment, segment.start, segment.end, segment.text, segment.source_text)))
            continue
        if words:
            cut = _split_by_words(segment, slices, words)
        else:
            cut = _split_by_time(segment, slices)
        if len(cut) < 2:
            speaker = _speaker_at(segment.start, segment.end, turns)
            if speaker is None:
                speaker = slices[0][2]
            pieces.append((speaker, _retimed(segment, segment.start, segment.end, segment.text, segment.source_text)))
            continue
        pieces.extend(cut)
    return pieces


def _speaker_slices(
    start: float, end: float, turns: list[tuple[float, float, int]]
) -> list[tuple[float, float, int]]:
    """Who owns each part of the span. An overlap is cut in half between them."""
    bounds = {start, end}
    relevant: list[tuple[float, float, int]] = []
    for turn_start, turn_end, speaker in turns:
        left = max(turn_start, start)
        right = min(turn_end, end)
        if right - left < 0.02:
            continue
        relevant.append((left, right, speaker))
        bounds.add(left)
        bounds.add(right)
    points = sorted(bounds)
    raw: list[tuple[float, float, set[int]]] = []
    for left, right in zip(points, points[1:], strict=False):
        if right <= left:
            continue
        active = {speaker for turn_start, turn_end, speaker in relevant if turn_start < right and turn_end > left}
        raw.append((left, right, active))
    resolved: list[tuple[float, float, int | None]] = []
    for index, (left, right, active) in enumerate(raw):
        if len(active) == 1:
            resolved.append((left, right, next(iter(active))))
            continue
        if not active:
            resolved.append((left, right, None))
            continue
        previous = _exclusive_neighbor(raw, index, -1)
        following = _exclusive_neighbor(raw, index, 1)
        if previous is None:
            previous = _exclusive_beyond(left, turns, -1)
        if following is None:
            following = _exclusive_beyond(right, turns, 1)
        if previous is None and following is None and len(active) >= 2:
            ordered = sorted(active, key=lambda speaker: _turn_start(speaker, turns, left))
            previous, following = ordered[0], ordered[1]
        if previous is None and following is None:
            resolved.append((left, right, min(active)))
            continue
        if previous is None or previous == following or following is None:
            resolved.append((left, right, previous if previous is not None else following))
            continue
        mid = (left + right) / 2
        resolved.append((left, mid, previous))
        resolved.append((mid, right, following))
    merged: list[tuple[float, float, int]] = []
    for left, right, speaker in resolved:
        if speaker is None:
            if merged:
                kept_start, _kept_end, kept_speaker = merged[-1]
                merged[-1] = (kept_start, right, kept_speaker)
            continue
        if merged and merged[-1][2] == speaker:
            kept_start, _kept_end, kept_speaker = merged[-1]
            merged[-1] = (kept_start, right, kept_speaker)
        else:
            merged.append((left, right, speaker))
    return _absorb_short_slices(merged)


def _exclusive_beyond(
    moment: float, turns: list[tuple[float, float, int]], direction: int
) -> int | None:
    """The person who is alone just before or after an overlap, within one second."""
    travelled = 0.0
    while travelled <= 1.0:
        travelled += 0.05
        probe = moment + direction * travelled
        if probe < 0:
            return None
        active = {speaker for start, end, speaker in turns if start <= probe < end}
        if len(active) == 1:
            return next(iter(active))
        if not active and travelled > 0.2:
            return None
    return None


def _turn_start(speaker: int, turns: list[tuple[float, float, int]], moment: float) -> float:
    starts = [start for start, end, other in turns if other == speaker and end > moment]
    return min(starts) if starts else moment


def _exclusive_neighbor(raw: list[tuple[float, float, set[int]]], index: int, direction: int) -> int | None:
    cursor = index + direction
    while 0 <= cursor < len(raw):
        active = raw[cursor][2]
        if len(active) == 1:
            return next(iter(active))
        cursor += direction
    return None


def _absorb_short_slices(
    slices: list[tuple[float, float, int]],
) -> list[tuple[float, float, int]]:
    pending = list(slices)
    changed = True
    while changed and len(pending) > 1:
        changed = False
        for index, (start, end, _speaker) in enumerate(pending):
            if end - start >= MIN_INTERRUPTION_SECONDS:
                continue
            if index > 0:
                kept_start, _kept_end, kept_speaker = pending[index - 1]
                pending[index - 1] = (kept_start, end, kept_speaker)
                del pending[index]
            else:
                _next_start, next_end, next_speaker = pending[1]
                pending[1] = (start, next_end, next_speaker)
                del pending[0]
            changed = True
            break
    return pending


def _split_by_words(
    segment: TranscriptSegment,
    slices: list[tuple[float, float, int]],
    words: list[tuple[float, float, str]],
) -> list[tuple[int, TranscriptSegment]]:
    grouped: list[tuple[int, list[tuple[float, float, str]]]] = []
    for word in words:
        midpoint = (word[0] + word[1]) / 2
        if midpoint < segment.start - 0.05 or midpoint > segment.end + 0.05:
            continue
        speaker = _slice_at(midpoint, slices)
        if speaker is None:
            continue
        if grouped and grouped[-1][0] == speaker:
            grouped[-1][1].append(word)
        else:
            grouped.append((speaker, [word]))
    if len(grouped) < 2:
        return []
    return [_segment_from_words(segment, speaker, group) for speaker, group in grouped]


def _split_by_time(
    segment: TranscriptSegment, slices: list[tuple[float, float, int]]
) -> list[tuple[int, TranscriptSegment]]:
    durations = [end - start for start, end, _speaker in slices]
    texts = _divide_tokens(segment.text, durations)
    sources = _divide_tokens(segment.source_text or segment.text, durations)
    pieces: list[tuple[int, TranscriptSegment]] = []
    for (start, end, speaker), text, source in zip(slices, texts, sources, strict=True):
        if not text.strip():
            continue
        pieces.append((speaker, _retimed(segment, start, end, text, source)))
    return pieces if len(pieces) >= 2 else []


def _segment_from_words(
    segment: TranscriptSegment, speaker: int, words: list[tuple[float, float, str]]
) -> tuple[int, TranscriptSegment]:
    text = " ".join(word[2] for word in words).strip()
    source = text
    if (segment.source_text or "").strip() and segment.source_text.strip() != segment.text.strip():
        source = text
    return speaker, _retimed(segment, words[0][0], words[-1][1], text, source)


def _slice_at(moment: float, slices: list[tuple[float, float, int]]) -> int | None:
    for start, end, speaker in slices:
        if start - 1e-3 <= moment <= end + 1e-3:
            return speaker
    return slices[-1][2] if slices else None


def _divide_tokens(text: str, durations: list[float]) -> list[str]:
    tokens = text.split()
    if not tokens:
        return [""] * len(durations)
    if len(durations) <= 1:
        return [" ".join(tokens)]
    total = sum(durations) or 1.0
    counts: list[int] = []
    remaining = len(tokens)
    for index, duration in enumerate(durations):
        left = len(durations) - index - 1
        if left == 0:
            counts.append(remaining)
            break
        count = max(1, round(len(tokens) * duration / total))
        count = min(count, remaining - left)
        counts.append(count)
        remaining -= count
    pieces: list[str] = []
    cursor = 0
    for count in counts:
        pieces.append(" ".join(tokens[cursor : cursor + count]))
        cursor += count
    return pieces


def _retimed(
    segment: TranscriptSegment, start: float, end: float, text: str, source_text: str
) -> TranscriptSegment:
    del segment
    return TranscriptSegment(start, end, text.strip(), source_text=source_text.strip())


def _drop_nested_turns(turns: list[tuple[float, float, int]]) -> list[tuple[float, float, int]]:
    """A short blip inside someone else's turn is overlap, not another person."""
    kept: list[tuple[float, float, int]] = []
    for start, end, speaker in turns:
        duration = end - start
        if duration < 1.0 and _inside_other_turn(start, end, speaker, turns):
            continue
        kept.append((start, end, speaker))
    return kept


def _inside_other_turn(
    start: float, end: float, speaker: int, turns: list[tuple[float, float, int]]
) -> bool:
    duration = max(0.0, end - start)
    if duration <= 0:
        return False
    for other_start, other_end, other in turns:
        if other == speaker:
            continue
        if other_end - other_start <= duration:
            continue
        if _overlap(start, end, other_start, other_end) >= 0.8 * duration:
            return True
    return False


def _labels_from_turns(
    segments: list[TranscriptSegment], turns: list[tuple[float, float, int]]
) -> list[int]:
    """The person who occupies the line. A gap takes the nearest turn, not the previous line."""
    labels: list[int] = []
    previous = turns[0][2] if turns else 0
    for segment in segments:
        speaker = _speaker_at(segment.start, segment.end, turns)
        if speaker is None:
            speaker = previous
        labels.append(speaker)
        previous = speaker
    return labels


def _speaker_at(start: float, end: float, turns: list[tuple[float, float, int]]) -> int | None:
    best_speaker: int | None = None
    best_overlap = 0.0
    nearest_speaker: int | None = None
    nearest_gap = math.inf
    for turn_start, turn_end, speaker in turns:
        covered = _overlap(start, end, turn_start, turn_end)
        if covered > best_overlap:
            best_speaker = speaker
            best_overlap = covered
        gap = _gap(start, end, turn_start, turn_end)
        if gap < nearest_gap:
            nearest_speaker = speaker
            nearest_gap = gap
    if best_overlap > 0:
        return best_speaker
    return nearest_speaker


def _overlap(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    return max(0.0, min(left_end, right_end) - max(left_start, right_start))


def _gap(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    if left_end < right_start:
        return right_start - left_end
    if right_end < left_start:
        return left_start - right_end
    return 0.0


def _speaker_labels(
    clips: list[list[float]], sample_rate: int, durations: list[float]
) -> list[int]:
    from app.providers.speaker_embed import EMBED_MATCH, embed_clips

    voiced = [_trim_silence(clip, sample_rate) for clip in clips]
    vectors = embed_clips(voiced, sample_rate)
    if vectors is not None and any(vectors):
        return _cluster(vectors, EMBED_MATCH, durations)
    spectral = [_embed(clip, sample_rate) for clip in voiced]
    return _cluster(spectral, SPECTRAL_MATCH, durations)


def _compress_silence(samples: list[float], sample_rate: int, threshold: float = 0.012) -> list[float]:
    """Keep the voice and drop pauses, so the clone prompt matches the words.

    OmniVoice strips silence from the sample but keeps the full transcript.
    A packed line includes the breaths between sentences, and that mismatch
    pulls the clone toward a generic voice.
    """
    frame = max(1, int(0.02 * sample_rate))
    if len(samples) < frame * 4:
        return samples
    keep_quiet = max(1, int(0.08 * sample_rate / frame))
    loud = []
    for index in range(0, len(samples), frame):
        window = samples[index : index + frame]
        rms = math.sqrt(sum(sample * sample for sample in window) / len(window))
        loud.append(rms >= threshold)
    keep = [False] * len(loud)
    for index, is_loud in enumerate(loud):
        if not is_loud:
            continue
        start = max(0, index - keep_quiet)
        end = min(len(loud), index + keep_quiet + 1)
        for cursor in range(start, end):
            keep[cursor] = True
    pieces: list[list[float]] = []
    current: list[float] = []
    for index, kept in enumerate(keep):
        window = samples[index * frame : (index + 1) * frame]
        if kept:
            current.extend(window)
        elif current:
            pieces.append(current)
            current = []
    if current:
        pieces.append(current)
    if not pieces:
        return samples
    merged = pieces[0]
    fade = int(0.008 * sample_rate)
    for piece in pieces[1:]:
        merged = _crossfade(merged, piece, fade)
    if len(merged) < int(0.3 * sample_rate):
        return samples
    return merged


def _trim_silence(samples: list[float], sample_rate: int, threshold: float = 0.012) -> list[float]:
    """Drop quiet edges so the previous person's tail is not part of this voice."""
    frame = max(1, int(0.02 * sample_rate))
    if len(samples) < frame * 4:
        return samples

    def loud(index: int) -> bool:
        window = samples[index : index + frame]
        if not window:
            return False
        rms = math.sqrt(sum(sample * sample for sample in window) / len(window))
        return rms >= threshold

    start = 0
    while start + frame < len(samples) and not loud(start):
        start += frame
    end = len(samples)
    while end - frame > start and not loud(end - frame):
        end -= frame
    trimmed = samples[start:end]
    if len(trimmed) < int(0.3 * sample_rate):
        return samples
    return trimmed


def _clip(samples: list[float], sample_rate: int, start: float, end: float) -> list[float]:
    left = max(0, int(start * sample_rate))
    right = min(len(samples), int(end * sample_rate))
    if right <= left:
        return []
    return samples[left:right]


def _embed(samples: list[float], sample_rate: int) -> list[float] | None:
    if len(samples) < int(MIN_EMBED_SECONDS * sample_rate):
        return None
    if len(samples) > int(MAX_EMBED_SECONDS * sample_rate):
        mid = len(samples) // 2
        half = int(MAX_EMBED_SECONDS * sample_rate / 2)
        samples = samples[mid - half : mid + half]
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    if rms < 0.008:
        return None

    shape = _log_band_shape(samples, sample_rate)
    pitch, strength = _pitch(samples, sample_rate)
    return _normalize(shape + [pitch / 250.0, strength])


def _log_band_shape(samples: list[float], sample_rate: int) -> list[float]:
    cutoffs = (150, 300, 600, 1200, 2400, 4800)
    lowpasses = [_lowpass(samples, _alpha(cutoff, sample_rate)) for cutoff in cutoffs]
    bands: list[list[float]] = [lowpasses[0]]
    for previous, current in zip(lowpasses, lowpasses[1:], strict=False):
        bands.append([current[i] - previous[i] for i in range(len(samples))])
    last = lowpasses[-1]
    bands.append([samples[i] - last[i] for i in range(len(samples))])
    logs = [math.log(_rms(band) + 1e-8) for band in bands]
    mean = sum(logs) / len(logs)
    return [value - mean for value in logs]


def _alpha(cutoff_hz: float, sample_rate: int) -> float:
    dt = 1.0 / sample_rate
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    return dt / (rc + dt)


def _lowpass(samples: list[float], alpha: float) -> list[float]:
    out = [0.0] * len(samples)
    acc = 0.0
    for index, sample in enumerate(samples):
        acc += alpha * (sample - acc)
        out[index] = acc
    return out


def _rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _pitch(samples: list[float], sample_rate: int) -> tuple[float, float]:
    """Fundamental frequency via YIN, so a higher voice is not folded an octave down."""
    window = samples
    if len(samples) > int(0.5 * sample_rate):
        mid = len(samples) // 2
        half = int(0.25 * sample_rate)
        window = samples[mid - half : mid + half]
    step = max(1, sample_rate // 8000)
    down = window[::step]
    if len(down) < 64:
        return 0.0, 0.0
    rate = sample_rate / step
    min_lag = max(2, int(rate / 400))
    max_lag = min(len(down) // 2, int(rate / 70))
    if max_lag <= min_lag:
        return 0.0, 0.0
    mean = sum(down) / len(down)
    centered = [sample - mean for sample in down]
    diffs = [0.0] * (max_lag + 1)
    for lag in range(1, max_lag + 1):
        total = 0.0
        for index in range(len(centered) - lag):
            delta = centered[index] - centered[index + lag]
            total += delta * delta
        diffs[lag] = total
    cmnd = [1.0] * (max_lag + 1)
    running = 0.0
    for lag in range(1, max_lag + 1):
        running += diffs[lag]
        cmnd[lag] = diffs[lag] * lag / running if running else 1.0
    threshold = 0.18
    chosen = None
    for lag in range(min_lag, max_lag):
        if cmnd[lag] < threshold:
            while lag + 1 < max_lag and cmnd[lag + 1] < cmnd[lag]:
                lag += 1
            chosen = lag
            break
    if chosen is None:
        chosen = min(range(min_lag, max_lag), key=lambda lag: cmnd[lag])
    confidence = max(0.0, 1.0 - cmnd[chosen])
    return rate / chosen, confidence


def _cluster(
    vectors: list[list[float] | None],
    threshold: float,
    durations: list[float] | None = None,
) -> list[int]:
    labels = [-1] * len(vectors)
    centroids: list[list[float]] = []
    counts: list[int] = []
    previous = 0
    for index, vector in enumerate(vectors):
        if not vector:
            labels[index] = previous
            continue
        match = _best_match(vector, centroids, threshold)
        duration = durations[index] if durations is not None and index < len(durations) else MIN_NEW_SPEAKER_SECONDS
        _closest, closest_score = _closest_score(vector, centroids)
        if match is None and centroids and _stays_with_current(duration, closest_score):
            labels[index] = previous
            previous = labels[index]
            continue
        if match is None:
            labels[index] = len(centroids)
            centroids.append(vector)
            counts.append(1)
        else:
            labels[index] = match
            centroids[match] = _normalize(
                [centroids[match][dim] * counts[match] + vector[dim] for dim in range(len(vector))]
            )
            counts[match] += 1
        previous = labels[index]

    for index, vector in enumerate(vectors):
        if not vector or not centroids:
            continue
        match = _best_match(vector, centroids, threshold)
        if match is not None:
            labels[index] = match
    for index, vector in enumerate(vectors):
        if vector:
            previous = labels[index]
        else:
            labels[index] = previous
    return labels


def _opens_turn(segment: TranscriptSegment) -> bool:
    """'Please…' is a new person in this clip. Do not score it with the previous voice."""
    first = (segment.source_text or segment.text).strip().split()[:1]
    if not first:
        return False
    return first[0].strip(".,!?;:\"'").lower() == "please"


def _stays_with_current(duration: float, closest_score: float) -> bool:
    """Only a backchannel is too short to be its own voice. A real short line can be."""
    del closest_score
    return duration < 0.75


def _attach_short_replies(segments: list[TranscriptSegment], labels: list[int]) -> list[int]:
    """A quick follow-up ("go check it out") keeps the voice that just spoke."""
    attached = list(labels)
    for index in range(1, len(segments)):
        gap = segments[index].start - segments[index - 1].end
        duration = segments[index].end - segments[index].start
        if duration < 1.15 and gap < 1.05:
            attached[index] = attached[index - 1]
    return attached


def _closest_score(vector: list[float], centroids: list[list[float]]) -> tuple[int | None, float]:
    best_index = None
    best_score = -1.0
    for index, centroid in enumerate(centroids):
        score = _cosine(vector, centroid)
        if score > best_score:
            best_index = index
            best_score = score
    return best_index, best_score


def _best_match(vector: list[float], centroids: list[list[float]], threshold: float) -> int | None:
    best_index = None
    best_score = threshold
    for index, centroid in enumerate(centroids):
        score = _cosine(vector, centroid)
        if score >= best_score:
            best_index = index
            best_score = score
    return best_index


def _names_in_order(labels: list[int]) -> list[str]:
    mapping: dict[int, str] = {}
    names: list[str] = []
    for label in labels:
        if label not in mapping:
            mapping[label] = f"spk{len(mapping)}"
        names.append(mapping[label])
    return names


def _reference_span(rows: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """The start of the turn, once it is long enough to clone.

    A later, slightly longer block was winning before. The opening then got
    cloned from the middle of the video and no longer sounded like that person.
    """
    ordered = sorted(rows, key=lambda row: row.start)
    longest: list[TranscriptSegment] = []
    longest_total = -1.0
    for start_index in range(len(ordered)):
        chosen, total = _span_from(ordered[start_index:])
        if total >= 6.0:
            return chosen
        if total > longest_total:
            longest = chosen
            longest_total = total
    return longest or ordered[:1]


def _span_from(rows: list[TranscriptSegment]) -> tuple[list[TranscriptSegment], float]:
    chosen: list[TranscriptSegment] = []
    total = 0.0
    for row in rows:
        if chosen and row.start - chosen[-1].end > 2.5:
            break
        piece = max(0.0, row.end - row.start)
        if total >= MIN_REF_SECONDS and total + piece > MAX_REF_SECONDS:
            break
        chosen.append(row)
        total += piece
        if total >= MAX_REF_SECONDS:
            break
    return chosen, total


def _join_clips(samples: list[float], sample_rate: int, rows: list[TranscriptSegment]) -> list[float]:
    pad = int(0.04 * sample_rate)
    pieces: list[list[float]] = []
    for row in rows:
        start = max(0, int(row.start * sample_rate) - pad)
        end = min(len(samples), int(row.end * sample_rate) + pad)
        if end > start:
            pieces.append(samples[start:end])
    if not pieces:
        return []
    merged = pieces[0]
    fade = int(0.01 * sample_rate)
    for piece in pieces[1:]:
        merged = _crossfade(merged, piece, fade)
    return merged[: int(MAX_REF_SECONDS * sample_rate)]


def _crossfade(left: list[float], right: list[float], fade: int) -> list[float]:
    fade = min(fade, len(left), len(right))
    if fade <= 0:
        return left + right
    mid = []
    for index in range(fade):
        gain = index / fade
        mid.append(left[-fade + index] * (1 - gain) + right[index] * gain)
    return left[:-fade] + mid + right[fade:]


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    return max(-1.0, min(1.0, dot))


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm < 1e-8:
        return vector
    return [value / norm for value in vector]
