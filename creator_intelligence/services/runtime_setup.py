from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable

from creator_intelligence.services.ffmpeg_manager import FFmpegManagerService


SETUP_SCHEMA_VERSION = 1
DEFAULT_WHISPER_MODEL = "base"
REQUIRED_MODEL_FILES = ("model.bin", "config.json", "tokenizer.json")
SOURCE_RUNTIME_MODULES = (
    "PySide6", "pandas", "numpy", "sklearn", "matplotlib", "openpyxl",
    "reportlab", "keyring", "googleapiclient", "google_auth_oauthlib",
    "faster_whisper",
)


def default_runtime_root(environ=None, home=None) -> Path:
    environ = environ or os.environ
    if os.name == "nt" and environ.get("LOCALAPPDATA"):
        root = Path(environ["LOCALAPPDATA"])
    else:
        root = Path(environ.get("XDG_CACHE_HOME") or (Path(home or Path.home()) / ".cache"))
    return root / "Creator Intelligence" / "runtime"


def whisper_model_path(model_name=DEFAULT_WHISPER_MODEL, runtime_root=None) -> Path:
    return Path(runtime_root or default_runtime_root()) / "models" / f"faster-whisper-{model_name}"


def whisper_model_ready(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in REQUIRED_MODEL_FILES)


@dataclass(frozen=True)
class RuntimeComponent:
    key: str
    name: str
    ready: bool
    required_for: str
    detail: str


@dataclass(frozen=True)
class RuntimeSetupResult:
    components: tuple[RuntimeComponent, ...]
    completed: bool
    state_path: str


class RuntimeSetupService:
    """Prepare non-secret, machine-wide runtime assets used by every workspace."""

    def __init__(
        self,
        runtime_root=None,
        *,
        ffmpeg=None,
        module_finder: Callable[[str], Any] | None = None,
        model_downloader: Callable[..., Any] | None = None,
        frozen: bool | None = None,
    ):
        self.runtime_root = Path(runtime_root or default_runtime_root())
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.runtime_root / "runtime_setup.json"
        self.module_finder = module_finder or importlib.util.find_spec
        self.model_downloader = model_downloader
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        runtime_db = SimpleNamespace(path=self.runtime_root / "data" / "runtime.db")
        self.ffmpeg = ffmpeg or FFmpegManagerService(runtime_db)

    def components(self, model_name=DEFAULT_WHISPER_MODEL) -> tuple[RuntimeComponent, ...]:
        missing = [name for name in SOURCE_RUNTIME_MODULES if self.module_finder(name) is None]
        python_ready = self.frozen or not missing
        python_detail = (
            f"Bundled with {Path(sys.executable).name}; no separate Python install is required."
            if self.frozen else
            f"Ready in {sys.executable}." if python_ready else
            "Missing Python packages: " + ", ".join(missing)
        )
        whisper_runtime_ready = self.module_finder("faster_whisper") is not None
        ffmpeg = self.ffmpeg.status()
        model = whisper_model_path(model_name, self.runtime_root)
        model_ready = whisper_model_ready(model)
        return (
            RuntimeComponent("python", "Python and application libraries", python_ready, "the application", python_detail),
            RuntimeComponent(
                "whisper_runtime", "Whisper transcription engine", whisper_runtime_ready,
                "local transcription", "faster-whisper is ready." if whisper_runtime_ready else
                "faster-whisper is missing. Run source Setup Once again."
            ),
            RuntimeComponent(
                "ffmpeg", "FFmpeg and FFprobe", ffmpeg.ready, "audio and video processing",
                ffmpeg.message if not ffmpeg.ready else f"Ready from {ffmpeg.source}."
            ),
            RuntimeComponent(
                "whisper_model", f"Whisper {model_name} model", model_ready, "local transcription",
                str(model) if model_ready else "Model files have not been downloaded yet."
            ),
        )

    def status(self, model_name=DEFAULT_WHISPER_MODEL) -> RuntimeSetupResult:
        components = self.components(model_name)
        return RuntimeSetupResult(
            components=components,
            completed=all(component.ready for component in components),
            state_path=str(self.state_path),
        )

    def install(
        self,
        *,
        install_ffmpeg=True,
        download_model=True,
        model_name=DEFAULT_WHISPER_MODEL,
        progress: Callable[[int, str], None] | None = None,
    ) -> RuntimeSetupResult:
        notify = progress or (lambda _percent, _message: None)
        current = {component.key: component for component in self.components(model_name)}
        if not current["python"].ready or not current["whisper_runtime"].ready:
            raise RuntimeError(
                "The application Python runtime is incomplete. Source users should rerun SETUP_ONCE.bat; "
                "installed users should reinstall Creator Intelligence."
            )

        notify(10, "Checking FFmpeg and FFprobe")
        if install_ffmpeg and not current["ffmpeg"].ready:
            notify(20, "Installing FFmpeg with Windows Package Manager")
            self.ffmpeg.install_with_winget()
        elif not install_ffmpeg and not current["ffmpeg"].ready:
            notify(25, "FFmpeg installation was skipped")

        model = whisper_model_path(model_name, self.runtime_root)
        if download_model and not whisper_model_ready(model):
            notify(45, f"Downloading the Whisper {model_name} model")
            model.parent.mkdir(parents=True, exist_ok=True)
            downloader = self.model_downloader or self._download_model
            downloader(model_name=model_name, destination=model)
            if not whisper_model_ready(model):
                raise RuntimeError("The Whisper download finished without all required model files.")
        elif not download_model and not whisper_model_ready(model):
            notify(60, "Whisper model download was skipped")

        notify(90, "Verifying installed components")
        result = self.status(model_name)
        self._save_state(result, model_name)
        notify(100, "Setup Once is complete" if result.completed else "Setup finished with unavailable components")
        return result

    @staticmethod
    def _download_model(*, model_name: str, destination: Path) -> None:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=f"Systran/faster-whisper-{model_name}",
            local_dir=str(destination),
        )

    def _save_state(self, result: RuntimeSetupResult, model_name: str) -> None:
        payload = {
            "schema_version": SETUP_SCHEMA_VERSION,
            "completed": result.completed,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "whisper_model": model_name,
            "components": [asdict(component) for component in result.components],
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Prepare Creator Intelligence local runtimes")
    parser.add_argument("--install", action="store_true", help="install FFmpeg and download the default Whisper model")
    parser.add_argument("--skip-ffmpeg", action="store_true")
    parser.add_argument("--skip-model", action="store_true")
    args = parser.parse_args(argv)
    service = RuntimeSetupService()
    if args.install:
        result = service.install(
            install_ffmpeg=not args.skip_ffmpeg,
            download_model=not args.skip_model,
            progress=lambda percent, message: print(f"[{percent:3d}%] {message}", flush=True),
        )
    else:
        result = service.status()
    for component in result.components:
        print(f"{'READY' if component.ready else 'MISSING'}: {component.name} — {component.detail}")
    return 0 if result.completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
