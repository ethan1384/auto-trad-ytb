"""Does Whisper / sherpa diarization give the same answer with more threads, and how fast?

    services/api/.venv/bin/python scripts/bench_transcribe_threads.py AUDIO_16K.wav
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))


def whisper_words(wav: Path, threads: int) -> tuple[list, float, float]:
    from faster_whisper import WhisperModel

    started = time.perf_counter()
    model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=threads)
    loaded = time.perf_counter()
    iterator, _info = model.transcribe(
        str(wav), vad_filter=True, word_timestamps=True, temperature=0.0, beam_size=5,
        condition_on_previous_text=False,
    )
    rows = list(iterator)
    done = time.perf_counter()
    words = [(w.start, w.end, w.word) for row in rows for w in (row.words or [])]
    return words, loaded - started, done - loaded


def diarize(samples: list[float], rate: int, threads: int) -> tuple[list, float]:
    import sherpa_onnx

    from app.providers import speaker_diarize as sd

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(sd._segmentation_path())),
            num_threads=threads, debug=False, provider="cpu",
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(sd._embedding_path()), num_threads=threads, debug=False, provider="cpu",
        ),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=sd.CLUSTER_THRESHOLD),
        min_duration_on=sd.MIN_DURATION_ON,
        min_duration_off=sd.MIN_DURATION_OFF,
    )
    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    started = time.perf_counter()
    result = diarizer.process(samples).sort_by_start_time()
    return [(r.start, r.end, r.speaker) for r in result], time.perf_counter() - started


def main() -> None:
    from app.providers.speakers import read_pcm16

    wav = Path(sys.argv[1])
    samples, rate = read_pcm16(wav)

    reference_words = None
    for threads in (4, 8, 12):
        words, load, run = whisper_words(wav, threads)
        same = reference_words is None or words == reference_words
        reference_words = reference_words or words
        print(f"whisper cpu_threads={threads:<2} load={load:.2f}s transcribe={run:.2f}s words={len(words)} same_as_4={same}")

    reference_turns = None
    for threads in (2, 4, 8):
        turns, seconds = diarize(samples, rate, threads)
        same = reference_turns is None or turns == reference_turns
        reference_turns = reference_turns or turns
        print(f"diarize num_threads={threads:<2} process={seconds:.2f}s turns={len(turns)} same_as_2={same}")

    # Today: whisper then diarization, one after the other. Overlapped: both at once.
    started = time.perf_counter()
    whisper_words(wav, 4)
    diarize(samples, rate, 2)
    sequential = time.perf_counter() - started

    box: dict = {}
    started = time.perf_counter()
    worker = threading.Thread(target=lambda: box.setdefault("turns", diarize(samples, rate, 2)))
    worker.start()
    words, _load, _run = whisper_words(wav, 4)
    worker.join()
    overlapped = time.perf_counter() - started
    print(
        f"whisper(4)+diarize(2): sequential={sequential:.2f}s overlapped={overlapped:.2f}s "
        f"same_words={words == reference_words} same_turns={box['turns'][0] == reference_turns}"
    )


if __name__ == "__main__":
    main()
