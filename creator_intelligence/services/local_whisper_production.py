from creator_intelligence.services.creator_packaging_intelligence import (
    CreatorPackagingIntelligenceMixin,
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
    CreatorPackagingIntelligenceMixin,
    TranscriptProductionMixin,
    LocalWhisperTranscriptService,
):
    """Local transcript service with packaging intelligence and production handoff."""

    pass
