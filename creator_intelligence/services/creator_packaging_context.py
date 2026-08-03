from __future__ import annotations

from typing import Any

from creator_intelligence.services.creator_packaging_intelligence import (
    CreatorPackagingIntelligenceMixin,
)


class CreatorPackagingContextMixin(CreatorPackagingIntelligenceMixin):
    """Adds transcript-level context to local creator packaging analysis."""

    def analyze_clip_candidate(self, clip_id: int) -> dict[str, Any]:
        frame = self.db.frame(
            "SELECT transcript_id FROM transcript_clip_candidates WHERE id=?",
            (int(clip_id),),
        )
        if frame.empty:
            raise KeyError(clip_id)

        transcript_id = int(frame.iloc[0]["transcript_id"])
        transcript = self.transcript(transcript_id)
        self._packaging_context_title = str(
            transcript.get("title")
            or transcript.get("display_name")
            or transcript.get("media_asset")
            or ""
        ).strip()
        try:
            return super().analyze_clip_candidate(clip_id)
        finally:
            self._packaging_context_title = ""

    def _build_creator_package(
        self,
        text: str,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        context = str(getattr(self, "_packaging_context_title", "") or "").strip()
        contextual_text = f"{context} {text}".strip()
        return super()._build_creator_package(contextual_text, analysis)
