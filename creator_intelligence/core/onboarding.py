from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

from creator_intelligence.core.config import ConfigService
from creator_intelligence.core.workspace import WorkspaceManager
from creator_intelligence.data.database import Database


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    required: bool
    ready: bool
    detail: str


@dataclass
class InstallationProfile:
    schema_version: int = 1
    onboarding_completed: bool = False
    privacy_acknowledged: bool = False
    workspace_root: str = ""
    workspace_name: str = "My Workspace"
    channel_name: str = "My Channel"
    selected_platforms: list[str] = field(default_factory=list)
    connections_skipped: bool = True
    completed_at: str | None = None


def default_profile_path(environ=None, home=None) -> Path:
    environ = environ or os.environ
    if os.name == "nt" and environ.get("APPDATA"):
        root = Path(environ["APPDATA"])
    else:
        root = Path(environ.get("XDG_CONFIG_HOME") or (Path(home or Path.home()) / ".config"))
    return root / "Creator Intelligence" / "installation.json"


def default_workspace_path(home=None) -> Path:
    return Path(home or Path.home()) / "Creator Intelligence Workspace"


class OnboardingService:
    """First-run state and workspace initialization; never stores provider secrets."""

    def __init__(self, profile_path=None, *, which=None, python_executable=None):
        self.profile_path = Path(profile_path or default_profile_path())
        self.which = which or shutil.which
        self.python_executable = python_executable or sys.executable

    def profile(self) -> InstallationProfile:
        if not self.profile_path.exists():
            return InstallationProfile()
        try:
            payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
            allowed = set(InstallationProfile.__dataclass_fields__)
            return InstallationProfile(**{key:value for key,value in payload.items() if key in allowed})
        except Exception:
            return InstallationProfile()

    def needs_onboarding(self) -> bool:
        profile = self.profile()
        return not (profile.onboarding_completed and profile.privacy_acknowledged
                    and profile.workspace_root and Path(profile.workspace_root).exists())

    def diagnostics(self, workspace_root) -> list[DependencyCheck]:
        root = Path(workspace_root).expanduser()
        writable, detail = self._writable(root)
        ffmpeg, ffprobe = self.which("ffmpeg"), self.which("ffprobe")
        return [
            DependencyCheck("Python", True, bool(self.python_executable and Path(self.python_executable).exists()),
                            self.python_executable or "Python executable was not found."),
            DependencyCheck("Workspace folder", True, writable, detail),
            DependencyCheck("FFmpeg", False, bool(ffmpeg), ffmpeg or "Optional: install FFmpeg for video processing."),
            DependencyCheck("FFprobe", False, bool(ffprobe), ffprobe or "Optional: install FFmpeg to include FFprobe."),
        ]

    def complete(self, *, workspace_root, workspace_name, channel_name,
                 privacy_acknowledged, selected_platforms=None, connections_skipped=True):
        if not privacy_acknowledged:
            raise ValueError("Acknowledge the local-data and privacy notice to continue.")
        workspace_root = Path(workspace_root).expanduser().resolve()
        required_failures = [check for check in self.diagnostics(workspace_root) if check.required and not check.ready]
        if required_failures:
            raise ValueError(" ".join(check.detail for check in required_failures))
        workspace = WorkspaceManager(workspace_root, (workspace_name or "My Workspace").strip())
        paths = workspace.initialize()
        config_service = ConfigService(paths.config / "settings.json")
        config = config_service.load(); config.channel_name = (channel_name or "My Channel").strip(); config_service.save(config)
        Database(paths.database).migrate()
        profile = InstallationProfile(
            onboarding_completed=True, privacy_acknowledged=True,
            workspace_root=str(paths.root), workspace_name=workspace.name,
            channel_name=config.channel_name,
            selected_platforms=sorted(set(selected_platforms or [])),
            connections_skipped=bool(connections_skipped),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._save(profile)
        return profile

    def migrate_existing(self, workspace_root) -> InstallationProfile:
        workspace = WorkspaceManager(Path(workspace_root))
        metadata = workspace.validate()
        config = ConfigService(workspace.paths.config / "settings.json").load()
        profile = InstallationProfile(
            onboarding_completed=True, privacy_acknowledged=True,
            workspace_root=str(workspace.paths.root), workspace_name=metadata["name"],
            channel_name=config.channel_name, connections_skipped=True,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._save(profile); return profile

    def reset(self):
        profile = self.profile(); profile.onboarding_completed = False; self._save(profile)

    def _save(self, profile):
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.profile_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
        temporary.replace(self.profile_path)

    @staticmethod
    def _writable(root):
        try:
            root.mkdir(parents=True, exist_ok=True)
            marker = root / ".creator-intelligence-write-test"
            marker.write_text("ok", encoding="utf-8"); marker.unlink()
            return True, f"Ready: {root.resolve()}"
        except OSError as exc:
            return False, f"Cannot write to this folder: {exc}"
