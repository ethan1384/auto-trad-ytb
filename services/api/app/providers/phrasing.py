"""Keep dubbed lines speakable.

Whisper often cuts a sentence at a pause, and Argos then translates each
fragment alone. A name that follows "called" or "named" must stay as spoken.
The clause after that name is its own line: one breath for the clone, not a
paragraph stretched across the whole turn.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.providers.base import TranscriptSegment, replace_segment_text

# Longer cues first so "s'appelle" is not split on "appelle".
_NAME_CUE = r"s'appelle|appelle|nommée|nommé|nomme|name is|known as|called|named"
_INLINE = re.compile(rf"(?is)^(?P<head>.*?\b(?:{_NAME_CUE})\b\s+)(?P<name>\S.*?)$")
_TAIL = re.compile(rf"(?i)\b(?:{_NAME_CUE})\b[.!?]*\s*$")

_MAX_NAME_WORDS = 4
_MERGE_GAP_SECONDS = 0.8
_PAUSE_SECONDS = 0.45
# Past this, OmniVoice smears the line instead of saying it.
_MAX_MERGED_WORDS = 8
_MAX_MERGED_SECONDS = 6.5
_MAX_BREATH_WORDS = 22
# Words that start the next clause, so they are not part of the name.
_CONTINUATION = frozenset(
    {
        "if",
        "because",
        "and",
        "so",
        "but",
        "then",
        "when",
        "while",
        "go",
        "please",
        "we",
        "i",
        "you",
        "he",
        "she",
        "they",
        "it",
        "hit",
        "check",
        "si",
        "parce",
        "car",
        "et",
        "donc",
        "alors",
        "allez",
    }
)
# Capital words that start a new sentence when Whisper drops the period.
_CLAUSE_START = frozenset({"if", "we", "please", "go", "hit", "all", "it's"})


def segments_from_words(words: list[tuple[float, float, str]]) -> list[TranscriptSegment]:
    """One breath per sentence. The name after a calling cue stays on that cue."""
    cleaned = [(start, end, token.strip()) for start, end, token in words if token and token.strip()]
    if not cleaned:
        return []
    groups: list[list[tuple[float, float, str]]] = []
    current: list[tuple[float, float, str]] = []
    for word in cleaned:
        if current and _should_break(current, word):
            groups.append(current)
            current = []
        current.append(word)
        if _ends_sentence(word[2]) and not _waiting_for_name(current):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return [_group_segment(group) for group in groups if group]


def split_sentences(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Break a whisper line on sentence punctuation, keeping a name on its cue."""
    output: list[TranscriptSegment] = []
    for segment in segments:
        parts = _glue_name_parts(_sentence_parts(segment.text))
        if len(parts) <= 1:
            output.append(_clone(segment))
            continue
        output.extend(_spread(segment, parts))
    return output


def merge_clauses(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Join a naming cue to its name. Do not glue a whole monologue into one line."""
    if not segments:
        return []
    merged: list[TranscriptSegment] = [_clone(segments[0])]
    for segment in segments[1:]:
        previous = merged[-1]
        incoming = _clone(segment)
        if not _can_merge(previous, incoming):
            merged.append(incoming)
            continue
        if _TAIL.search(previous.text.strip()):
            named, rest = _split_incoming_name(incoming)
            _append_segment(previous, named)
            if rest is not None:
                merged.append(rest)
            continue
        _append_segment(previous, incoming)
    return merged


def _should_break(current: list[tuple[float, float, str]], nxt: tuple[float, float, str]) -> bool:
    text = _join_words(current)
    tail = _cue_tail(text)
    gap = nxt[0] - current[-1][1]
    if tail is not None:
        if tail == "":
            return False
        _name, rest = _split_name(tail)
        if rest:
            return True
        bare = nxt[2].strip(".,!?;:\"'").lower()
        if bare in _CONTINUATION or gap >= _PAUSE_SECONDS or len(_name.split()) >= _MAX_NAME_WORDS:
            return True
        return False
    if gap >= _PAUSE_SECONDS and len(current) >= 2:
        return True
    bare = nxt[2].strip(".,!?;:\"'")
    # "It's" / "All" / "Go" start a sentence even when the period was dropped.
    if current and bare[:1].isupper() and bare.lower() in _CLAUSE_START:
        return True
    # Same cue in lowercase after a finished phrase: "check it out hit the button".
    if bare.lower() == "please" and current:
        return True
    if len(current) >= 4 and bare.lower() in {"go", "hit"}:
        return True
    if len(current) >= _MAX_BREATH_WORDS and bare.lower() not in {"to", "a", "the", "of", "and"}:
        return True
    return False


def _waiting_for_name(words: list[tuple[float, float, str]]) -> bool:
    return _cue_tail(_join_words(words)) == ""


def _ends_sentence(token: str) -> bool:
    return bool(re.search(r"[.!?]$", token))


def _join_words(words: list[tuple[float, float, str]]) -> str:
    tokens: list[str] = []
    for index, word in enumerate(words):
        token = word[2]
        bare = token.strip(".,!?;:\"'")
        # Whisper capitalizes "That" after a pause with no period, and Argos
        # then switches to "tu". Keep it one sentence.
        if index and bare.lower() == "that" and bare[:1].isupper():
            token = token.replace(bare, bare.lower(), 1)
        tokens.append(token)
    return " ".join(tokens).strip()


_FRENCH_VARIETY: dict[str, list[tuple[str, str]]] = {
    "fr-CA": [
        (r"\bweek-ends\b", "fins de semaine"),
        (r"\bweek-end\b", "fin de semaine"),
        (r"\be-mails\b", "courriels"),
        (r"\bemails\b", "courriels"),
        (r"\be-mail\b", "courriel"),
        (r"\bemail\b", "courriel"),
        (r"\bparkings\b", "stationnements"),
        (r"\bparking\b", "stationnement"),
        (r"\bshopping\b", "magasinage"),
    ],
    "fr-FR": [
        (r"\bfins de semaine\b", "week-ends"),
        (r"\bfin de semaine\b", "week-end"),
        (r"\bcourriels\b", "e-mails"),
        (r"\bcourriel\b", "e-mail"),
        (r"\bstationnements\b", "parkings"),
        (r"\bstationnement\b", "parking"),
        (r"\bmagasinage\b", "shopping"),
        (r"\bicitte\b", "ici"),
    ],
    "fr-BE": [
        (r"\bquatre-vingt-dix\b", "nonante"),
        (r"\bsoixante-dix\b", "septante"),
    ],
    "fr-CH": [
        (r"\bquatre-vingt-dix\b", "nonante"),
        (r"\bsoixante-dix\b", "septante"),
        (r"\bquatre-vingts\b", "huitante"),
        (r"\bquatre-vingt\b(?!-)", "huitante"),
    ],
}


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply_french_variety(text: str, accent: str | None) -> str:
    """Shift a few words that mark Québec, France, Belgium, or Switzerland."""
    spoken = " ".join(text.split())
    rules = _FRENCH_VARIETY.get(accent or "")
    if not rules:
        return spoken
    for pattern, replacement in rules:
        spoken = re.sub(
            pattern,
            lambda match, repl=replacement: _match_case(match.group(0), repl),
            spoken,
            flags=re.IGNORECASE,
        )
    return spoken


def polish_spoken(text: str, source_text: str, language: str) -> str:
    """Fix a few Argos phrasings that come out wrong when spoken."""
    spoken = " ".join(text.split())
    if language != "fr":
        return spoken
    spoken = spoken.replace("génials", "géniaux")
    source = source_text.lower()
    if "all my friend" in source and "tous mes amis" not in spoken.lower():
        spoken = spoken.replace("mes amis", "tous mes amis")
    if source.strip(" .!?").startswith("go check it out") and spoken.strip() in {"Va voir.", "Va voir"}:
        spoken = "Allez voir."
    return spoken


def _group_segment(words: list[tuple[float, float, str]]) -> TranscriptSegment:
    text = _join_words(words)
    return TranscriptSegment(words[0][0], words[-1][1], text, source_text=text)


def _cue_tail(text: str) -> str | None:
    """Words after the naming cue. Empty when the cue is still waiting for the name."""
    stripped = text.strip()
    if _TAIL.search(stripped):
        return ""
    match = _INLINE.match(stripped)
    if match is None:
        return None
    return match.group("name")


def _sentence_parts(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _glue_name_parts(parts: list[str]) -> list[str]:
    glued: list[str] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        if index + 1 < len(parts) and _TAIL.search(part):
            name, rest = _split_name(parts[index + 1])
            glued.append(f"{part} {name}".strip())
            if rest:
                glued.append(rest)
            index += 2
            continue
        glued.append(part)
        index += 1
    return glued


def _spread(segment: TranscriptSegment, parts: list[str]) -> list[TranscriptSegment]:
    weights = [max(len(part.split()), 1) for part in parts]
    total = sum(weights)
    span = max(segment.end - segment.start, 0.25 * len(parts))
    cursor = segment.start
    source = (segment.source_text or segment.text).strip()
    source_parts = _glue_name_parts(_sentence_parts(source))
    if len(source_parts) != len(parts):
        source_parts = parts
    rows: list[TranscriptSegment] = []
    for part, weight, source_part in zip(parts, weights, source_parts, strict=True):
        dur = span * weight / total
        end = cursor + dur
        rows.append(
            TranscriptSegment(
                cursor,
                end,
                part,
                speaker=segment.speaker,
                source_text=source_part,
            )
        )
        cursor = end
    if rows:
        rows[-1].end = max(rows[-1].end, segment.end)
    return rows


def _can_merge(previous: TranscriptSegment, incoming: TranscriptSegment) -> bool:
    gap = incoming.start - previous.end
    if not _same_speaker(previous, incoming):
        return False
    if previous.text.rstrip()[-1:] in ".?!":
        return False
    if not (-0.05 <= gap < _MERGE_GAP_SECONDS):
        return False
    incoming_first = incoming.text.strip().split()[:1]
    if incoming_first:
        bare = incoming_first[0].strip(".,!?;:\"'").lower()
        if bare in {"please", "go", "hit", "all"}:
            return False
    if _TAIL.search(previous.text.strip()):
        return True
    if gap >= _PAUSE_SECONDS:
        return False
    words = len(f"{previous.text} {incoming.text}".split())
    duration = max(incoming.end, previous.end) - previous.start
    return words <= _MAX_MERGED_WORDS and duration <= _MAX_MERGED_SECONDS


def _split_incoming_name(incoming: TranscriptSegment) -> tuple[TranscriptSegment, TranscriptSegment | None]:
    name, rest = _split_name(incoming.text.strip())
    if not name or not rest:
        return incoming, None
    source = (incoming.source_text or incoming.text).strip()
    if source == incoming.text.strip():
        source_name, source_rest = name, rest
    else:
        source_name, source_rest = _split_name(source)
        if not source_rest:
            source_name, source_rest = source, ""
    name_words = max(len(name.split()), 1)
    rest_words = max(len(rest.split()), 1)
    span = max(incoming.end - incoming.start, 0.2)
    name_end = incoming.start + span * name_words / (name_words + rest_words)
    named = TranscriptSegment(
        incoming.start,
        name_end,
        name,
        speaker=incoming.speaker,
        source_text=source_name,
    )
    remainder = TranscriptSegment(
        name_end,
        max(incoming.end, name_end),
        rest,
        speaker=incoming.speaker,
        source_text=source_rest or rest,
    )
    return named, remainder


def _append_segment(previous: TranscriptSegment, incoming: TranscriptSegment) -> None:
    previous.end = max(previous.end, incoming.end)
    prev_source = (previous.source_text or previous.text).rstrip()
    next_source = (incoming.source_text or incoming.text).strip()
    previous.text = f"{previous.text.rstrip()} {incoming.text.strip()}".strip()
    previous.source_text = f"{prev_source} {next_source}".strip()


_PACK_WORDS = 18
_PACK_SECONDS = 7.5
_PACK_GAP = 0.75
# A shorter line makes OmniVoice invent a noise in front of the words.
_PACK_MIN_WORDS = 8


def pack_lines(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Join short same-speaker lines so the clone speaks a real phrase."""
    if not segments:
        return []
    packed: list[TranscriptSegment] = [_clone(segments[0])]
    for segment in segments[1:]:
        previous = packed[-1]
        incoming = _clone(segment)
        if _can_pack(previous, incoming):
            _pack_append(previous, incoming)
        else:
            packed.append(incoming)
    return packed


def _can_pack(previous: TranscriptSegment, incoming: TranscriptSegment) -> bool:
    if not _same_speaker(previous, incoming):
        return False
    gap = incoming.start - previous.end
    if gap > 1.1:
        return False
    words = len(f"{previous.text} {incoming.text}".split())
    duration = max(incoming.end, previous.end) - previous.start
    incoming_words = len(incoming.text.split())
    if incoming_words <= 4 and words <= 24 and duration <= 9:
        return True
    if gap > _PACK_GAP:
        return False
    if len(previous.text.split()) < _PACK_MIN_WORDS and words <= 24 and duration <= 9:
        return True
    return words <= _PACK_WORDS and duration <= _PACK_SECONDS


def _pack_append(previous: TranscriptSegment, incoming: TranscriptSegment) -> None:
    previous_text = previous.text.rstrip().rstrip(",;:")
    if previous_text and previous_text[-1] not in ".!?":
        previous.text = f"{previous_text}."
    else:
        previous.text = previous_text
    _append_segment(previous, incoming)


def protected_name(text: str) -> str:
    """The short name after a calling cue, or empty when the line has none."""
    match = _INLINE.match(text.strip())
    if match is None:
        return ""
    name, _rest = _split_name(match.group("name"))
    return name.strip(" .,!?;:\"'")


def preserve_names(
    segments: list[TranscriptSegment], translate: Callable[[str], str]
) -> list[TranscriptSegment]:
    """Translate each line, leaving the name after a calling/naming cue intact."""
    output: list[TranscriptSegment] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        text = segment.text.strip()
        if not text:
            output.append(replace_segment_text(segment, ""))
            index += 1
            continue
        nxt = segments[index + 1] if index + 1 < len(segments) else None
        if nxt is not None and _TAIL.search(text) and _same_speaker(segment, nxt):
            output.append(replace_segment_text(segment, translate(text)))
            output.append(replace_segment_text(nxt, _protect_leading_name(nxt.text, translate)))
            index += 2
            continue
        output.append(replace_segment_text(segment, _translate_keeping_name(text, translate)))
        index += 1
    return output


def _translate_keeping_name(text: str, translate: Callable[[str], str]) -> str:
    match = _INLINE.match(text.strip())
    if match is None:
        return translate(text.strip())
    head = translate(match.group("head").strip()).rstrip()
    name, rest = _split_name(match.group("name"))
    spoken = f"{head} {name}".strip()
    if rest:
        spoken = f"{spoken} {translate(rest)}".strip()
    return spoken


def _protect_leading_name(text: str, translate: Callable[[str], str]) -> str:
    """The previous line ended on the cue, so this line starts with the name."""
    name, rest = _split_name(text.strip())
    if not rest:
        return name
    return f"{name} {translate(rest)}".strip()


def _split_name(tail: str) -> tuple[str, str]:
    """Keep a short name, and return the clause that follows it."""
    words = tail.split()
    name: list[str] = []
    for index, word in enumerate(words):
        bare = word.strip(".,!?;:\"'").lower()
        if name and bare in _CONTINUATION:
            return " ".join(name), " ".join(words[index:])
        name.append(word)
        if any(mark in word for mark in ".!?"):
            return " ".join(name), " ".join(words[index + 1 :])
        if len(name) >= _MAX_NAME_WORDS:
            return " ".join(name), " ".join(words[index + 1 :])
    return " ".join(name), ""


def _same_speaker(previous: TranscriptSegment, nxt: TranscriptSegment) -> bool:
    return (previous.speaker or "spk0") == (nxt.speaker or "spk0")


def _clone(segment: TranscriptSegment) -> TranscriptSegment:
    return TranscriptSegment(
        segment.start,
        segment.end,
        segment.text,
        speaker=segment.speaker,
        source_text=segment.source_text,
    )
