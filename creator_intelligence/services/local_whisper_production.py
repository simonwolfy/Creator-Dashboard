from creator_intelligence.services.creator_packaging_context import (
    CreatorPackagingContextMixin,
)
from creator_intelligence.services.creator_packaging_queries import (
    CreatorPackagingQueriesMixin,
)
from creator_intelligence.services.local_whisper_transcripts import (
    LocalWhisperTranscriptService,
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
