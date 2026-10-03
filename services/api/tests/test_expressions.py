from app.providers.base import TranscriptSegment, TranslationResult
from app.providers.expressions import ExpressionRewriter, accept_spoken
from app.providers.local import LocalRewriteProvider
from app.providers.phrasing import protected_name


def test_protected_name_is_the_short_name() -> None:
    assert protected_name("it is called Team Refurb.") == "Team Refurb"
    assert protected_name("Look carefully.") == ""


def test_accepts_a_short_spoken_line() -> None:
    spoken = accept_spoken("It's no big deal.", "It's not the sea to drink.", "C'est pas la mer à boire.")
    assert spoken == "It's no big deal."


def test_rejects_an_explanation() -> None:
    raw = (
        "This idiom means the task is easy and you should not worry about it "
        "because the amount of work is actually quite small."
    )
    assert accept_spoken(raw, "It's not the sea to drink.", "C'est pas la mer à boire.") is None


def test_rejects_a_line_that_drops_the_name() -> None:
    source = "This channel is called Team Refurb."
    draft = "Cette chaîne s'appelle Team Refurb."
    assert accept_spoken("Cette chaîne s'appelle Équipe Rénov.", draft, source) is None


def test_rewrite_replaces_the_literal_draft() -> None:
    def complete(prompt: str) -> str:
        assert "C'est pas la mer à boire." in prompt
        assert "It's not the sea to drink." not in prompt
        assert "Source language: French" in prompt
        assert "Target language: English" in prompt
        return "It's no big deal."

    rewriter = ExpressionRewriter(complete=complete)
    segments = [
        TranscriptSegment(
            0.0,
            1.2,
            "It's not the sea to drink.",
            speaker="spk0",
            source_text="C'est pas la mer à boire.",
        )
    ]
    updated, count = rewriter.apply(segments, "fr", "en")
    assert count == 1
    assert updated[0].text == "It's no big deal."
    assert updated[0].source_text == "C'est pas la mer à boire."
    assert updated[0].speaker == "spk0"
    assert updated[0].start == 0.0


def test_rewrite_prompt_includes_neighboring_lines() -> None:
    seen: list[str] = []

    def complete(prompt: str) -> str:
        seen.append(prompt)
        return "À bientôt."

    rewriter = ExpressionRewriter(complete=complete)
    segments = [
        TranscriptSegment(0.0, 1.0, "La vidéo est en ligne.", source_text="The video is live."),
        TranscriptSegment(1.0, 2.0, "YouTube te vois", source_text="YouTube see you"),
        TranscriptSegment(2.0, 3.0, "Merci.", source_text="Thanks."),
    ]
    updated, count = rewriter.apply(segments, "en", "fr")
    assert count == 3
    assert "Previous line: The video is live." in seen[1]
    assert "Line: YouTube see you" in seen[1]
    assert "Next line: Thanks." in seen[1]
    assert "YouTube te vois" not in seen[1]
    assert updated[1].text == "À bientôt."


def test_rewrite_reports_each_line() -> None:
    seen: list[tuple[int, int]] = []

    def complete(_prompt: str) -> str:
        return "It's no big deal."

    rewriter = ExpressionRewriter(complete=complete)
    segments = [
        TranscriptSegment(0.0, 1.0, "It's not the sea to drink.", source_text="C'est pas la mer à boire."),
        TranscriptSegment(1.0, 2.0, "Look.", source_text="Regarde."),
    ]
    updated, count = rewriter.apply(segments, "fr", "en", progress=lambda done, total: seen.append((done, total)))
    assert count == 2
    assert updated[0].text == "It's no big deal."
    assert seen == [(0, 2), (1, 2), (2, 2)]


def test_rewrite_keeps_the_draft_when_the_model_fails() -> None:
    def complete(_prompt: str) -> str:
        raise RuntimeError("down")

    rewriter = ExpressionRewriter(complete=complete)
    segments = [
        TranscriptSegment(0.0, 1.0, "It's not the sea to drink.", source_text="C'est pas la mer à boire."),
        TranscriptSegment(1.0, 2.0, "Look.", source_text="Regarde."),
    ]
    updated, count = rewriter.apply(segments, "fr", "en")
    assert count == 0
    assert updated[0].text == "It's not the sea to drink."
    assert updated[1].text == "Look."


def test_same_language_skips_the_model() -> None:
    def complete(_prompt: str) -> str:
        raise AssertionError("model should not be called")

    rewriter = ExpressionRewriter(complete=complete)
    segments = [TranscriptSegment(0.0, 1.0, "Déjà dit.", source_text="Déjà dit.")]
    updated, count = rewriter.apply(segments, "fr", "fr")
    assert count == 0
    assert updated[0].text == "Déjà dit."


def test_local_rewrite_applies_the_accent_after_the_model() -> None:
    def complete(_prompt: str) -> str:
        return "On se voit en fin de semaine."

    provider = LocalRewriteProvider(rewriter=ExpressionRewriter(complete=complete))
    translation = TranslationResult(
        source_language="en",
        target_language="fr",
        segments=[
            TranscriptSegment(
                0.0,
                1.5,
                "On se voit en fin de semaine.",
                speaker="spk1",
                source_text="See you on the weekend.",
            )
        ],
        raw_text="On se voit en fin de semaine.",
    )
    result = provider.rewrite(translation, "fr", accent="fr-FR")
    assert result.segments[0].text == "On se voit en week-end."
    assert result.segments[0].speaker == "spk1"
    assert result.meta["provider"] == "qwen3.8:27b"
    assert result.meta["rewritten_lines"] == 1
    assert result.meta["reference_segments"][0].text == "See you on the weekend."
