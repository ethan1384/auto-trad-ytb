from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.providers.base import (
    LipSyncProvider,
    MediaRenderer,
    RewriteProvider,
    TranscriptionProvider,
    TranslationProvider,
    VoiceSynthesisProvider,
)
from app.providers.mock import (
    MockLipSyncProvider,
    MockMediaRenderer,
    MockRewriteProvider,
    MockTranscriptionProvider,
    MockTranslationProvider,
    MockVoiceSynthesisProvider,
)
from app.providers.real import (
    ArgosTranslationProvider,
    FasterWhisperTranscriptionProvider,
    FfmpegMediaRenderer,
    DisabledLipSyncProvider,
    OmniVoiceSynthesisProvider,
    VllmRewriteProvider,
)
from app.storage import StorageClient


@dataclass
class ProviderBundle:
    transcription: TranscriptionProvider
    translation: TranslationProvider
    rewrite: RewriteProvider
    voice: VoiceSynthesisProvider
    lipsync: LipSyncProvider
    media: MediaRenderer


def get_providers(settings: Settings | None = None, storage: StorageClient | None = None) -> ProviderBundle:
    settings = settings or get_settings()
    storage = storage or StorageClient(settings)
    mode = settings.provider_mode.lower()

    if mode == "local":
        from app.providers.local import (
            LocalLipSyncProvider,
            LocalMediaRenderer,
            LocalRewriteProvider,
            LocalTranscriptionProvider,
            LocalTranslationProvider,
            LocalVoiceSynthesisProvider,
        )

        return ProviderBundle(
            transcription=LocalTranscriptionProvider(storage, settings),
            translation=LocalTranslationProvider(),
            rewrite=LocalRewriteProvider(settings),
            voice=LocalVoiceSynthesisProvider(storage),
            lipsync=LocalLipSyncProvider(storage),
            media=LocalMediaRenderer(storage),
        )

    if mode == "real":
        return ProviderBundle(
            transcription=FasterWhisperTranscriptionProvider(),
            translation=ArgosTranslationProvider(),
            rewrite=VllmRewriteProvider(),
            voice=OmniVoiceSynthesisProvider(),
            lipsync=DisabledLipSyncProvider(),
            media=FfmpegMediaRenderer(),
        )

    return ProviderBundle(
        transcription=MockTranscriptionProvider(),
        translation=MockTranslationProvider(),
        rewrite=MockRewriteProvider(),
        voice=MockVoiceSynthesisProvider(storage),
        lipsync=MockLipSyncProvider(storage),
        media=MockMediaRenderer(storage),
    )
