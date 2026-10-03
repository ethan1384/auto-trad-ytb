"""French variety for a dub: wording only.

The accent changes a few marker words. It never chooses the voice.
Every speaker is still cloned from their own original audio.
"""

from __future__ import annotations

FRENCH_ACCENTS = ("fr-FR", "fr-CA", "fr-BE", "fr-CH")
# Default wording variety. The voice is still the original speaker.
DEFAULT_FRENCH_ACCENT = "fr-CA"


def language_base(code: str | None) -> str:
    if not code:
        return ""
    return code.strip().lower().replace("_", "-").split("-", 1)[0]


def canonical_accent(accent: str) -> str:
    bits = accent.strip().replace("_", "-").split("-")
    if len(bits) != 2 or not bits[0] or not bits[1]:
        raise ValueError("French accent must be fr-FR, fr-CA, fr-BE, or fr-CH")
    code = f"{bits[0].lower()}-{bits[1].upper()}"
    if code not in FRENCH_ACCENTS:
        raise ValueError("French accent must be fr-FR, fr-CA, fr-BE, or fr-CH")
    return code


def resolve_accent(target_language: str | None, accent: str | None) -> str | None:
    """French projects always have an accent. Other languages ignore it."""
    if language_base(target_language) != "fr":
        return None
    if accent is None or not str(accent).strip():
        return DEFAULT_FRENCH_ACCENT
    return canonical_accent(str(accent))
