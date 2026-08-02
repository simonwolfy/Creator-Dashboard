from pathlib import Path

from creator_intelligence.core.privacy_audit import audit_repository


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
    ):
        assert rule in text
