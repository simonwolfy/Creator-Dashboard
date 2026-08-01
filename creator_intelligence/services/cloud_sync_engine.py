from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Protocol


class SyncCancelled(RuntimeError):
    """Raised internally when a caller cancels a synchronization session."""


class CloudFolderProvider(Protocol):
    """Minimal provider contract used by the synchronization engine."""

    def list_folder_page(self, folder_id: str, page_token: str | None = None) -> dict[str, Any]:
        """Return {'items': [...], 'next_page_token': str | None}."""


@dataclass(frozen=True)
class SyncItem:
    provider_id: str
    name: str
    mime_type: str | None = None
    parent_id: str | None = None
    is_folder: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SyncProgress:
    root_folder_id: str
    current_folder_id: str
    scanned_items: int
    scanned_folders: int
    pages_fetched: int
    retries: int
    cancelled: bool = False


@dataclass(frozen=True)
class SyncResult:
    root_folder_id: str
    items: tuple[SyncItem, ...]
    scanned_folders: int
    pages_fetched: int
    retries: int
    cancelled: bool


class CloudSyncEngine:
    """Provider-neutral, read-only folder enumeration engine.

    Persistence and asset reconciliation are intentionally delegated to later
    phases. This class owns traversal, pagination, progress, cancellation, and
    bounded retry behavior.
    """

    def __init__(
        self,
        provider: CloudFolderProvider,
        *,
        max_retries: int = 3,
        base_delay_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        transient_error: Callable[[Exception], bool] | None = None,
    ):
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater")
        if base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be zero or greater")
        self.provider = provider
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.sleep = sleep
        self.transient_error = transient_error or _default_transient_error

    def scan(
        self,
        root_folder_id: str,
        *,
        recursive: bool = True,
        progress: Callable[[SyncProgress], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> SyncResult:
        if not root_folder_id:
            raise ValueError("root_folder_id is required")
        is_cancelled = cancelled or (lambda: False)
        queue = [root_folder_id]
        visited: set[str] = set()
        items: list[SyncItem] = []
        pages_fetched = 0
        retries = 0

        while queue:
            if is_cancelled():
                return SyncResult(root_folder_id, tuple(items), len(visited), pages_fetched, retries, True)
            folder_id = queue.pop(0)
            if folder_id in visited:
                continue
            visited.add(folder_id)
            page_token: str | None = None
            while True:
                if is_cancelled():
                    return SyncResult(root_folder_id, tuple(items), len(visited), pages_fetched, retries, True)
                payload, used_retries = self._fetch_page(folder_id, page_token)
                retries += used_retries
                pages_fetched += 1
                for raw in payload.get("items", ()):  # provider-normalized records
                    item = _to_item(raw, folder_id)
                    items.append(item)
                    if recursive and item.is_folder and item.provider_id not in visited:
                        queue.append(item.provider_id)
                if progress:
                    progress(
                        SyncProgress(
                            root_folder_id=root_folder_id,
                            current_folder_id=folder_id,
                            scanned_items=len(items),
                            scanned_folders=len(visited),
                            pages_fetched=pages_fetched,
                            retries=retries,
                        )
                    )
                page_token = payload.get("next_page_token")
                if not page_token:
                    break

        return SyncResult(root_folder_id, tuple(items), len(visited), pages_fetched, retries, False)

    def _fetch_page(self, folder_id: str, page_token: str | None) -> tuple[dict[str, Any], int]:
        retries = 0
        while True:
            try:
                payload = self.provider.list_folder_page(folder_id, page_token)
                if not isinstance(payload, dict):
                    raise TypeError("Provider page response must be a dictionary")
                return payload, retries
            except Exception as exc:
                if retries >= self.max_retries or not self.transient_error(exc):
                    raise
                delay = self.base_delay_seconds * (2**retries)
                retries += 1
                self.sleep(delay)


def _to_item(raw: dict[str, Any], parent_id: str) -> SyncItem:
    provider_id = str(raw.get("id") or "")
    if not provider_id:
        raise ValueError("Provider item is missing an id")
    mime_type = raw.get("mime_type") or raw.get("mimeType")
    is_folder = bool(raw.get("is_folder")) or mime_type == "application/vnd.google-apps.folder"
    return SyncItem(
        provider_id=provider_id,
        name=str(raw.get("name") or provider_id),
        mime_type=None if mime_type is None else str(mime_type),
        parent_id=str(raw.get("parent_id") or parent_id),
        is_folder=is_folder,
        raw=dict(raw),
    )


def _default_transient_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
    return status in {408, 429, 500, 502, 503, 504} or isinstance(exc, (TimeoutError, ConnectionError))
