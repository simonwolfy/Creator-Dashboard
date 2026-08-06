from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import re
import subprocess
from typing import Iterable


FORBIDDEN_RUNTIME_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".mp4", ".mkv", ".mov", ".webm",
    ".wav", ".flac", ".mp3", ".m4a", ".srt", ".vtt", ".parquet",
    ".csv", ".tsv", ".jsonl", ".log",
}

SECRET_NAME_PATTERNS = (
    re.compile(r"client_?secrets?", re.I),
    re.compile(r"credentials?", re.I),
    re.compile(r"oauth", re.I),
    re.compile(r"(?:twitch|youtube).*token", re.I),
    re.compile(r"token.*(?:twitch|youtube)", re.I),
    re.compile(r"\.env(?:\.|$)", re.I),
    re.compile(r"(?:^|[._-])secrets?(?:[._-]|$)", re.I),
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

SECRET_CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
)
ABSOLUTE_USER_PATH = re.compile(r"(?:[A-Za-z]:\\+Users\\+[^\\\s]+|/(?:Users|home)/[^/\s]+)")
HISTORY_FORBIDDEN_NAMES = re.compile(
    r"(?i)(?:^|/)(?:workspace\.json|.*\.(?:db|sqlite|sqlite3|env|pem|key|p12|pfx)|"
    r"(?:credentials?|client.?secrets?|oauth|token).*\.json)$"
)


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

        safe_example = name == ".env.example" or ".example." in name
        if not safe_example and any(pattern.search(name) for pattern in SECRET_NAME_PATTERNS):
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
        if any(pattern.search(text) for pattern in SECRET_CONTENT_PATTERNS):
            findings.append(PrivacyFinding(normalized, "credential-shaped content"))
        if ABSOLUTE_USER_PATH.search(text):
            findings.append(PrivacyFinding(normalized, "machine-specific user path"))
        if (normalized != "creator_intelligence/core/privacy_audit.py"
                and normalized != "tests/test_privacy_audit.py"
                and any(pattern.search(text) for pattern in CREATOR_IDENTITY_PATTERNS)):
            findings.append(PrivacyFinding(normalized, "creator identity hard-coded in product source"))

    return findings


def tracked_paths(root: str | Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=Path(root), capture_output=True, check=True,
    )
    return [
        path for value in result.stdout.split(b"\0") if value
        if (path := Path(value.decode("utf-8"))).exists()
    ]


def audit_git_history(root: str | Path) -> list[PrivacyFinding]:
    """Report sensitive artifact names ever committed, without reading their values."""
    result = subprocess.run(
        ["git", "log", "--all", "--name-only", "--pretty=format:"],
        cwd=Path(root), capture_output=True, text=True, encoding="utf-8",
        errors="ignore", check=True,
    )
    paths = sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
    return [
        PrivacyFinding(f"history:{path}", "sensitive runtime artifact remains in Git history")
        for path in paths if HISTORY_FORBIDDEN_NAMES.search(path)
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Audit release files without displaying secret values.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--history", action="store_true", help="also flag sensitive filenames in Git history")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    findings = audit_repository(root, tracked_paths(root))
    if args.history:
        findings.extend(audit_git_history(root))
    for finding in findings:
        print(f"{finding.reason}: {finding.path}")
    if findings:
        print(f"Privacy audit failed with {len(findings)} finding(s). Values were not displayed.")
        return 1
    print("Privacy audit passed. No tracked release findings detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
