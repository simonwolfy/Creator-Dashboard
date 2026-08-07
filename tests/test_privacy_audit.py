from pathlib import Path

import subprocess

from creator_intelligence.core.privacy_audit import (
    audit_git_history, audit_repository, main, tracked_paths,
)
from creator_intelligence.core.workspace import WorkspaceManager


def test_privacy_audit_flags_runtime_media_and_credentials(tmp_path: Path):
    (tmp_path / "creator.db").write_bytes(b"db")
    (tmp_path / "stream.mp4").write_bytes(b"video")
    (tmp_path / "youtube_token.json").write_text("{}", encoding="utf-8")

    findings = audit_repository(tmp_path)
    reasons = {finding.reason for finding in findings}

    assert "creator-owned runtime artifact" in reasons
    assert "credential or OAuth material" in reasons


def test_privacy_audit_flags_creator_identity_in_product_source(tmp_path: Path):
    package = tmp_path / "creator_intelligence"
    package.mkdir()
    (package / "settings.py").write_text(
        'DEFAULT_CREATOR = "SimonWolfy"',
        encoding="utf-8",
    )

    findings = audit_repository(tmp_path)

    assert findings == [
        findings[0].__class__(
            "creator_intelligence/settings.py",
            "creator identity hard-coded in product source",
        )
    ]


def test_privacy_audit_accepts_generic_product_source(tmp_path: Path):
    package = tmp_path / "creator_intelligence"
    package.mkdir()
    (package / "settings.py").write_text(
        'DEFAULT_WORKSPACE_NAME = "My Workspace"',
        encoding="utf-8",
    )

    assert audit_repository(tmp_path) == []


def test_privacy_audit_flags_secret_shapes_and_machine_paths_without_values(tmp_path: Path):
    (tmp_path / "unsafe.py").write_text(
        'TOKEN = "' + "ghp_" + 'abcdefghijklmnopqrstuvwxyz123456"\n'
        'PATH = "' + "C:" + '\\\\Users\\\\private-name\\\\Videos"',
        encoding="utf-8",
    )
    findings = audit_repository(tmp_path)
    assert {finding.reason for finding in findings} == {
        "credential-shaped content", "machine-specific user path",
    }


def test_example_configuration_names_are_release_safe(tmp_path: Path):
    (tmp_path / ".env.example").write_text("API_KEY=replace-me", encoding="utf-8")
    (tmp_path / "credentials.example.json").write_text('{"token":"replace-me"}', encoding="utf-8")
    assert audit_repository(tmp_path) == []


def test_security_source_names_are_safe_but_credential_json_is_not(tmp_path: Path):
    (tmp_path / "credential_vault.py").write_text("class Vault: pass",encoding="utf-8")
    (tmp_path / "credentials.json").write_text("{}",encoding="utf-8")
    findings=audit_repository(tmp_path)
    assert [finding.path for finding in findings]==["credentials.json"]


def test_history_audit_reports_old_database_by_path_only(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Privacy Test"], cwd=tmp_path, check=True)
    data = tmp_path / "data"; data.mkdir(); (data / "creator.db").write_bytes(b"private")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=tmp_path, check=True, capture_output=True)
    (data / "creator.db").unlink(); subprocess.run(["git", "add", "-u"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "remove"], cwd=tmp_path, check=True, capture_output=True)
    findings = audit_git_history(tmp_path)
    assert findings == [findings[0].__class__(
        "history:data/creator.db", "sensitive runtime artifact remains in Git history"
    )]


def test_gitignore_contains_creator_data_boundaries():
    text = Path(".gitignore").read_text(encoding="utf-8")

    for rule in (
        "data/",
        "workspaces/",
        "*.db",
        "*.mp4",
        "*.wav",
        "*.srt",
        "credentials*.json",
        "token*.json",
        ".env.*",
        "imports/",
        "assets/",
        "*.csv",
        "*.log",
    ):
        assert rule in text


def test_repository_tracks_no_runtime_workspace_or_database():
    paths = {path.as_posix() for path in tracked_paths(".")}
    assert "workspace.json" not in paths
    assert not any(Path(path).suffix.lower() in {".db", ".sqlite", ".sqlite3"} for path in paths)


def test_fresh_workspace_uses_neutral_empty_defaults(tmp_path: Path):
    paths = WorkspaceManager(tmp_path / "fresh").initialize()
    metadata = WorkspaceManager(paths.root).validate()
    assert metadata["name"] == "My Workspace"
    assert paths.database.exists() is False
    assert list(paths.exports.iterdir()) == []


def test_tracked_repository_privacy_command_passes():
    assert main(["."]) == 0
