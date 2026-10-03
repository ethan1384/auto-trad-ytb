"""Local pipeline: faster-whisper, Argos Translate, OmniVoice cloning, ffmpeg.

Each detected speaker is dubbed with a clone of their own voice. The original
picture is kept. Render keeps the original music and room tone under the new
voice, and burns translated subtitles.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from app.accents import resolve_accent
from app.config import Settings, get_settings
from app.providers.base import (
    LipSyncProvider,
    LipSyncResult,
    MediaRenderer,
    RenderResult,
    RewriteProvider,
    RewriteResult,
    SynthesisResult,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
    TranslationProvider,
    TranslationResult,
    VoiceSynthesisProvider,
    replace_segment_text,
)
from app.providers.phrasing import (
    apply_french_variety,
    merge_clauses,
    pack_lines,
    polish_spoken,
    preserve_names,
    segments_from_words,
    split_sentences,
)
from app.providers.expressions import ExpressionRewriter
from app.providers.speakers import assign_speakers, speaker_ids, write_speaker_refs
from app.providers.stems import extract_soundtrack, mix_dub_over_background, separate_accompaniment
from app.providers.voice_clone import speaking_duration

# Past this, time-stretch turns the cloned line into noise.
MAX_DUB_SPEED = 1.25
# Each timeline piece is its own small ffmpeg process, independent of the others.
TIMELINE_WORKERS = max(1, min(8, os.cpu_count() or 1))
from app.providers.ffmpeg_tools import (
    DUB_SAMPLE_RATE,
    atempo_chain,
    concat_wavs,
    fit_wav,
    probe_duration,
    run_cmd,
    write_silence,
)
from app.storage import StorageClient

log = logging.getLogger(__name__)


def normalize_lang(code: str | None) -> str:
    if not code:
        return "en"
    token = code.strip().lower().replace("_", "-").split("-", 1)[0]
    return token or "en"


class LocalTranscriptionProvider(TranscriptionProvider):
    def __init__(self, storage: StorageClient, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings

    def transcribe(self, audio_key: str, language: str | None = None) -> TranscriptResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed in the worker") from exc

        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "audio.wav"
            self.storage.download(audio_key, wav)
            model = _whisper_model(self.settings)
            # Detect the spoken language. Forcing the project language made Whisper
            # rewrite French speech as broken English, which the translator then mangled.
            rows = None
            info = None
            last_error: Exception | None = None
            for vad_filter, word_timestamps in ((True, True), (False, True), (False, False)):
                try:
                    iterator, info = model.transcribe(
                        str(wav),
                        vad_filter=vad_filter,
                        word_timestamps=word_timestamps,
                        temperature=0.0,
                        beam_size=5,
                        condition_on_previous_text=False,
                    )
                    rows = list(iterator)
                    break
                except Exception as exc:
                    last_error = exc
            if rows is None or info is None:
                raise RuntimeError("Transcription failed") from last_error

            words = _whisper_words(rows)
            if words:
                segments = segments_from_words(words)
            else:
                segments = [
                    TranscriptSegment(float(row.start), float(row.end), row.text.strip(), source_text=row.text.strip())
                    for row in rows
                    if row.text and row.text.strip()
                ]
            segments = split_sentences(segments)
            if not segments:
                raise RuntimeError("No speech detected in the source video")
            assign_speakers(wav, segments, words)
            segments = merge_clauses(segments)
            detected = getattr(info, "language", None) or normalize_lang(language)
        return TranscriptResult(
            language=str(detected),
            segments=segments,
            raw_text=" ".join(segment.text for segment in segments),
        )


def _whisper_words(rows: list) -> list[tuple[float, float, str]]:
    words: list[tuple[float, float, str]] = []
    for row in rows:
        for token in getattr(row, "words", None) or []:
            label = (getattr(token, "word", "") or "").strip()
            start = getattr(token, "start", None)
            end = getattr(token, "end", None)
            if not label or start is None or end is None:
                continue
            words.append((float(start), float(end), label))
    return words


# 4, 8, and 12 threads give the same words and timings. Past 8 there is no gain.
WHISPER_CPU_THREADS = max(4, min(8, os.cpu_count() or 4))
_whisper_models: dict[str, object] = {}
_whisper_lock = threading.Lock()


def _whisper_model(settings: Settings):
    """One loaded model per worker process. Reloading it cost about a second per job."""
    with _whisper_lock:
        model = _whisper_models.get(settings.whisper_model)
        if model is None:
            model = _load_whisper(settings.whisper_model, settings.whisper_device, settings.whisper_compute_type)
            _whisper_models[settings.whisper_model] = model
        return model


def _load_whisper(name: str, device: str = "cpu", compute_type: str = ""):
    from faster_whisper import WhisperModel

    if device != "cpu":
        try:
            return WhisperModel(name, device=device, compute_type=compute_type or "float16")
        except Exception as exc:  # noqa: BLE001 — missing CUDA libs must not stop the dub
            log.warning("Whisper could not load on %s (%s); transcribing on CPU", device, exc)
    try:
        return WhisperModel(
            name, device="cpu", compute_type=compute_type or "int8", cpu_threads=WHISPER_CPU_THREADS
        )
    except Exception:
        return WhisperModel(name, device="cpu", compute_type="default", cpu_threads=WHISPER_CPU_THREADS)


class LocalTranslationProvider(TranslationProvider):
    def translate(
        self, transcript: TranscriptResult, source_language: str, target_language: str
    ) -> TranslationResult:
        source = normalize_lang(transcript.language or source_language)
        target = normalize_lang(target_language)
        if source == target:
            segments = [replace_segment_text(segment, segment.text.strip()) for segment in transcript.segments]
        else:
            translate = _argos_translate(source, target)
            segments = preserve_names(transcript.segments, translate)
        return TranslationResult(
            source_language=source,
            target_language=target,
            segments=segments,
            raw_text=" ".join(segment.text for segment in segments if segment.text),
        )


def _argos_translate(source: str, target: str):
    try:
        import argostranslate.package
        import argostranslate.translate
    except ImportError as exc:
        raise RuntimeError("Argos Translate is not installed in the worker") from exc

    if source == target:
        return lambda text: text

    _ensure_argos_pair(source, target, argostranslate.package, argostranslate.translate)

    def _run(text: str) -> str:
        return argostranslate.translate.translate(text, source, target)

    return _run


def _ensure_argos_pair(source: str, target: str, package_mod, translate_mod) -> None:
    languages = translate_mod.get_installed_languages()
    from_lang = next((lang for lang in languages if lang.code == source), None)
    to_lang = next((lang for lang in languages if lang.code == target), None)
    if from_lang and to_lang and from_lang.get_translation(to_lang):
        return

    package_mod.update_package_index()
    package = next(
        (item for item in package_mod.get_available_packages() if item.from_code == source and item.to_code == target),
        None,
    )
    if package is None:
        raise RuntimeError(f"No Argos translation package for {source} → {target}")
    package_mod.install_from_path(package.download())


class LocalRewriteProvider(RewriteProvider):
    def __init__(
        self,
        settings: Settings | None = None,
        rewriter: ExpressionRewriter | None = None,
    ) -> None:
        if rewriter is not None:
            self.rewriter = rewriter
        else:
            resolved = settings or get_settings()
            self.rewriter = ExpressionRewriter(resolved.ollama_base_url, resolved.rewrite_model)

    def rewrite(
        self,
        translation: TranslationResult,
        target_language: str,
        accent: str | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> RewriteResult:
        lang = normalize_lang(target_language)
        chosen = resolve_accent(lang, accent)
        source_lang = normalize_lang(translation.source_language)
        lines, rewritten = self.rewriter.apply(
            translation.segments, source_lang, lang, progress=progress
        )
        segments = [
            replace_segment_text(
                segment,
                apply_french_variety(
                    polish_spoken(segment.text, segment.source_text or "", lang),
                    chosen,
                ),
            )
            for segment in lines
        ]
        # The clone sample has to be the original lines. Packed phrases include
        # the pauses between them, and that mismatch drops the voice likeness.
        reference_segments = [
            TranscriptSegment(
                segment.start,
                segment.end,
                segment.source_text or segment.text,
                speaker=segment.speaker,
                source_text=segment.source_text or segment.text,
            )
            for segment in segments
            if (segment.source_text or segment.text).strip()
        ]
        segments = pack_lines(segments)
        return RewriteResult(
            text=" ".join(segment.text for segment in segments if segment.text),
            segments=segments,
            meta={
                "provider": self.rewriter.model if rewritten else "passthrough",
                "lang": lang,
                "accent": chosen,
                "rewritten_lines": rewritten,
                "reference_segments": reference_segments,
            },
        )


class LocalVoiceSynthesisProvider(VoiceSynthesisProvider):
    def __init__(self, storage: StorageClient) -> None:
        self.storage = storage

    def synthesize(
        self,
        script: RewriteResult,
        voice_ref_key: str | None,
        target_language: str,
        output_key: str,
        accent: str | None = None,
        stop: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> SynthesisResult:
        if not any(segment.text.strip() for segment in script.segments):
            raise RuntimeError("Translated script is empty")
        # Accent only changes a few French words. The voice is always the
        # original speaker. A catalog voice is not a fallback.
        if not voice_ref_key:
            raise RuntimeError(
                "Voice cloning needs the original soundtrack. "
                "Refusing to dub with a catalog voice."
            )
        chosen = resolve_accent(target_language, accent)
        return self._synthesize_cloned(
            script,
            voice_ref_key,
            target_language,
            output_key,
            chosen,
            stop=stop,
            progress=progress,
        )

    def _synthesize_cloned(
        self,
        script: RewriteResult,
        voice_ref_key: str,
        target_language: str,
        output_key: str,
        accent: str | None = None,
        stop: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> SynthesisResult:
        from app.providers.voice_clone import CloneLine, clear_prompts, write_cloned_lines

        clear_prompts()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            self.storage.download(voice_ref_key, source)
            refs = write_speaker_refs(source, _reference_segments(script), root / "refs")

            lang = normalize_lang(target_language)
            jobs: list[CloneLine] = []
            for index, segment in enumerate(script.segments):
                text = segment.text.strip()
                if not text:
                    continue
                speaker = segment.speaker or "spk0"
                ref = refs.get(speaker) or next(iter(refs.values()))
                slot = max(segment.end - segment.start, 0.35)
                jobs.append(
                    CloneLine(
                        text=text,
                        ref_audio=ref.wav_path,
                        ref_text=ref.ref_text,
                        dest=root / f"line-{index}.wav",
                        duration=speaking_duration(text, slot),
                    )
                )
            write_cloned_lines(jobs, language=lang, stop=stop, progress=progress)

            def speak(segment: TranscriptSegment, dest: Path, slot: float) -> None:
                del segment, slot
                if not dest.is_file():
                    raise RuntimeError("Cloned line was not rendered")

            rendered = self._lay_timeline(script, speak, root)
            self.storage.upload_path(output_key, rendered, "audio/wav")
            duration = probe_duration(rendered)

        speakers = speaker_ids(script.segments) or sorted(refs)
        return SynthesisResult(
            audio_key=output_key,
            duration_seconds=duration,
            meta={"provider": "omnivoice", "voice_clone": True, "speakers": speakers, "accent": accent},
        )

    def _lay_timeline(self, script: RewriteResult, speak, root: Path) -> Path:
        """Plan every piece in order, then run the independent ffmpeg calls together."""
        spoken_lines: dict[int, Path] = {}
        for index, segment in enumerate(script.segments):
            if segment.text.strip():
                spoken = root / f"line-{index}.wav"
                speak(segment, spoken, max(segment.end - segment.start, 0.35))
                spoken_lines[index] = spoken

        with ThreadPoolExecutor(max_workers=TIMELINE_WORKERS) as pool:
            spoken_durations = dict(zip(spoken_lines, pool.map(probe_duration, spoken_lines.values()), strict=True))
            pieces: list[Path] = []
            writes: list[Callable[[], None]] = []
            cursor = 0.0
            for index, segment in enumerate(script.segments):
                start = max(segment.start, cursor)
                slot = max(segment.end - segment.start, 0.35)
                gap = start - cursor
                if gap > 0.05:
                    silence = root / f"gap-{index}.wav"
                    writes.append(partial(write_silence, silence, gap))
                    pieces.append(silence)
                if index in spoken_lines:
                    spoken_dur = spoken_durations[index]
                    if spoken_dur > slot * MAX_DUB_SPEED:
                        slot = spoken_dur / MAX_DUB_SPEED
                    fitted = root / f"fit-{index}.wav"
                    writes.append(partial(fit_wav, spoken_lines[index], fitted, slot, duration=spoken_dur))
                    pieces.append(fitted)
                else:
                    silence = root / f"empty-{index}.wav"
                    writes.append(partial(write_silence, silence, slot))
                    pieces.append(silence)
                cursor = start + slot
            list(pool.map(lambda write: write(), writes))

        rendered = root / "voice.wav"
        concat_wavs(pieces, rendered)
        return rendered


def _reference_segments(script: RewriteResult) -> list[TranscriptSegment]:
    stored = script.meta.get("reference_segments")
    if isinstance(stored, list) and stored:
        return stored
    return script.segments


class LocalLipSyncProvider(LipSyncProvider):
    def __init__(self, storage: StorageClient) -> None:
        self.storage = storage

    def sync(self, video_key: str, audio_key: str, output_key: str) -> LipSyncResult:
        del audio_key
        self.storage.copy_object(video_key, output_key, "video/mp4")
        return LipSyncResult(
            video_key=output_key,
            meta={
                "provider": "passthrough",
                "note": "The original picture is kept. Translated audio and subtitles are applied at render.",
            },
        )


class LocalMediaRenderer(MediaRenderer):
    def __init__(self, storage: StorageClient) -> None:
        self.storage = storage

    def extract_audio(self, video_key: str, output_key: str, voice_key: str | None = None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.mp4"
            self.storage.download(video_key, src)
            # Whisper and the speaker model want 16 kHz. The clone does not:
            # OmniVoice listens at 24 kHz, and a 16 kHz sample has already lost
            # the part of the voice that makes it recognizable.
            speech = Path(tmp) / "speech.wav"
            _extract_wav(src, speech, 16000)
            self.storage.upload_path(output_key, speech, "audio/wav")
            if voice_key:
                voice = Path(tmp) / "voice.wav"
                _extract_wav(src, voice, DUB_SAMPLE_RATE)
                self.storage.upload_path(voice_key, voice, "audio/wav")
        return output_key

    def align_audio(self, audio_key: str, target_duration: float, output_key: str) -> str:
        target = max(float(target_duration), 0.2)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.wav"
            dest = Path(tmp) / "out.wav"
            self.storage.download(audio_key, src)
            current = probe_duration(src)
            if abs(current - target) / target < 0.04:
                self.storage.copy_object(audio_key, output_key, "audio/wav")
                return output_key
            speed = current / target
            if speed > MAX_DUB_SPEED:
                speed = MAX_DUB_SPEED
            run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(src),
                    "-af",
                    f"{atempo_chain(speed)},apad=whole_dur={target:.3f},atrim=0:{target:.3f}",
                    "-ac",
                    "1",
                    "-ar",
                    str(DUB_SAMPLE_RATE),
                    "-c:a",
                    "pcm_s16le",
                    str(dest),
                ]
            )
            self.storage.upload_path(output_key, dest, "audio/wav")
        return output_key

    def render(
        self, video_key: str, audio_key: str, output_key: str, subtitle_text: str | None = None
    ) -> RenderResult:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "in.mp4"
            audio = root / "in.wav"
            out = root / "out.mp4"
            self.storage.download(video_key, video)
            self.storage.download(audio_key, audio)
            soundtrack = _with_original_ambience(video, audio, root)
            burned = False
            if subtitle_text and subtitle_text.strip():
                (root / "subs.srt").write_text(subtitle_text, encoding="utf-8")
                try:
                    _encode(video, soundtrack, out, root, burn=True)
                    burned = True
                except RuntimeError:
                    _encode(video, soundtrack, out, root, burn=False)
            else:
                _encode(video, soundtrack, out, root, burn=False)
            self.storage.upload_path(output_key, out, "video/mp4")

        subtitle_key = None
        if subtitle_text and subtitle_text.strip():
            subtitle_key = output_key.rsplit(".", 1)[0] + ".srt"
            self.storage.put_bytes(subtitle_key, subtitle_text.encode("utf-8"), "application/x-subrip")
        return RenderResult(
            video_key=output_key,
            subtitle_key=subtitle_key,
            meta={
                "provider": "ffmpeg",
                "subtitles": "burned-in" if burned else "sidecar",
                "background": "kept",
            },
        )


def _with_original_ambience(video: Path, voice: Path, root: Path) -> Path:
    """Mix music and other non-voice sounds from the picture under the dub."""
    original = root / "original.wav"
    try:
        extract_soundtrack(video, original)
    except RuntimeError as exc:
        raise RuntimeError(f"Could not read the original soundtrack: {exc}") from exc
    background = root / "background.wav"
    log.info("separating vocals from the original soundtrack")
    try:
        separate_accompaniment(original, background, root / "separated")
    except RuntimeError as exc:
        raise RuntimeError(f"Background separation failed: {exc}") from exc
    mixed = root / "mix.wav"
    mix_dub_over_background(background, voice, mixed)
    return mixed


def _extract_wav(src: Path, dest: Path, sample_rate: int) -> None:
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )


def _encode(video: Path, audio: Path, out: Path, cwd: Path, burn: bool) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
    ]
    if burn:
        cmd += [
            "-vf",
            "subtitles=subs.srt:force_style='FontName=DejaVu Sans,FontSize=22,Outline=2,MarginV=90'",
        ]
    # The dub ends on the last spoken line, often a little before the picture.
    # Padding the soundtrack makes -shortest follow the video, so those final
    # frames stay. Without the pad, AAC priming also clips the tail.
    cmd += [
        "-af",
        "apad",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-shortest",
        str(out),
    ]
    run_cmd(cmd, cwd=cwd if burn else None)
