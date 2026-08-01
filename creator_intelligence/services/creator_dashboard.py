from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DashboardSnapshot:
    total_content: int
    counts_by_type: dict[str, int]
    counts_by_status: dict[str, int]
    work_queue: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]
    upcoming: list[dict[str, Any]]


class CreatorDashboardService:
    """Builds the daily operating snapshot from the unified content library."""

    ACTIONABLE_STATUSES = (
        "Planned",
        "Recording",
        "Editing",
        "Waiting on editor",
        "Needs review",
        "Revision requested",
        "Ready to publish",
    )

    def __init__(self, db):
        self.db = db

    def snapshot(self, *, queue_limit: int = 12, recent_limit: int = 10) -> DashboardSnapshot:
        if not self.db.table_exists("content_items"):
            return DashboardSnapshot(0, {}, {}, [], [], [])

        counts_by_type = self._counts("content_type")
        counts_by_status = self._counts("status")
        total_content = sum(counts_by_type.values())
        return DashboardSnapshot(
            total_content=total_content,
            counts_by_type=counts_by_type,
            counts_by_status=counts_by_status,
            work_queue=self._work_queue(queue_limit),
            recent_activity=self._recent(recent_limit),
            upcoming=self._upcoming(recent_limit),
        )

    def _counts(self, column: str) -> dict[str, int]:
        frame = self.db.frame(
            f"""SELECT COALESCE(NULLIF(TRIM({column}), ''), 'Unspecified') AS label,
                       COUNT(*) AS count
                FROM content_items
                GROUP BY label
                ORDER BY count DESC, label"""
        )
        return {str(row["label"]): int(row["count"]) for row in frame.to_dict("records")}

    def _work_queue(self, limit: int) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in self.ACTIONABLE_STATUSES)
        frame = self.db.frame(
            f"""SELECT id,title,content_type,platform,status,editor,
                       COALESCE(published_at, recorded_at, updated_at) AS due_at,
                       updated_at
                FROM content_items
                WHERE status IN ({placeholders})
                ORDER BY
                    CASE status
                        WHEN 'Needs review' THEN 1
                        WHEN 'Revision requested' THEN 2
                        WHEN 'Ready to publish' THEN 3
                        WHEN 'Waiting on editor' THEN 4
                        WHEN 'Editing' THEN 5
                        ELSE 6
                    END,
                    COALESCE(published_at, recorded_at, updated_at), title
                LIMIT ?""",
            (*self.ACTIONABLE_STATUSES, max(1, min(int(limit), 100))),
        )
        return frame.to_dict("records")

    def _recent(self, limit: int) -> list[dict[str, Any]]:
        frame = self.db.frame(
            """SELECT id,title,content_type,platform,status,updated_at
               FROM content_items
               ORDER BY updated_at DESC
               LIMIT ?""",
            (max(1, min(int(limit), 100)),),
        )
        return frame.to_dict("records")

    def _upcoming(self, limit: int) -> list[dict[str, Any]]:
        now = datetime.now().isoformat()
        frame = self.db.frame(
            """SELECT id,title,content_type,platform,status,published_at
               FROM content_items
               WHERE published_at IS NOT NULL
                 AND published_at >= ?
                 AND status <> 'Published'
               ORDER BY published_at, title
               LIMIT ?""",
            (now, max(1, min(int(limit), 100))),
        )
        return frame.to_dict("records")
