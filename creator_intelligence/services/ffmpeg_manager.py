from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable


@dataclass(frozen=True)
class FFmpegStatus:
    ffmpeg_path: str | None
    ffprobe_path: str | None
    ffmpeg_version: str | None
    ffprobe_version: str | None
    ready: bool
    source: str
    message: str


class FFmpegManagerService:
    """Detect, validate, install, and persist FFmpeg tool locations.

    The manager never modifies the system PATH. Creator Intelligence stores its
    own executable paths, which avoids requiring elevation or a restart.
    """

    WINGET_PACKAGE = "Gyan.FFmpeg"

    def __init__(
        self,
        db,
        *,
        runner: Callable[..., Any] | None = None,
        which: Callable[[str], str | None] | None = None,
        environ: dict[str, str] | None = None,
    ):
        self.db = db
        self.runner = runner or subprocess.run
        self.which = which or shutil.which
        self.environ = environ if environ is not None else os.environ
        workspace_root = Path(db.path).resolve().parent.parent
        self.config_path = workspace_root / "config" / "ffmpeg.json"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def status(self) -> FFmpegStatus:
        ffmpeg, ffprobe, source = self._resolve_paths()
        ffmpeg_version = self._version(ffmpeg)
        ffprobe_version = self._version(ffprobe)
        ready = bool(ffmpeg and ffprobe and ffmpeg_version and ffprobe_version)
        if ready:
            message = "FFmpeg and FFprobe are ready."
        elif ffmpeg or ffprobe:
            message = "FFmpeg configuration is incomplete or one executable could not be started."
        else:
            message = "FFmpeg and FFprobe were not found. Install them or select their bin folder."
        return FFmpegStatus(ffmpeg, ffprobe, ffmpeg_version, ffprobe_version, ready, source, message)

    def configure_bin_folder(self, folder: str | Path) -> FFmpegStatus:
        folder = Path(folder).expanduser().resolve()
        ffmpeg = self._executable(folder, "ffmpeg")
        ffprobe = self._executable(folder, "ffprobe")
        if not ffmpeg or not ffprobe:
            raise ValueError("The selected folder must contain both ffmpeg and ffprobe executables.")
        if not self._version(str(ffmpeg)) or not self._version(str(ffprobe)):
            raise ValueError("FFmpeg or FFprobe could not be started from the selected folder.")
        self._save({"ffmpeg_path": str(ffmpeg), "ffprobe_path": str(ffprobe)})
        return self.status()

    def clear_configuration(self) -> FFmpegStatus:
        if self.config_path.exists():
            self.config_path.unlink()
        return self.status()

    def install_with_winget(self) -> dict[str, Any]:
        winget = self.which("winget")
        if not winget:
            raise RuntimeError("Windows Package Manager (winget) is not available on this computer.")
        command = [
            winget,
            "install",
            "--id",
            self.WINGET_PACKAGE,
            "--exact",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--silent",
        ]
        result = self.runner(command, capture_output=True, text=True, timeout=900)
        output = "\n".join(part for part in (getattr(result, "stdout", ""), getattr(result, "stderr", "")) if part).strip()
        if int(getattr(result, "returncode", 1)) != 0:
            raise RuntimeError(output or f"winget exited with code {result.returncode}")
        discovered = self._discover_winget_tools()
        if discovered:
            self._save({"ffmpeg_path": discovered[0], "ffprobe_path": discovered[1]})
        return {"command": command, "output": output, "status": self.status()}

    def environment(self) -> dict[str, str]:
        status = self.status()
        values: dict[str, str] = {}
        if status.ffmpeg_path:
            values["CREATOR_INTELLIGENCE_FFMPEG"] = status.ffmpeg_path
        if status.ffprobe_path:
            values["CREATOR_INTELLIGENCE_FFPROBE"] = status.ffprobe_path
        return values

    def _resolve_paths(self) -> tuple[str | None, str | None, str]:
        configured = self._load()
        ffmpeg = self._valid_path(configured.get("ffmpeg_path"))
        ffprobe = self._valid_path(configured.get("ffprobe_path"))
        if ffmpeg and ffprobe:
            return ffmpeg, ffprobe, "Creator Intelligence configuration"

        ffmpeg = self._valid_path(self.environ.get("CREATOR_INTELLIGENCE_FFMPEG"))
        ffprobe = self._valid_path(self.environ.get("CREATOR_INTELLIGENCE_FFPROBE"))
        if ffmpeg and ffprobe:
            return ffmpeg, ffprobe, "Environment variables"

        ffmpeg = self._valid_path(self.which("ffmpeg"))
        ffprobe = self._valid_path(self.which("ffprobe"))
        if ffmpeg and ffprobe:
            return ffmpeg, ffprobe, "System PATH"

        discovered = self._discover_winget_tools()
        if discovered:
            return discovered[0], discovered[1], "WinGet installation"
        return ffmpeg, ffprobe, "Not found"

    def _discover_winget_tools(self) -> tuple[str, str] | None:
        local = Path(self.environ.get("LOCALAPPDATA", ""))
        candidates = [local / "Microsoft" / "WinGet" / "Links"]
        packages = local / "Microsoft" / "WinGet" / "Packages"
        if packages.exists():
            candidates.extend(path for path in packages.glob("Gyan.FFmpeg*") if path.is_dir())
        for root in candidates:
            if not root.exists():
                continue
            direct_ffmpeg = self._executable(root, "ffmpeg")
            direct_ffprobe = self._executable(root, "ffprobe")
            if direct_ffmpeg and direct_ffprobe:
                return str(direct_ffmpeg), str(direct_ffprobe)
            for bin_dir in root.glob("**/bin"):
                ffmpeg = self._executable(bin_dir, "ffmpeg")
                ffprobe = self._executable(bin_dir, "ffprobe")
                if ffmpeg and ffprobe:
                    return str(ffmpeg), str(ffprobe)
        return None

    def _version(self, executable: str | None) -> str | None:
        if not executable:
            return None
        try:
            result = self.runner([executable, "-version"], capture_output=True, text=True, timeout=15)
            if int(getattr(result, "returncode", 1)) != 0:
                return None
            first_line = str(getattr(result, "stdout", "") or "").splitlines()
            return first_line[0].strip() if first_line else None
        except (OSError, subprocess.SubprocessError):
            return None

    @staticmethod
    def _executable(folder: Path, name: str) -> Path | None:
        for candidate in (folder / f"{name}.exe", folder / name):
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _valid_path(value: Any) -> str | None:
        if not value:
            return None
        path = Path(str(value)).expanduser()
        return str(path.resolve()) if path.is_file() else None

    def _load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, values: dict[str, Any]) -> None:
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, indent=2), encoding="utf-8")
        temporary.replace(self.config_path)
