from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from creator_intelligence.services.runtime_setup import (
    REQUIRED_MODEL_FILES, RuntimeSetupService, default_runtime_root,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeFFmpeg:
    def __init__(self, ready=False):
        self.ready = ready
        self.installs = 0

    def status(self):
        return SimpleNamespace(
            ready=self.ready,
            source="test tools" if self.ready else "Not found",
            message="FFmpeg and FFprobe are ready." if self.ready else "FFmpeg was not found.",
        )

    def install_with_winget(self):
        self.installs += 1; self.ready = True
        return {"status": self.status()}


def all_modules(_name):
    return object()


def write_model(*, model_name, destination):
    assert model_name == "base"
    destination.mkdir(parents=True)
    for name in REQUIRED_MODEL_FILES:
        (destination / name).write_bytes(b"fixture")


def test_setup_installs_tools_downloads_model_and_persists_machine_state(tmp_path: Path):
    ffmpeg = FakeFFmpeg()
    progress = []
    service = RuntimeSetupService(
        tmp_path / "runtime", ffmpeg=ffmpeg, module_finder=all_modules,
        model_downloader=write_model, frozen=True,
    )

    result = service.install(progress=lambda percent, message: progress.append((percent, message)))

    assert result.completed is True
    assert ffmpeg.installs == 1
    assert progress[-1][0] == 100
    payload = json.loads(service.state_path.read_text(encoding="utf-8"))
    assert payload["completed"] is True
    assert payload["whisper_model"] == "base"
    assert "token" not in service.state_path.read_text(encoding="utf-8").lower()


def test_setup_is_idempotent_when_components_are_ready(tmp_path: Path):
    ffmpeg = FakeFFmpeg(ready=True)
    downloads = []

    def downloader(**kwargs):
        downloads.append(kwargs); write_model(**kwargs)

    service = RuntimeSetupService(
        tmp_path / "runtime", ffmpeg=ffmpeg, module_finder=all_modules,
        model_downloader=downloader, frozen=True,
    )
    service.install(); service.install()

    assert ffmpeg.installs == 0
    assert len(downloads) == 1


def test_incomplete_source_python_environment_has_actionable_failure(tmp_path: Path):
    service = RuntimeSetupService(
        tmp_path / "runtime", ffmpeg=FakeFFmpeg(True),
        module_finder=lambda name: None if name == "faster_whisper" else object(),
        frozen=False,
    )
    result = service.status()
    assert result.completed is False
    assert any(component.key == "whisper_runtime" and not component.ready for component in result.components)
    with pytest.raises(RuntimeError, match="SETUP_ONCE.bat"):
        service.install()


def test_default_runtime_root_uses_machine_local_cache(tmp_path: Path):
    root = default_runtime_root(environ={"XDG_CACHE_HOME": str(tmp_path / "cache")}, home=tmp_path)
    assert root == tmp_path / "cache" / "Creator Intelligence" / "runtime"


def test_source_setup_bootstraps_every_required_runtime_layer():
    batch = (ROOT / "SETUP_ONCE.bat").read_text(encoding="utf-8")
    script = (ROOT / "tools" / "setup_once.ps1").read_text(encoding="utf-8")
    spec = (ROOT / "CreatorIntelligence.spec").read_text(encoding="utf-8")
    assert "tools\\setup_once.ps1" in batch
    assert "Python.Python.3.12" in script
    assert "-m venv" in script
    assert "requirements.txt" in script
    assert "runtime_setup --install" in script
    for package in ("faster_whisper", "ctranslate2", "huggingface_hub", "tokenizers"):
        assert f'"{package}"' in spec
