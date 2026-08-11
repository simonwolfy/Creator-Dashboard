from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

RELEASES_API_URL = (
    "https://api.github.com/repos/simonwolfy/Creator-Dashboard/releases?per_page=20"
)
RELEASES_PAGE_URL = "https://github.com/simonwolfy/Creator-Dashboard/releases"
TRUSTED_DOWNLOAD_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
MAX_RELEASE_METADATA_BYTES = 2 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4096
MAX_INSTALLER_BYTES = 1024 * 1024 * 1024
CHECK_INTERVAL = timedelta(hours=24)
INSTALLER_NAME = re.compile(
    r"^CreatorIntelligence-(?P<version>[0-9A-Za-z.-]+)-windows-x64-setup\.exe$"
)


class UpdateStatus(StrEnum):
    AVAILABLE = "available"
    CURRENT = "current"
    SKIPPED = "skipped"
    THROTTLED = "throttled"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class UpdateSecurityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    page_url: str
    prerelease: bool
    installer_name: str
    installer_url: str
    checksum_url: str
    published_at: str | None = None

    def to_cache(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_cache(cls, value: Any) -> ReleaseInfo | None:
        if not isinstance(value, dict):
            return None
        allowed = set(cls.__dataclass_fields__)
        try:
            release = cls(**{key: value[key] for key in allowed if key in value})
            _require_trusted_url(release.page_url, {"github.com"})
            _require_trusted_url(release.installer_url)
            _require_trusted_url(release.checksum_url)
            if not INSTALLER_NAME.fullmatch(release.installer_name):
                return None
            Version(release.version)
            return release
        except (KeyError, TypeError, ValueError, InvalidVersion, UpdateSecurityError):
            return None


@dataclass(frozen=True)
class UpdateCheckResult:
    status: UpdateStatus
    current_version: str
    message: str
    release: ReleaseInfo | None = None


@dataclass
class UpdateState:
    schema_version: int = 1
    last_checked_at: str | None = None
    etag: str | None = None
    skipped_version: str | None = None
    cached_channel: str | None = None
    cached_release: dict[str, Any] | None = field(default=None)


class UpdateStateStore:
    """Atomic, non-secret update state kept separate from creator settings."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> UpdateState:
        if not self.path.exists():
            return UpdateState()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = set(UpdateState.__dataclass_fields__)
            state = UpdateState(**{key: value for key, value in payload.items() if key in allowed})
            if state.schema_version != 1:
                return UpdateState()
            return state
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return UpdateState()

    def save(self, state: UpdateState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(state), indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    final_url: str


class UrlTransport:
    """Small bounded HTTPS transport with no authentication or creator data."""

    def fetch(self, url: str, *, headers: dict[str, str], timeout: float, limit: int) -> HttpResponse:
        _require_trusted_url(url)
        request = Request(url, headers=headers)
        try:
            response = urlopen(request, timeout=timeout)
        except HTTPError as exc:
            response = exc
        with response:
            final_url = response.geturl()
            _require_trusted_url(final_url)
            body = _read_bounded(response, limit)
            return HttpResponse(
                int(response.status),
                {str(key).lower(): str(value) for key, value in response.headers.items()},
                body,
                final_url,
            )

    def download(
        self,
        url: str,
        destination: Path,
        *,
        headers: dict[str, str],
        timeout: float,
        limit: int,
    ) -> None:
        _require_trusted_url(url)
        request = Request(url, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            _require_trusted_url(response.geturl())
            length = response.headers.get("Content-Length")
            if length and int(length) > limit:
                raise UpdateSecurityError("The update download is larger than the allowed limit.")
            total = 0
            with destination.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > limit:
                        raise UpdateSecurityError("The update download is larger than the allowed limit.")
                    output.write(chunk)


class UpdateChecker:
    """Checks signed-ready GitHub releases without delaying application startup."""

    def __init__(
        self,
        *,
        current_version: str,
        state_path: Path,
        download_dir: Path,
        channel: str = "stable",
        packaged: bool | None = None,
        transport: Any | None = None,
        now: Callable[[], datetime] | None = None,
        api_url: str = RELEASES_API_URL,
    ):
        self.current_version = current_version
        self.state_store = UpdateStateStore(state_path)
        self.download_dir = Path(download_dir)
        self.channel = _channel(channel)
        self.packaged = bool(getattr(sys, "frozen", False)) if packaged is None else packaged
        self.transport = transport or UrlTransport()
        self.now = now or (lambda: datetime.now(UTC))
        self.api_url = api_url

    def set_channel(self, channel: str) -> None:
        self.channel = _channel(channel)

    def should_check(self) -> bool:
        if not self.packaged:
            return False
        state = self.state_store.load()
        checked = _parse_timestamp(state.last_checked_at)
        if checked is None:
            return True
        elapsed = self.now() - checked
        return elapsed < timedelta(0) or elapsed >= CHECK_INTERVAL

    def check(
        self,
        *,
        force: bool = False,
        every_launch: bool = False,
    ) -> UpdateCheckResult:
        current = _version(self.current_version)
        state = self.state_store.load()
        if not force and not self.packaged:
            return UpdateCheckResult(
                UpdateStatus.DISABLED,
                self.current_version,
                "Automatic update checks run in the installed Windows app.",
            )
        checked = _parse_timestamp(state.last_checked_at)
        elapsed = self.now() - checked if checked is not None else None
        if (
            not force
            and not every_launch
            and elapsed is not None
            and timedelta(0) <= elapsed < CHECK_INTERVAL
        ):
            return UpdateCheckResult(
                UpdateStatus.THROTTLED,
                self.current_version,
                "The installed app already checked for updates in the last 24 hours.",
            )

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"CreatorIntelligence/{self.current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if state.etag and state.cached_channel == self.channel:
            headers["If-None-Match"] = state.etag

        state.last_checked_at = self.now().astimezone(UTC).isoformat()
        try:
            response = self.transport.fetch(
                self.api_url,
                headers=headers,
                timeout=8.0,
                limit=MAX_RELEASE_METADATA_BYTES,
            )
            if response.status == 304:
                release = ReleaseInfo.from_cache(state.cached_release)
                self._save_state(state)
                return self._result_for_release(current, state, release, force=force)
            if response.status == 404:
                self._save_state(state)
                return UpdateCheckResult(
                    UpdateStatus.UNAVAILABLE,
                    self.current_version,
                    "Published updates are not available yet.",
                )
            if response.status == 403:
                self._save_state(state)
                return UpdateCheckResult(
                    UpdateStatus.UNAVAILABLE,
                    self.current_version,
                    "GitHub temporarily limited update checks. Try again later.",
                )
            if response.status != 200:
                raise RuntimeError(f"GitHub returned status {response.status}.")
            payload = json.loads(response.body.decode("utf-8"))
            release = select_release(payload, self.channel)
            state.etag = response.headers.get("etag")
            state.cached_channel = self.channel
            state.cached_release = release.to_cache() if release else None
            self._save_state(state)
            return self._result_for_release(current, state, release, force=force)
        except Exception:
            self._save_state(state)
            return UpdateCheckResult(
                UpdateStatus.ERROR,
                self.current_version,
                "Could not check for updates. The app will keep working normally.",
            )

    def _result_for_release(
        self,
        current: Version,
        state: UpdateState,
        release: ReleaseInfo | None,
        *,
        force: bool,
    ) -> UpdateCheckResult:
        if release is None:
            return UpdateCheckResult(
                UpdateStatus.CURRENT,
                self.current_version,
                f"No newer {self.channel} release is available.",
            )
        if self.channel == "stable" and release.prerelease:
            return UpdateCheckResult(
                UpdateStatus.CURRENT,
                self.current_version,
                "No newer stable release is available.",
            )
        if _version(release.version) <= current:
            return UpdateCheckResult(
                UpdateStatus.CURRENT,
                self.current_version,
                f"Creator Intelligence {self.current_version} is up to date.",
                release,
            )
        if not force and state.skipped_version == release.version:
            return UpdateCheckResult(
                UpdateStatus.SKIPPED,
                self.current_version,
                f"Version {release.version} is skipped on this workspace.",
                release,
            )
        return UpdateCheckResult(
            UpdateStatus.AVAILABLE,
            self.current_version,
            f"Creator Intelligence {release.version} is available.",
            release,
        )

    def skip(self, version: str) -> bool:
        _version(version)
        state = self.state_store.load()
        state.skipped_version = version
        return self._save_state(state)

    def clear_skip(self) -> bool:
        state = self.state_store.load()
        state.skipped_version = None
        return self._save_state(state)

    def _save_state(self, state: UpdateState) -> bool:
        try:
            self.state_store.save(state)
            return True
        except OSError:
            return False

    def download_and_verify(self, release: ReleaseInfo) -> Path:
        """Download a release installer and verify its exact companion SHA-256 file."""
        if not self.packaged:
            raise RuntimeError("Installer downloads are available only in the installed Windows app.")
        _validate_release_urls(release)
        match = INSTALLER_NAME.fullmatch(release.installer_name)
        if not match or match.group("version") != release.version:
            raise UpdateSecurityError("The release installer name does not match its version.")

        headers = {
            "Accept": "application/octet-stream",
            "User-Agent": f"CreatorIntelligence/{self.current_version}",
        }
        checksum_response = self.transport.fetch(
            release.checksum_url,
            headers=headers,
            timeout=15.0,
            limit=MAX_CHECKSUM_BYTES,
        )
        if checksum_response.status != 200:
            raise RuntimeError("The update checksum could not be downloaded.")
        expected = _checksum_for(
            checksum_response.body.decode("ascii", errors="strict"),
            release.installer_name,
        )

        self.download_dir.mkdir(parents=True, exist_ok=True)
        target = self.download_dir / release.installer_name
        partial = target.with_suffix(target.suffix + ".part")
        try:
            partial.unlink(missing_ok=True)
            self.transport.download(
                release.installer_url,
                partial,
                headers=headers,
                timeout=120.0,
                limit=MAX_INSTALLER_BYTES,
            )
            actual = _sha256(partial)
            if actual != expected:
                raise UpdateSecurityError("The downloaded installer did not match its SHA-256 checksum.")
            partial.replace(target)
            return target
        except Exception:
            partial.unlink(missing_ok=True)
            raise


def select_release(payload: Any, channel: str) -> ReleaseInfo | None:
    if not isinstance(payload, list):
        raise ValueError("GitHub release metadata must be a list.")
    channel = _channel(channel)
    candidates: list[tuple[Version, dict[str, Any]]] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        if channel == "stable" and item.get("prerelease"):
            continue
        tag = str(item.get("tag_name") or "")
        try:
            parsed = _version(tag.removeprefix("v"))
        except InvalidVersion:
            continue
        candidates.append((parsed, item))
    if not candidates:
        return None
    _, item = max(candidates, key=lambda pair: pair[0])
    return _release_info(item)


def _release_info(item: dict[str, Any]) -> ReleaseInfo:
    tag = str(item.get("tag_name") or "")
    version = tag.removeprefix("v")
    _version(version)
    expected_installer = f"CreatorIntelligence-{version}-windows-x64-setup.exe"
    assets = item.get("assets")
    if not isinstance(assets, list):
        raise ValueError("The release does not contain Windows assets.")

    installers = [asset for asset in assets if asset.get("name") == expected_installer]
    checksums = [asset for asset in assets if asset.get("name") == expected_installer + ".sha256"]
    if len(installers) != 1 or len(checksums) != 1:
        raise ValueError("The release needs one Windows installer and one exact SHA-256 file.")
    page_url = str(item.get("html_url") or "")
    installer_url = str(installers[0].get("browser_download_url") or "")
    checksum_url = str(checksums[0].get("browser_download_url") or "")
    release = ReleaseInfo(
        version=version,
        tag_name=tag,
        page_url=page_url,
        prerelease=bool(item.get("prerelease")),
        installer_name=expected_installer,
        installer_url=installer_url,
        checksum_url=checksum_url,
        published_at=item.get("published_at"),
    )
    _validate_release_urls(release)
    return release


def _validate_release_urls(release: ReleaseInfo) -> None:
    _require_trusted_url(release.page_url, {"github.com"})
    _require_trusted_url(release.installer_url)
    _require_trusted_url(release.checksum_url)


def _require_trusted_url(url: str, hosts: set[str] | None = None) -> None:
    parsed = urlparse(url)
    allowed = hosts or TRUSTED_DOWNLOAD_HOSTS
    if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password:
        raise UpdateSecurityError("The update URL is not a trusted GitHub HTTPS address.")


def _read_bounded(response: Any, limit: int) -> bytes:
    length = response.headers.get("Content-Length")
    if length and int(length) > limit:
        raise UpdateSecurityError("The update response is larger than the allowed limit.")
    body = response.read(limit + 1)
    if len(body) > limit:
        raise UpdateSecurityError("The update response is larger than the allowed limit.")
    return body


def _checksum_for(text: str, filename: str) -> str:
    matches = []
    for line in text.splitlines():
        match = re.fullmatch(r"\s*([0-9A-Fa-f]{64})\s+\*?(.+?)\s*", line)
        if match and match.group(2) == filename:
            matches.append(match.group(1).lower())
    if len(matches) != 1:
        raise UpdateSecurityError("The checksum file does not name the expected installer exactly once.")
    return matches[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _channel(value: str) -> str:
    if value not in {"stable", "preview"}:
        raise ValueError("Update channel must be stable or preview.")
    return value


def _version(value: str) -> Version:
    return Version(str(value).removeprefix("v"))
