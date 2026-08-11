from __future__ import annotations

from pathlib import Path

from creator_intelligence.core import processes


ROOT = Path(__file__).resolve().parents[1]


class _StartupInfo:
    def __init__(self):
        self.dwFlags = 0
        self.wShowWindow = None


def test_windows_process_options_preserve_flags_and_hide_console(monkeypatch):
    monkeypatch.setattr(processes.os, "name", "nt")
    monkeypatch.setattr(processes.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(processes.subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(processes.subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(processes.subprocess, "STARTUPINFO", _StartupInfo, raising=False)

    options = processes.windowless_kwargs({"creationflags": 0x10, "text": True})

    assert options["creationflags"] == 0x08000010
    assert options["startupinfo"].dwFlags & 0x00000001
    assert options["startupinfo"].wShowWindow == 0
    assert options["text"] is True


def test_non_windows_process_options_are_unchanged(monkeypatch):
    monkeypatch.setattr(processes.os, "name", "posix")
    assert processes.windowless_kwargs({"text": True}) == {"text": True}


def test_runtime_process_launches_use_windowless_helpers():
    runtime_files = (
        "services/ffmpeg_manager.py",
        "services/processing_scheduler.py",
        "services/scene_intelligence.py",
        "services/transcripts.py",
        "services/video_metadata.py",
        "services/video_processing.py",
        "services/visual_scene_engine.py",
    )
    for relative in runtime_files:
        source = (ROOT / "creator_intelligence" / relative).read_text(encoding="utf-8")
        assert "subprocess.run(" not in source, relative
        assert "subprocess.Popen(" not in source, relative
        assert "windowless_" in source, relative
