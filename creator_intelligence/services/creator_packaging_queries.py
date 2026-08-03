from __future__ import annotations


class CreatorPackagingQueriesMixin:
    """Read helpers for creator packaging data stored on clip candidates."""

    def clip_packaging(self, clip_id: int) -> dict:
        frame = self.db.frame(
            "SELECT * FROM transcript_clip_candidates WHERE id=?",
            (int(clip_id),),
        )
        if frame.empty:
            raise KeyError(clip_id)
        return frame.iloc[0].to_dict()
