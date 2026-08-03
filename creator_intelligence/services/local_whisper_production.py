from creator_intelligence.services.local_whisper_transcripts import LocalWhisperTranscriptService
from creator_intelligence.services.transcript_production import TranscriptProductionMixin


class LocalWhisperProductionService(
    TranscriptProductionMixin,
    LocalWhisperTranscriptService,
):
    """Local Whisper transcript service with clip review and production handoff."""

    pass
