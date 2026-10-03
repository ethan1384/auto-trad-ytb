"""Turn a source line into one spoken sentence.

The model sees the source line and a short bit of neighboring speech.
It does not see the Argos draft: a word-for-word gloss anchors the model
on the wrong formula. Timing, speaker, and the original wording stay on
the segment. A missing model, a rambling answer, or a dropped name keeps
the Argos line.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from app.providers.base import TranscriptSegment, replace_segment_text
from app.providers.phrasing import protected_name

log = logging.getLogger(__name__)

# A small model copies the literal draft. Formulas (greetings, farewells,
# thanks, slang, idioms) need a model that can say the native expression.
_DEFAULT_MODEL = "qwen3.8:27b"
_SYSTEM = (
    "You dub one spoken line into the target language. "
    "The source line is what was said. "
    "When it is a greeting, farewell, thanks, apology, filler, slang, or idiom, "
    "use the real expression native speakers use for that situation. "
    "Never gloss it word for word, and never invent an expression. "
    "Keep facts, numbers, names, and brands unchanged. "
    "On a video platform, channel means the creator's channel. "
    "Reply with one short spoken line only."
)
_LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
}


class ExpressionRewriter:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = _DEFAULT_MODEL,
        complete: Callable[[str], str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._complete = complete

    def apply(
        self,
        segments: list[TranscriptSegment],
        source_language: str,
        target_language: str,
        progress: Callable[[int, int], None] | None = None,
    ) -> tuple[list[TranscriptSegment], int]:
        if source_language == target_language or not self._reachable():
            return list(segments), 0
        source_name = _LANGUAGE_NAMES.get(source_language, source_language)
        target_name = _LANGUAGE_NAMES.get(target_language, target_language)
        output: list[TranscriptSegment] = []
        rewritten = 0
        failed = False
        total = len(segments)
        if progress is not None:
            progress(0, total)
        for index, segment in enumerate(segments):
            draft = segment.text.strip()
            source = (segment.source_text or "").strip()
            if failed or not draft or not source:
                output.append(segment)
            else:
                prompt = build_rewrite_prompt(
                    source_name,
                    target_name,
                    source,
                    _source_at(segments, index - 1),
                    _source_at(segments, index + 1),
                )
                try:
                    raw = self._ask(prompt)
                except Exception:
                    log.warning("Expression rewrite kept the Argos lines: %s did not answer", self.model)
                    failed = True
                    output.append(segment)
                else:
                    spoken = accept_spoken(raw, draft, source)
                    if spoken is None:
                        output.append(segment)
                    else:
                        output.append(replace_segment_text(segment, spoken))
                        rewritten += 1
            if progress is not None:
                progress(index + 1, total)
        if rewritten:
            log.info("Expression rewrite updated %s lines with %s", rewritten, self.model)
        return output, rewritten

    def _reachable(self) -> bool:
        if self._complete is not None:
            return True
        if not self.base_url:
            return False
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=0.5)
            response.raise_for_status()
        except Exception:
            log.info("Expression rewrite kept the Argos lines: %s is unreachable", self.base_url)
            return False
        return True

    def _ask(self, prompt: str) -> str:
        if self._complete is not None:
            return self._complete(prompt)
        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                # Qwen3 spends the token budget on a hidden trace unless this is off.
                "think": False,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": 0, "num_predict": 64},
            },
            timeout=120.0,
        )
        response.raise_for_status()
        message = response.json().get("message") or {}
        return str(message.get("content") or "")


def build_rewrite_prompt(
    source_language: str,
    target_language: str,
    source: str,
    previous: str = "",
    following: str = "",
) -> str:
    """The source line, plus neighbors so a formula is read in situation."""
    lines = [
        f"Source language: {source_language}",
        f"Target language: {target_language}",
    ]
    if previous:
        lines.append(f"Previous line: {previous}")
    lines.append(f"Line: {source}")
    if following:
        lines.append(f"Next line: {following}")
    return "\n".join(lines)


def _source_at(segments: list[TranscriptSegment], index: int) -> str:
    if index < 0 or index >= len(segments):
        return ""
    text = (segments[index].source_text or "").strip()
    if len(text) <= 180:
        return text
    shortened = text[:180].rsplit(" ", 1)[0]
    return shortened or text[:180]


def accept_spoken(raw: str, draft: str, source: str) -> str | None:
    """One short spoken line, or nothing when the answer explains or drops a name."""
    line = _first_line(raw)
    if not line:
        return None
    name = protected_name(source)
    if name and name.casefold() not in line.casefold():
        return None
    draft_words = max(len(draft.split()), 1)
    if len(line.split()) > max(draft_words + 4, int(draft_words * 1.5)):
        return None
    return line


def _first_line(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    line = text.splitlines()[0].strip()
    if len(line) >= 2 and line[0] == line[-1] and line[0] in "\"'":
        line = line[1:-1].strip()
    if line.startswith("«") and line.endswith("»"):
        line = line[1:-1].strip()
    lowered = line.casefold()
    for prefix in ("spoken ", "rewrite:", "rewritten:", "output:"):
        if lowered.startswith(prefix) and ":" in line:
            line = line.split(":", 1)[1].strip()
            break
    return line
