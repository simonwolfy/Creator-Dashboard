from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from creator_intelligence.core.config import AppConfig, ConfigService
from creator_intelligence.core.settings import SettingsValidationError
from creator_intelligence.services.update_checker import (
    RELEASES_API_URL,
    RELEASES_PAGE_URL,
    HttpResponse,
    UpdateChecker,
    UpdateSecurityError,
    UpdateStatus,
    select_release,
)

API_URL = RELEASES_API_URL
DOWNLOAD_ROOT = RELEASES_PAGE_URL + "/download"


def release(version, *, prerelease=False, draft=False, assets=True):
    installer = f"CreatorIntelligence-{version}-windows-x64-setup.exe"
    asset_rows = []
    if assets:
        asset_rows = [
            {"name": installer, "browser_download_url": f"{DOWNLOAD_ROOT}/v{version}/{installer}"},
            {
                "name": installer + ".sha256",
                "browser_download_url": f"{DOWNLOAD_ROOT}/v{version}/{installer}.sha256",
            },
        ]
    return {
        "tag_name": f"v{version}",
        "html_url": f"{RELEASES_PAGE_URL}/tag/v{version}",
        "prerelease": prerelease,
        "draft": draft,
        "published_at": "2026-08-06T00:00:00Z",
        "assets": asset_rows,
    }


class FakeTransport:
    def __init__(self, payload=None, *, failure=None):
        self.payload = payload if payload is not None else []
        self.failure = failure
        self.etag = '"release-etag"'
        self.checksum_body = None
        self.installer_body = b"test-installer"
        self.fetch_calls = []

    def fetch(self, url, *, headers, timeout, limit):
        self.fetch_calls.append((url, dict(headers), timeout, limit))
        if self.failure:
            raise self.failure
        if url == API_URL:
            return HttpResponse(
                200,
                {"etag": self.etag},
                json.dumps(self.payload).encode(),
                API_URL,
            )
        return HttpResponse(200, {}, self.checksum_body or b"", url)

    def download(self, url, destination, *, headers, timeout, limit):
        destination.write_bytes(self.installer_body)


def checker(tmp_path, transport, *, channel="stable", packaged=True, now=None):
    return UpdateChecker(
        current_version="5.0.0-alpha.2",
        state_path=tmp_path / "config" / "update_state.json",
        download_dir=tmp_path / "temp" / "updates",
        channel=channel,
        packaged=packaged,
        transport=transport,
        now=now,
    )


def test_stable_and_preview_channels_select_the_right_release():
    payload = [
        release("5.0.0"),
        release("5.1.0-beta.1", prerelease=True),
        release("9.0.0", draft=True),
    ]
    assert select_release(payload, "stable").version == "5.0.0"
    assert select_release(payload, "preview").version == "5.1.0-beta.1"


def test_newer_release_is_available_and_equal_or_older_is_current(tmp_path):
    update = checker(tmp_path, FakeTransport([release("5.0.0")]))
    result = update.check(force=True)
    assert result.status == UpdateStatus.AVAILABLE
    assert result.release.installer_name == "CreatorIntelligence-5.0.0-windows-x64-setup.exe"

    current = checker(tmp_path / "same", FakeTransport([release("5.0.0-alpha.2", prerelease=True)]), channel="preview")
    assert current.check(force=True).status == UpdateStatus.CURRENT
    older = checker(tmp_path / "old", FakeTransport([release("4.9.0")]))
    assert older.check(force=True).status == UpdateStatus.CURRENT


def test_missing_asset_pair_and_untrusted_urls_fail_closed(tmp_path):
    missing = checker(tmp_path, FakeTransport([release("5.0.0", assets=False)]))
    assert missing.check(force=True).status == UpdateStatus.ERROR

    payload = release("5.0.0")
    payload["assets"][0]["browser_download_url"] = "https://example.com/update.exe"
    untrusted = checker(tmp_path / "untrusted", FakeTransport([payload]))
    assert untrusted.check(force=True).status == UpdateStatus.ERROR


def test_automatic_checks_are_source_safe_throttled_and_skippable(tmp_path):
    clock = [datetime(2026, 8, 6, tzinfo=UTC)]
    transport = FakeTransport([release("5.0.0")])
    source = checker(tmp_path / "source", transport, packaged=False, now=lambda: clock[0])
    assert source.check().status == UpdateStatus.DISABLED
    assert transport.fetch_calls == []
    assert source.check(force=True).status == UpdateStatus.AVAILABLE

    installed = checker(tmp_path / "installed", FakeTransport([release("5.0.0")]), now=lambda: clock[0])
    first = installed.check()
    assert first.status == UpdateStatus.AVAILABLE
    assert installed.check().status == UpdateStatus.THROTTLED
    launch_calls = len(installed.transport.fetch_calls)
    assert installed.check(every_launch=True).status == UpdateStatus.AVAILABLE
    assert len(installed.transport.fetch_calls) == launch_calls + 1
    installed.skip("5.0.0")
    assert installed.check(every_launch=True).status == UpdateStatus.SKIPPED
    clock[0] += timedelta(days=1, seconds=1)
    assert installed.check().status == UpdateStatus.SKIPPED
    assert installed.check(force=True).status == UpdateStatus.AVAILABLE


def test_clock_rollback_does_not_disable_update_checks(tmp_path):
    clock = [datetime(2026, 8, 6, tzinfo=UTC)]
    update = checker(
        tmp_path,
        FakeTransport([release("5.0.0")]),
        now=lambda: clock[0],
    )
    assert update.check().status == UpdateStatus.AVAILABLE
    clock[0] -= timedelta(days=3)
    assert update.should_check() is True
    assert update.check().status == UpdateStatus.AVAILABLE


def test_offline_check_is_nonfatal_and_does_not_expose_exception(tmp_path):
    result = checker(tmp_path, FakeTransport(failure=TimeoutError("secret network detail"))).check(force=True)
    assert result.status == UpdateStatus.ERROR
    assert "secret network detail" not in result.message


def test_read_only_update_state_cannot_break_a_successful_check(tmp_path, monkeypatch):
    update = checker(tmp_path, FakeTransport([release("5.0.0")]))
    monkeypatch.setattr(
        update.state_store,
        "save",
        lambda _state: (_ for _ in ()).throw(PermissionError("read only")),
    )
    assert update.check(force=True).status == UpdateStatus.AVAILABLE


def test_cached_preview_release_cannot_cross_into_stable_channel(tmp_path):
    transport = FakeTransport([release("5.1.0-beta.1", prerelease=True)])
    update = checker(tmp_path, transport, channel="preview")
    assert update.check(force=True).status == UpdateStatus.AVAILABLE
    update.set_channel("stable")
    transport.payload = [release("5.0.0")]
    result = update.check(force=True)
    assert result.status == UpdateStatus.AVAILABLE
    assert result.release.version == "5.0.0"
    assert "If-None-Match" not in transport.fetch_calls[-1][1]


def test_download_is_verified_and_mismatch_removes_partial_file(tmp_path):
    body = b"synthetic installer bytes"
    digest = hashlib.sha256(body).hexdigest()
    transport = FakeTransport()
    transport.installer_body = body
    info = select_release([release("5.0.0")], "stable")
    transport.checksum_body = f"{digest}  {info.installer_name}\n".encode()
    update = checker(tmp_path, transport)
    path = update.download_and_verify(info)
    assert path.read_bytes() == body

    transport.installer_body = b"tampered"
    with pytest.raises(UpdateSecurityError, match="did not match"):
        update.download_and_verify(info)
    assert not path.with_suffix(path.suffix + ".part").exists()


def test_checksum_must_name_exact_installer_once(tmp_path):
    transport = FakeTransport()
    info = select_release([release("5.0.0")], "stable")
    digest = hashlib.sha256(transport.installer_body).hexdigest()
    transport.checksum_body = f"{digest}  another.exe\n".encode()
    with pytest.raises(UpdateSecurityError, match="exactly once"):
        checker(tmp_path, transport).download_and_verify(info)


def test_update_preferences_round_trip_and_invalid_channel_is_rejected(tmp_path):
    service = ConfigService(tmp_path / "settings.json")
    config = service.load()
    config.auto_check_updates = False
    config.update_channel = "preview"
    service.save(config)
    loaded = service.load()
    assert loaded.auto_check_updates is False
    assert loaded.update_channel == "preview"

    invalid = AppConfig(update_channel="nightly")
    with pytest.raises(SettingsValidationError, match="stable or preview"):
        service.save(invalid)
