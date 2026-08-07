from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from creator_intelligence.services.ffmpeg_manager import FFmpegManagerService


class FakeDB:
    def __init__(self, path: Path):
        self.path = path


def _make_tools(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    ffmpeg = folder / "ffmpeg.exe"
    ffprobe = folder / "ffprobe.exe"
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    return ffmpeg, ffprobe


def _runner(command, **_kwargs):
    executable = Path(command[0]).name.casefold()
    if command[-1] == "-version":
        return SimpleNamespace(returncode=0, stdout=f"{executable} version test-build\n", stderr="")
    return SimpleNamespace(returncode=0, stdout="installed", stderr="")


def test_configure_bin_folder_persists_paths(tmp_path):
    db = FakeDB(tmp_path / "data" / "creator_intelligence.db")
    bin_folder = tmp_path / "ffmpeg" / "bin"
    ffmpeg, ffprobe = _make_tools(bin_folder)
    service = FFmpegManagerService(db, runner=_runner, which=lambda _name: None, environ={})

    status = service.configure_bin_folder(bin_folder)

    assert status.ready is True
    assert status.ffmpeg_path == str(ffmpeg.resolve())
    assert status.ffprobe_path == str(ffprobe.resolve())
    assert service.config_path.exists()


def test_status_uses_system_path_when_available(tmp_path):
    db = FakeDB(tmp_path / "data" / "creator_intelligence.db")
    ffmpeg, ffprobe = _make_tools(tmp_path / "path-tools")

    def which(name):
        return str(ffmpeg if name == "ffmpeg" else ffprobe if name == "ffprobe" else "") or None

    status = FFmpegManagerService(db, runner=_runner, which=which, environ={}).status()

    assert status.ready is True
    assert status.source == "System PATH"


def test_invalid_folder_is_rejected(tmp_path):
    db = FakeDB(tmp_path / "data" / "creator_intelligence.db")
    folder = tmp_path / "incomplete"
    folder.mkdir()
    (folder / "ffmpeg.exe").write_bytes(b"tool")
    service = FFmpegManagerService(db, runner=_runner, which=lambda _name: None, environ={})

    try:
        service.configure_bin_folder(folder)
    except ValueError as exc:
        assert "both ffmpeg and ffprobe" in str(exc)
    else:
        raise AssertionError("Expected invalid folder to be rejected")


def test_winget_install_command_is_bounded_and_silent(tmp_path):
    db = FakeDB(tmp_path / "data" / "creator_intelligence.db")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    service = FFmpegManagerService(
        db,
        runner=runner,
        which=lambda name: "C:/Windows/winget.exe" if name == "winget" else None,
        environ={},
    )
    result = service.install_with_winget()

    command, kwargs = calls[0]
    assert command[:4] == ["C:/Windows/winget.exe", "install", "--id", "Gyan.FFmpeg"]
    assert "--silent" in command
    assert kwargs["timeout"] == 900
    assert result["output"] == "installed"
