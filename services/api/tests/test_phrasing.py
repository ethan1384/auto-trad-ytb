import pytest
from pydantic import ValidationError

from app.providers.base import TranscriptSegment

from app.accents import resolve_accent
from app.providers.phrasing import (
    apply_french_variety,
    merge_clauses,
    pack_lines,
    polish_spoken,
    preserve_names,
    segments_from_words,
    split_sentences,
)
from app.schemas import ProjectCreate


def test_merge_joins_a_name_split_at_a_pause() -> None:
    segments = [
        TranscriptSegment(0.0, 5.76, "it is called", speaker="spk0", source_text="it is called"),
        TranscriptSegment(5.76, 6.76, "Team Refurb.", speaker="spk0", source_text="Team Refurb."),
        TranscriptSegment(8.0, 9.0, "Look carefully.", speaker="spk0", source_text="Look carefully."),
    ]
    merged = merge_clauses(segments)
    assert len(merged) == 2
    assert merged[0].text == "it is called Team Refurb."
    assert merged[0].source_text == "it is called Team Refurb."
    assert merged[0].end == 6.76
    assert merged[1].text == "Look carefully."


def test_merge_does_not_glue_a_monologue() -> None:
    segments = [
        TranscriptSegment(
            0.0,
            6.0,
            "I have some very exciting news we just launched a brand new channel",
            speaker="spk0",
            source_text="I have some very exciting news we just launched a brand new channel",
        ),
        TranscriptSegment(
            6.1,
            12.0,
            "if you haven't seen it yet go check it out hit the subscribe button",
            speaker="spk0",
            source_text="if you haven't seen it yet go check it out hit the subscribe button",
        ),
    ]
    merged = merge_clauses(segments)
    assert len(merged) == 2


def test_merge_keeps_the_name_and_releases_the_next_clause() -> None:
    segments = [
        TranscriptSegment(0.0, 5.0, "it is called", speaker="spk0", source_text="it is called"),
        TranscriptSegment(
            5.0,
            12.0,
            "Team Refurb if you haven't seen it yet",
            speaker="spk0",
            source_text="Team Refurb if you haven't seen it yet",
        ),
    ]
    merged = merge_clauses(segments)
    assert merged[0].text == "it is called Team Refurb"
    assert merged[1].text == "if you haven't seen it yet"
    assert merged[0].speaker == "spk0"
    assert merged[1].speaker == "spk0"


def test_words_keep_the_name_and_start_a_new_breath() -> None:
    words = [
        (5.04, 5.26, "It's"),
        (5.26, 5.52, "called"),
        (5.52, 6.02, "team"),
        (6.02, 6.54, "refurb"),
        (6.54, 7.00, "If"),
        (7.00, 7.14, "you"),
        (7.14, 7.32, "haven't"),
        (7.32, 7.48, "seen"),
        (7.48, 7.62, "it"),
        (7.62, 7.76, "yet."),
    ]
    segments = segments_from_words(words)
    assert segments[0].text == "It's called team refurb"
    assert segments[1].text == "If you haven't seen it yet."
    assert "team refurb" not in segments[1].text


def test_pause_does_not_steal_the_name() -> None:
    words = [
        (0.0, 0.4, "It's"),
        (0.4, 0.8, "called"),
        (1.4, 1.8, "Team"),
        (1.8, 2.3, "Refurb."),
        (2.8, 3.2, "Look"),
        (3.2, 3.6, "carefully."),
    ]
    segments = segments_from_words(words)
    assert segments[0].text == "It's called Team Refurb."
    assert segments[1].text == "Look carefully."


def test_split_sentences_keeps_a_name_with_its_cue() -> None:
    segments = [
        TranscriptSegment(
            0.0,
            8.0,
            "It's called. Team Refurb. Go check it out.",
            speaker="spk0",
            source_text="It's called. Team Refurb. Go check it out.",
        )
    ]
    pieces = split_sentences(segments)
    assert pieces[0].text == "It's called. Team Refurb."
    assert pieces[1].text == "Go check it out."


def test_a_new_sentence_starts_without_a_period() -> None:
    words = [
        (2.7, 3.1, "We"),
        (3.1, 3.4, "just"),
        (3.4, 3.8, "launched"),
        (3.8, 4.8, "channel"),
        (5.0, 5.3, "It's"),
        (5.3, 5.6, "called"),
        (5.6, 6.0, "team"),
        (6.0, 6.5, "refurb"),
        (6.5, 6.8, "if"),
        (6.8, 7.2, "you"),
        (7.2, 7.6, "haven't"),
        (7.6, 8.0, "yet"),
        (8.0, 8.2, "Go"),
        (8.2, 8.4, "check"),
        (8.4, 8.5, "it"),
        (8.5, 8.8, "out"),
    ]
    segments = segments_from_words(words)
    assert [segment.text for segment in segments] == [
        "We just launched channel",
        "It's called team refurb",
        "if you haven't yet",
        "Go check it out",
    ]


def test_lowercase_imperatives_still_split_the_line() -> None:
    text = (
        "Go check it out hit the subscribe button because we're gonna post some awesome stuff "
        "there that you are not gonna want to miss All right, please go subscribe to the channel, please"
    )
    words = []
    cursor = 0.0
    for token in text.split():
        words.append((cursor, cursor + 0.3, token))
        cursor += 0.32
    segments = segments_from_words(words)
    assert segments[0].text == "Go check it out"
    assert segments[1].text.startswith("hit the subscribe")
    assert segments[1].text.endswith("to miss")
    assert segments[2].text == "All right,"
    assert segments[3].text.startswith("please go subscribe")


def test_mid_sentence_that_stays_lowercase() -> None:
    words = [
        (8.4, 8.8, "Hit"),
        (8.8, 9.2, "the"),
        (9.2, 9.8, "button"),
        (9.8, 11.2, "there"),
        (11.2, 11.6, "That"),
        (11.6, 12.0, "you"),
        (12.0, 13.0, "miss."),
    ]
    segments = segments_from_words(words)
    assert "that you" in segments[0].text
    assert "That" not in segments[0].text


def test_polish_fixes_spoken_french() -> None:
    assert polish_spoken("des trucs génials", "", "fr") == "des trucs géniaux"
    assert polish_spoken("Ça va être mes amis.", "It's gonna be all my friends.", "fr") == (
        "Ça va être tous mes amis."
    )
    assert polish_spoken("Va voir.", "Go check it out", "fr") == "Allez voir."
    assert polish_spoken("Va voir.", "Look at this", "fr") == "Va voir."


def test_merge_does_not_hand_the_next_line_to_the_same_voice() -> None:
    segments = [
        TranscriptSegment(12.9, 13.7, "All right,", speaker="spk0", source_text="All right,"),
        TranscriptSegment(
            13.7,
            16.2,
            "please go subscribe to the channel,",
            speaker="spk0",
            source_text="please go subscribe to the channel,",
        ),
    ]
    merged = merge_clauses(segments)
    assert len(merged) == 2
    assert merged[1].text.startswith("please")


def test_pack_joins_short_lines_of_one_speaker() -> None:
    segments = [
        TranscriptSegment(0.0, 2.0, "Bonne nouvelle.", speaker="spk0", source_text="News."),
        TranscriptSegment(2.1, 4.8, "Nous venons de lancer une chaîne.", speaker="spk0", source_text="We launched."),
        TranscriptSegment(4.8, 6.5, "Ça s'appelle team refurb", speaker="spk0", source_text="called team refurb"),
        TranscriptSegment(14.0, 17.0, "Allez vous abonner.", speaker="spk1", source_text="Please subscribe."),
    ]
    packed = pack_lines(segments)
    assert len(packed) == 2
    assert "team refurb" in packed[0].text
    assert packed[0].text.endswith("team refurb") or "team refurb" in packed[0].text
    assert packed[1].speaker == "spk1"
    assert packed[1].text == "Allez vous abonner."


def test_merge_keeps_a_speaker_change() -> None:
    segments = [
        TranscriptSegment(0.0, 1.0, "it is called", speaker="spk0"),
        TranscriptSegment(1.0, 2.0, "the other person.", speaker="spk1"),
    ]
    merged = merge_clauses(segments)
    assert [segment.speaker for segment in merged] == ["spk0", "spk1"]


def test_called_name_is_not_translated() -> None:
    segments = [
        TranscriptSegment(
            0.0,
            6.0,
            "we are going to launch a new channel, it is called Team Refurb.",
            speaker="spk0",
            source_text="we are going to launch a new channel, it is called Team Refurb.",
        )
    ]

    def translate(text: str) -> str:
        assert "Team Refurb" not in text
        return "nous allons lancer une nouvelle chaîne, il s'appelle"

    updated = preserve_names(segments, translate)
    assert updated[0].text.endswith("Team Refurb.")
    assert updated[0].source_text.endswith("Team Refurb.")


def test_speech_after_the_name_is_translated() -> None:
    segments = [
        TranscriptSegment(
            0.0,
            12.0,
            "It's called team refurb if you haven't seen it yet Go check it out",
            speaker="spk0",
            source_text="It's called team refurb if you haven't seen it yet Go check it out",
        )
    ]

    def translate(text: str) -> str:
        assert "team refurb" not in text
        if text.lower().startswith("it's called"):
            return "Ça s'appelle"
        return "si vous ne l'avez pas encore vu, allez voir"

    updated = preserve_names(segments, translate)
    assert "team refurb" in updated[0].text
    assert updated[0].text.endswith("allez voir")
    assert "if you haven't" not in updated[0].text


def test_name_on_the_next_line_stays_verbatim() -> None:
    segments = [
        TranscriptSegment(0.0, 5.0, "it is called", speaker="spk0", source_text="it is called"),
        TranscriptSegment(5.0, 6.0, "Team Refurb.", speaker="spk0", source_text="Team Refurb."),
    ]

    def translate(text: str) -> str:
        assert text == "it is called"
        return "il s'appelle"

    updated = preserve_names(segments, translate)
    assert updated[0].text == "il s'appelle"
    assert updated[1].text == "Team Refurb."


def test_french_variety_follows_the_accent() -> None:
    assert apply_french_variety("On se voit en week-end.", "fr-CA") == "On se voit en fin de semaine."
    assert apply_french_variety("Envoie un courriel.", "fr-FR") == "Envoie un e-mail."
    assert apply_french_variety("Il en a soixante-dix.", "fr-BE") == "Il en a septante."
    assert apply_french_variety("Ça fait quatre-vingt-dix.", "fr-CH") == "Ça fait nonante."
    assert apply_french_variety("Ça fait quatre-vingts.", "fr-CH") == "Ça fait huitante."
    assert apply_french_variety("Ça fait quatre-vingt-un.", "fr-CH") == "Ça fait quatre-vingt-un."
    assert apply_french_variety("Week-end", "fr-CA") == "Fin de semaine"


def test_french_accent_defaults_to_quebec_and_rejects_unknown() -> None:
    assert resolve_accent("fr", None) == "fr-CA"
    assert resolve_accent("es", "fr-FR") is None
    assert ProjectCreate(name="Demo").target_accent == "fr-CA"
    assert ProjectCreate(name="Demo", target_language="es", target_accent="fr-CA").target_accent is None
    assert ProjectCreate(name="Demo", target_accent="fr-fr").target_accent == "fr-FR"
    with pytest.raises(ValidationError):
        ProjectCreate(name="Demo", target_accent="fr-US")
