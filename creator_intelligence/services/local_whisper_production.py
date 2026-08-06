from creator_intelligence.services.local_whisper_transcripts import (
    LocalWhisperTranscriptService,
)
from creator_intelligence.services.packaging import (
    CreatorPackagingContextMixin,
    CreatorPackagingQueriesMixin,
)
from creator_intelligence.services.transcript_production import TranscriptProductionMixin


class LocalWhisperProductionService(
    CreatorPackagingQueriesMixin,
    CreatorPackagingContextMixin,
    TranscriptProductionMixin,
    LocalWhisperTranscriptService,
):
    """Local transcript service with packaging intelligence and production handoff."""

    pass
