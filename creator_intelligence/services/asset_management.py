from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class AssetManagementService:
    """Canonical registry for production assets and their relationships."""

    def __init__(self, db):
        self.db = db

    def create_asset(self, values: dict[str, Any]) -> str:
        now = datetime.now().isoformat()
        asset_id = str(values.get("id") or uuid4())
        location = self._optional_text(values.get("location"))
        path = Path(location) if location and values.get("storage_provider", "Local") == "Local" else None
        extension = self._optional_text(values.get("extension"))
        if extension is None and path is not None:
            extension = path.suffix.lower() or None
        name = self._optional_text(values.get("name"))
        if name is None and path is not None:
            name = path.name
        if name is None:
            name = "Untitled asset"

        self.db.execute(
            """
            INSERT INTO managed_assets(
                id,name,asset_type,role,storage_provider,provider_key,location,
                mime_type,extension,size_bytes,checksum_sha256,status,
                recorded_at,created_at,updated_at,last_verified_at,notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                asset_id,
                name,
                str(values.get("asset_type") or "Other"),
                self._optional_text(values.get("role")),
                str(values.get("storage_provider") or "Local"),
                self._optional_text(values.get("provider_key")),
                location,
                self._optional_text(values.get("mime_type")),
                extension,
                self._integer(values.get("size_bytes")),
                self._normalize_checksum(values.get("checksum_sha256")),
                str(values.get("status") or "Available"),
                self._optional_text(values.get("recorded_at")),
                now,
                now,
                self._optional_text(values.get("last_verified_at")),
                self._optional_text(values.get("notes")),
            ),
        )
        return asset_id

    def update_asset(self, asset_id: str, values: dict[str, Any]) -> None:
        allowed = {
            "name",
            "asset_type",
            "role",
            "storage_provider",
            "provider_key",
            "location",
            "mime_type",
            "extension",
            "size_bytes",
            "status",
            "recorded_at",
            "last_verified_at",
            "notes",
        }
        updates: list[str] = []
        params: list[Any] = []
        for key, value in values.items():
            if key == "checksum_sha256":
                updates.append("checksum_sha256=?")
                params.append(self._normalize_checksum(value))
            elif key in allowed:
                updates.append(f"{key}=?")
                params.append(value)
        if not updates:
            return
        updates.append("updated_at=?")
        params.extend([datetime.now().isoformat(), asset_id])
        self.db.execute(
            f"UPDATE managed_assets SET {', '.join(updates)} WHERE id=?",
            params,
        )

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        frame = self.db.frame("SELECT * FROM managed_assets WHERE id=?", (asset_id,))
        return None if frame.empty else frame.iloc[0].to_dict()

    def search(
        self,
        query: str | None = None,
        *,
        asset_type: str | None = None,
        role: str | None = None,
        storage_provider: str | None = None,
        status: str | None = None,
        checksum_sha256: str | None = None,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            token = f"%{query}%"
            clauses.append("(name LIKE ? OR location LIKE ? OR notes LIKE ?)")
            params.extend([token, token, token])
        for column, value in (
            ("asset_type", asset_type),
            ("role", role),
            ("storage_provider", storage_provider),
            ("status", status),
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        if checksum_sha256:
            clauses.append("checksum_sha256=?")
            params.append(self._normalize_checksum(checksum_sha256))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 1000)))
        frame = self.db.frame(
            f"SELECT * FROM managed_assets {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        )
        return frame.to_dict("records")

    def link_content(
        self,
        content_id: str,
        asset_id: str,
        *,
        role: str = "supporting",
        is_primary: bool = False,
    ) -> int:
        return int(
            self.db.execute(
                """
                INSERT INTO content_asset_links(content_id,asset_id,role,is_primary,created_at)
                VALUES(?,?,?,?,?)
                """,
                (content_id, asset_id, role, int(is_primary), datetime.now().isoformat()),
            )
        )

    def assets_for_content(self, content_id: str) -> list[dict[str, Any]]:
        frame = self.db.frame(
            """
            SELECT asset.*, link.role AS content_role, link.is_primary
            FROM content_asset_links link
            JOIN managed_assets asset ON asset.id=link.asset_id
            WHERE link.content_id=?
            ORDER BY link.is_primary DESC, asset.updated_at DESC
            """,
            (content_id,),
        )
        return frame.to_dict("records")

    def content_for_asset(self, asset_id: str) -> list[dict[str, Any]]:
        frame = self.db.frame(
            """
            SELECT content.*, link.role AS asset_role, link.is_primary
            FROM content_asset_links link
            JOIN content_items content ON content.id=link.content_id
            WHERE link.asset_id=?
            ORDER BY content.updated_at DESC
            """,
            (asset_id,),
        )
        return frame.to_dict("records")

    def relate_assets(
        self,
        parent_asset_id: str,
        child_asset_id: str,
        relationship_type: str = "derived_from",
        notes: str | None = None,
    ) -> int:
        if parent_asset_id == child_asset_id:
            raise ValueError("An asset cannot be related to itself.")
        return int(
            self.db.execute(
                """
                INSERT INTO managed_asset_relationships(
                    parent_asset_id,child_asset_id,relationship_type,created_at,notes
                ) VALUES(?,?,?,?,?)
                """,
                (
                    parent_asset_id,
                    child_asset_id,
                    relationship_type,
                    datetime.now().isoformat(),
                    notes,
                ),
            )
        )

    def derived_assets(self, asset_id: str) -> list[dict[str, Any]]:
        frame = self.db.frame(
            """
            SELECT child.*, rel.relationship_type, rel.notes AS relationship_notes
            FROM managed_asset_relationships rel
            JOIN managed_assets child ON child.id=rel.child_asset_id
            WHERE rel.parent_asset_id=?
            ORDER BY child.created_at
            """,
            (asset_id,),
        )
        return frame.to_dict("records")

    def source_assets(self, asset_id: str) -> list[dict[str, Any]]:
        frame = self.db.frame(
            """
            SELECT parent.*, rel.relationship_type, rel.notes AS relationship_notes
            FROM managed_asset_relationships rel
            JOIN managed_assets parent ON parent.id=rel.parent_asset_id
            WHERE rel.child_asset_id=?
            ORDER BY parent.created_at
            """,
            (asset_id,),
        )
        return frame.to_dict("records")

    def duplicates_for_checksum(self, checksum_sha256: str) -> list[dict[str, Any]]:
        return self.search(checksum_sha256=checksum_sha256, limit=1000)

    def mark_verified(self, asset_id: str, *, available: bool) -> None:
        self.update_asset(
            asset_id,
            {
                "status": "Available" if available else "Missing",
                "last_verified_at": datetime.now().isoformat(),
            },
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _integer(value: Any) -> int | None:
        return None if value in (None, "") else int(value)

    @staticmethod
    def _normalize_checksum(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None
