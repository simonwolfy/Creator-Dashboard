from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable


FORBIDDEN_RUNTIME_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".mp4", ".mkv", ".mov", ".webm",
    ".wav", ".flac", ".mp3", ".m4a", ".srt", ".vtt", ".parquet",
}

SECRET_NAME_PATTERNS = (
    re.compile(r"client_?secrets?", re.I),
    re.compile(r"credentials?", re.I),
    re.compile(r"oauth", re.I),
    re.compile(r"(?:twitch|youtube).*token", re.I),
    re.compile(r"token.*(?:twitch|youtube)", re.I),
)

CREATOR_IDENTITY_PATTERNS = (
    re.compile(r"\bsimonwolfy\b", re.I),
    re.compile(r"\bhunter\s+anderson\b", re.I),
)

SOURCE_SUFFIXES = {".py", ".toml", ".json", ".yaml", ".yml", ".md"}
ALLOWED_IDENTITY_PATHS = {
    "README.md",
    "docs/PRIVACY_AND_SHARING.md",
}


@dataclass(frozen=True)
class PrivacyFinding:
    path: str
    reason: str


def audit_repository(root: str | Path, paths: Iterable[str | Path] | None = None) -> list[PrivacyFinding]:
    """Report creator-specific data, credentials, or identity hard-coding.

    This is intentionally conservative. It is designed for release checks and
    never reads ignored runtime databases or media files.
    """
    root_path = Path(root).resolve()
    candidates = [Path(value) for value in paths] if paths is not None else [
        path.relative_to(root_path)
        for path in root_path.rglob("*")
        if path.is_file() and ".git" not in path.parts
    ]

    findings: list[PrivacyFinding] = []
    for relative in candidates:
        relative = Path(relative)
        normalized = relative.as_posix()
        name = relative.name

        if relative.suffix.lower() in FORBIDDEN_RUNTIME_SUFFIXES:
            findings.append(PrivacyFinding(normalized, "creator-owned runtime artifact"))
            continue

        if any(pattern.search(name) for pattern in SECRET_NAME_PATTERNS):
            findings.append(PrivacyFinding(normalized, "credential or OAuth material"))
            continue

        if relative.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if normalized in ALLOWED_IDENTITY_PATHS:
            continue

        try:
            text = (root_path / relative).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(pattern.search(text) for pattern in CREATOR_IDENTITY_PATTERNS):
            findings.append(PrivacyFinding(normalized, "creator identity hard-coded in product source"))

    return findings
