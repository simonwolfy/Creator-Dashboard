from creator_intelligence.services.cloud_sync_engine import CloudSyncEngine
from creator_intelligence.services.google_drive_sync import GoogleDriveFolderProvider


class FakeProvider:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list_folder_page(self, folder_id, page_token=None):
        self.calls.append((folder_id, page_token))
        return self.pages[(folder_id, page_token)]


def test_pagination_collects_all_items():
    provider = FakeProvider({
        ("root", None): {"items": [{"id": "a", "name": "A"}], "next_page_token": "two"},
        ("root", "two"): {"items": [{"id": "b", "name": "B"}]},
    })
    result = CloudSyncEngine(provider).scan("root", recursive=False)
    assert [item.provider_id for item in result.items] == ["a", "b"]
    assert result.pages_fetched == 2


def test_recursive_scan_visits_child_folder():
    provider = FakeProvider({
        ("root", None): {"items": [{"id": "child", "name": "Child", "is_folder": True}]},
        ("child", None): {"items": [{"id": "video", "name": "video.mp4"}]},
    })
    result = CloudSyncEngine(provider).scan("root")
    assert result.scanned_folders == 2
    assert {item.provider_id for item in result.items} == {"child", "video"}


def test_non_recursive_scan_does_not_visit_child_folder():
    provider = FakeProvider({
        ("root", None): {"items": [{"id": "child", "name": "Child", "is_folder": True}]},
    })
    result = CloudSyncEngine(provider).scan("root", recursive=False)
    assert result.scanned_folders == 1
    assert provider.calls == [("root", None)]


def test_cancellation_returns_partial_result():
    provider = FakeProvider({
        ("root", None): {"items": [{"id": "a", "name": "A"}], "next_page_token": "two"},
        ("root", "two"): {"items": [{"id": "b", "name": "B"}]},
    })
    checks = {"count": 0}
    def cancelled():
        checks["count"] += 1
        return checks["count"] >= 3
    result = CloudSyncEngine(provider).scan("root", recursive=False, cancelled=cancelled)
    assert result.cancelled is True
    assert [item.provider_id for item in result.items] == ["a"]


def test_transient_failure_retries_with_backoff():
    class Flaky:
        def __init__(self):
            self.calls = 0
        def list_folder_page(self, folder_id, page_token=None):
            self.calls += 1
            if self.calls < 3:
                raise TimeoutError("temporary")
            return {"items": []}
    delays = []
    result = CloudSyncEngine(Flaky(), max_retries=3, base_delay_seconds=0.5, sleep=delays.append).scan("root")
    assert result.retries == 2
    assert delays == [0.5, 1.0]


def test_progress_callback_receives_page_updates():
    provider = FakeProvider({("root", None): {"items": [{"id": "a", "name": "A"}]}})
    updates = []
    CloudSyncEngine(provider).scan("root", progress=updates.append)
    assert len(updates) == 1
    assert updates[0].scanned_items == 1
    assert updates[0].pages_fetched == 1


def test_google_drive_adapter_normalizes_response():
    class Request:
        def execute(self):
            return {"files": [{"id": "x", "name": "X", "mimeType": "video/mp4", "parents": ["root"]}]}
    class Files:
        def list(self, **kwargs):
            assert kwargs["pageSize"] == 1000
            return Request()
    class Drive:
        def files(self):
            return Files()
    page = GoogleDriveFolderProvider(Drive()).list_folder_page("root")
    assert page["items"][0]["mime_type"] == "video/mp4"
    assert page["items"][0]["parent_id"] == "root"
