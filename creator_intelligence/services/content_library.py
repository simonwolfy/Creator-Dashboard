from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from uuid import uuid4


class ContentLibraryService:
    """Canonical content catalog and relationship graph."""

    def __init__(self, db):
        self.db = db

    def create_item(self, values: dict[str, Any]) -> str:
        now = datetime.now().isoformat()
        content_id = str(values.get("id") or uuid4())
        platform = str(values.get("platform") or "Local").strip()
        content_type = str(values.get("content_type") or "Unknown").strip()
        title = str(values.get("title") or "Untitled").strip()
        external_id = self._optional_text(values.get("external_id"))

        self.db.execute(
            """
            INSERT INTO content_items(
                id, platform, external_id, content_type, title, game_topic,
                series_name, episode_number, status, editor,
                collaborators_json, tags_json, thumbnail_url, source_url,
                local_path, recorded_at, published_at, duration_seconds,
                views, watch_hours, engagement_rate, retention_rate, revenue,
                notes, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                content_id,
                platform,
                external_id,
                content_type,
                title,
                self._optional_text(values.get("game_topic")),
                self._optional_text(values.get("series_name")),
                self._optional_text(values.get("episode_number")),
                str(values.get("status") or "Planned"),
                self._optional_text(values.get("editor")),
                self._json_list(values.get("collaborators")),
                self._json_list(values.get("tags")),
                self._optional_text(values.get("thumbnail_url")),
                self._optional_text(values.get("source_url")),
                self._optional_text(values.get("local_path")),
                self._optional_text(values.get("recorded_at")),
                self._optional_text(values.get("published_at")),
                self._number(values.get("duration_seconds")),
                int(values.get("views") or 0),
                float(values.get("watch_hours") or 0),
                self._number(values.get("engagement_rate")),
                self._number(values.get("retention_rate")),
                float(values.get("revenue") or 0),
                self._optional_text(values.get("notes")),
                now,
                now,
            ),
        )
        return content_id

    def update_item(self, content_id: str, values: dict[str, Any]) -> None:
        allowed = {
            "platform",
            "external_id",
            "content_type",
            "title",
            "game_topic",
            "series_name",
            "episode_number",
            "status",
            "editor",
            "thumbnail_url",
            "source_url",
            "local_path",
            "recorded_at",
            "published_at",
            "duration_seconds",
            "views",
            "watch_hours",
            "engagement_rate",
            "retention_rate",
            "revenue",
            "notes",
        }
        updates: list[str] = []
        params: list[Any] = []
        for key, value in values.items():
            if key == "collaborators":
                updates.append("collaborators_json=?")
                params.append(self._json_list(value))
            elif key == "tags":
                updates.append("tags_json=?")
                params.append(self._json_list(value))
            elif key in allowed:
                updates.append(f"{key}=?")
                params.append(value)
        if not updates:
            return
        updates.append("updated_at=?")
        params.extend([datetime.now().isoformat(), content_id])
        self.db.execute(
            f"UPDATE content_items SET {', '.join(updates)} WHERE id=?",
            params,
        )

    def get_item(self, content_id: str) -> dict[str, Any] | None:
        frame = self.db.frame("SELECT * FROM content_items WHERE id=?", (content_id,))
        if frame.empty:
            return None
        return self._decode(frame.iloc[0].to_dict())

    def search(
        self,
        query: str | None = None,
        *,
        platform: str | None = None,
        content_type: str | None = None,
        game_topic: str | None = None,
        series_name: str | None = None,
        status: str | None = None,
        editor: str | None = None,
        min_views: int | None = None,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            clauses.append("(title LIKE ? OR notes LIKE ? OR tags_json LIKE ?)")
            token = f"%{query}%"
            params.extend([token, token, token])
        for column, value in (
            ("platform", platform),
            ("content_type", content_type),
            ("game_topic", game_topic),
            ("series_name", series_name),
            ("status", status),
            ("editor", editor),
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        if min_views is not None:
            clauses.append("views>=?")
            params.append(int(min_views))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 1000)))
        frame = self.db.frame(
            f"SELECT * FROM content_items {where} ORDER BY COALESCE(published_at, recorded_at, created_at) DESC LIMIT ?",
            params,
        )
        return [self._decode(row) for row in frame.to_dict("records")]

    def relate(
        self,
        parent_content_id: str,
        child_content_id: str,
        relationship_type: str = "derived_from",
        *,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        notes: str | None = None,
    ) -> int:
        if parent_content_id == child_content_id:
            raise ValueError("A content item cannot be related to itself.")
        return int(
            self.db.execute(
                """
                INSERT INTO content_relationships(
                    parent_content_id, child_content_id, relationship_type,
                    start_seconds, end_seconds, notes, created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    parent_content_id,
                    child_content_id,
                    relationship_type,
                    start_seconds,
                    end_seconds,
                    notes,
                    datetime.now().isoformat(),
                ),
            )
        )

    def children(self, content_id: str) -> list[dict[str, Any]]:
        frame = self.db.frame(
            """
            SELECT child.*, rel.relationship_type, rel.start_seconds,
                   rel.end_seconds, rel.notes AS relationship_notes
            FROM content_relationships rel
            JOIN content_items child ON child.id=rel.child_content_id
            WHERE rel.parent_content_id=?
            ORDER BY child.created_at
            """,
            (content_id,),
        )
        return [self._decode(row) for row in frame.to_dict("records")]

    def parents(self, content_id: str) -> list[dict[str, Any]]:
        frame = self.db.frame(
            """
            SELECT parent.*, rel.relationship_type, rel.start_seconds,
                   rel.end_seconds, rel.notes AS relationship_notes
            FROM content_relationships rel
            JOIN content_items parent ON parent.id=rel.parent_content_id
            WHERE rel.child_content_id=?
            ORDER BY parent.created_at
            """,
            (content_id,),
        )
        return [self._decode(row) for row in frame.to_dict("records")]

    @staticmethod
    def _json_list(value: Any) -> str:
        if value is None:
            return "[]"
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        return json.dumps(list(value))

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _number(value: Any) -> float | None:
        return None if value in (None, "") else float(value)

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        row["collaborators"] = json.loads(row.pop("collaborators_json", "[]") or "[]")
        row["tags"] = json.loads(row.pop("tags_json", "[]") or "[]")
        return row
