from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from packaging.version import Version

from creator_intelligence.core.processes import windowless_run
from creator_intelligence.core.privacy_audit import audit_repository, tracked_paths
from creator_intelligence.core.versioning import APPLICATION_VERSION, WORKSPACE_SCHEMA_VERSION


def verify_source(root: Path, *, tag: str | None = None) -> list[str]:
    """Verify the source-to-installer release contract without using creator data."""
    root = Path(root).resolve()
    checks = []
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = str(pyproject["project"]["version"])
    if Version(package_version) != Version(APPLICATION_VERSION):
        raise RuntimeError(
            f"pyproject version {package_version} does not match {APPLICATION_VERSION}."
        )
    checks.append("canonical application and package versions match")

    if tag and tag != f"v{APPLICATION_VERSION}":
        raise RuntimeError(
            f"Release tag {tag!r} must be exactly v{APPLICATION_VERSION}."
        )
    if tag:
        checks.append("release tag matches the canonical version")

    installer = (root / "installer" / "CreatorIntelligence.iss").read_text(encoding="utf-8")
    if "#ifndef MyAppVersion" not in installer or "#define MyAppVersion" not in installer:
        raise RuntimeError("The installer must accept the canonical version from the build.")
    fallback = re.search(r'#define MyAppVersion\s+"([^"]+)"', installer)
    if not fallback or fallback.group(1) != APPLICATION_VERSION:
        raise RuntimeError("The installer fallback version does not match the canonical version.")
    rank_fallback = re.search(r'#define MyAppReleaseRank\s+"([^"]+)"', installer)
    if not rank_fallback or rank_fallback.group(1) != release_rank(APPLICATION_VERSION):
        raise RuntimeError("The installer fallback release rank does not match the canonical version.")
    if "CloseApplications=yes" not in installer or "RestartApplications=no" not in installer:
        raise RuntimeError("The installer does not declare safe application replacement behavior.")
    if (
        "function InitializeSetup(): Boolean" not in installer
        or "CompareStr" not in installer
        or "SuppressibleMsgBox" not in installer
    ):
        raise RuntimeError("The installer does not prevent an older release replacing a newer one.")
    checks.append("installer accepts the canonical version and prevents downgrades")

    workflow = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    signing_contract = (
        "WINDOWS_SIGNING_CERTIFICATE_BASE64",
        "WINDOWS_SIGNING_CERTIFICATE_PASSWORD",
        "Get-AuthenticodeSignature",
        "startsWith(github.ref, 'refs/tags/')",
    )
    missing_signing = [value for value in signing_contract if value not in workflow]
    if missing_signing:
        raise RuntimeError("The tagged release signing gate is incomplete.")
    checks.append("tagged releases require and verify Authenticode signatures")

    ignored_tracked = windowless_run(
        ["git", "ls-files", "-ci", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.splitlines()
    if ignored_tracked:
        raise RuntimeError("Ignored runtime files are still tracked: " + ", ".join(ignored_tracked))
    checks.append("no ignored runtime files are tracked")

    findings = audit_repository(root, tracked_paths(root))
    if findings:
        raise RuntimeError(
            "Tracked privacy audit failed: "
            + ", ".join(f"{finding.path} ({finding.reason})" for finding in findings)
        )
    checks.append("tracked release files pass the privacy audit")

    json.loads((root / "workspace.example.json").read_text(encoding="utf-8"))
    json.loads((root / "config" / "settings.example.json").read_text(encoding="utf-8"))
    checks.append("fresh-workspace example configuration is valid")
    privacy = (root / "PRIVACY.md").read_text(encoding="utf-8")
    for heading in ("## Data stored on your computer", "## Network requests", "## Retention and deletion"):
        if heading not in privacy:
            raise RuntimeError(f"Public privacy notice is missing {heading!r}.")
    checks.append("public privacy notice covers storage, network use, and deletion")
    return checks


def verify_artifacts(release_dir: Path, *, expected_version: str = APPLICATION_VERSION) -> list[str]:
    release_dir = Path(release_dir).resolve()
    installer_name = f"CreatorIntelligence-{expected_version}-windows-x64-setup.exe"
    installer = release_dir / installer_name
    checksum = release_dir / f"{installer_name}.sha256"
    manifest = release_dir / f"CreatorIntelligence-{expected_version}-release.json"
    expected_files = {installer.name, checksum.name, manifest.name}
    actual_files = {path.name for path in release_dir.iterdir() if path.is_file()}
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        unexpected = sorted(actual_files - expected_files)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise RuntimeError("Release asset allowlist mismatch (" + "; ".join(details) + ").")
    expected = _checksum_value(checksum.read_text(encoding="ascii"), installer_name)
    actual = _sha256(installer)
    if actual != expected:
        raise RuntimeError("The release installer does not match its SHA-256 file.")
    if installer.stat().st_size < 1024:
        raise RuntimeError("The installer artifact is unexpectedly small.")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    _verify_manifest(payload, installer, actual, expected_version)
    return [
        "exact release asset allowlist is present",
        "installer SHA-256 checksum is valid",
        "release provenance manifest is valid",
    ]


def verify_bundle(bundle_dir: Path) -> list[str]:
    """Reject creator runtime data and prove required packaged resources are present."""
    bundle_dir = Path(bundle_dir).resolve()
    executable = bundle_dir / "CreatorIntelligence.exe"
    module_manifest = bundle_dir / "_internal" / "config" / "modules.json"
    if not executable.is_file() or not module_manifest.is_file():
        raise RuntimeError("The standalone bundle is missing its executable or module manifest.")
    top_level = {path.name for path in bundle_dir.iterdir()}
    if top_level != {"CreatorIntelligence.exe", "_internal"}:
        raise RuntimeError("The standalone bundle contains unexpected top-level files or folders.")
    forbidden_names = {
        "creator_intelligence.db",
        "installation.json",
        "settings.json",
        "update_state.json",
        "workspace.json",
    }
    findings = [
        path.relative_to(bundle_dir).as_posix()
        for path in bundle_dir.rglob("*")
        if path.is_file() and path.name.lower() in forbidden_names
    ]
    if findings:
        raise RuntimeError("Packaged runtime data is forbidden: " + ", ".join(findings))
    return [
        "standalone executable and module manifest are present",
        "standalone bundle contains no creator runtime state",
    ]


def write_manifest(
    release_dir: Path,
    *,
    commit: str | None = None,
    built_at: datetime | None = None,
) -> Path:
    release_dir = Path(release_dir).resolve()
    installer_name = f"CreatorIntelligence-{APPLICATION_VERSION}-windows-x64-setup.exe"
    installer = release_dir / installer_name
    checksum = release_dir / f"{installer_name}.sha256"
    if not installer.is_file() or not checksum.is_file():
        raise RuntimeError("Create the installer and checksum before the release manifest.")
    digest = _checksum_value(checksum.read_text(encoding="ascii"), installer_name)
    if _sha256(installer) != digest:
        raise RuntimeError("Cannot write a manifest for an installer with an invalid checksum.")
    commit = commit or windowless_run(
        ["git", "rev-parse", "HEAD"],
        cwd=release_dir.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise RuntimeError("The release manifest needs a full 40-character Git commit SHA.")
    timestamp = (built_at or datetime.now(UTC)).astimezone(UTC).isoformat()
    payload = {
        "schema_version": 1,
        "application": "Creator Intelligence",
        "version": APPLICATION_VERSION,
        "tag": f"v{APPLICATION_VERSION}",
        "channel": "preview" if Version(APPLICATION_VERSION).is_prerelease else "stable",
        "commit": commit.lower(),
        "built_at": timestamp,
        "minimum_workspace_schema": WORKSPACE_SCHEMA_VERSION,
        "installer": {
            "name": installer_name,
            "size_bytes": installer.stat().st_size,
            "sha256": digest,
            "checksum_asset": f"{installer_name}.sha256",
        },
    }
    path = release_dir / f"CreatorIntelligence-{APPLICATION_VERSION}-release.json"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return path


def _verify_manifest(
    payload: object,
    installer: Path,
    digest: str,
    expected_version: str,
) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError("The release manifest must be a JSON object.")
    installer_data = payload.get("installer")
    checks = {
        "schema_version": payload.get("schema_version") == 1,
        "application": payload.get("application") == "Creator Intelligence",
        "version": payload.get("version") == expected_version,
        "tag": payload.get("tag") == f"v{expected_version}",
        "channel": payload.get("channel")
        == ("preview" if Version(expected_version).is_prerelease else "stable"),
        "commit": bool(re.fullmatch(r"[0-9a-f]{40}", str(payload.get("commit") or ""))),
        "built_at": _valid_timestamp(payload.get("built_at")),
        "workspace_schema": payload.get("minimum_workspace_schema") == WORKSPACE_SCHEMA_VERSION,
        "installer": isinstance(installer_data, dict)
        and installer_data.get("name") == installer.name
        and installer_data.get("checksum_asset") == installer.name + ".sha256"
        and installer_data.get("size_bytes") == installer.stat().st_size
        and installer_data.get("sha256") == digest,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError("Release manifest validation failed: " + ", ".join(failed))


def _valid_timestamp(value: object) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.tzinfo is not None
    except (TypeError, ValueError):
        return False


def _checksum_value(text: str, expected_name: str) -> str:
    matches = []
    for line in text.splitlines():
        match = re.fullmatch(r"\s*([0-9A-Fa-f]{64})\s+\*?(.+?)\s*", line)
        if match and match.group(2) == expected_name:
            matches.append(match.group(1).lower())
    if len(matches) != 1:
        raise RuntimeError("The checksum file must name the installer exactly once.")
    return matches[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def release_rank(value: str) -> str:
    """Return a fixed-width ordering key for installer downgrade prevention."""
    version = Version(value)
    if version.local is not None or len(version.release) != 3:
        raise ValueError("Release versions need major, minor, and patch components without local data.")
    major, minor, patch = version.release
    if any(component > 99999 for component in (major, minor, patch)):
        raise ValueError("Release version components must be at most five digits.")
    if version.dev is not None:
        stage, serial = 0, version.dev
    elif version.pre is not None:
        stage = {"a": 1, "b": 2, "rc": 3}[version.pre[0]]
        serial = version.pre[1]
    elif version.post is not None:
        stage, serial = 5, version.post
    else:
        stage, serial = 4, 0
    if serial > 99999:
        raise ValueError("Release version serials must be at most five digits.")
    return f"{major:05d}{minor:05d}{patch:05d}{stage}{serial:05d}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify Creator Intelligence release inputs.")
    parser.add_argument("--source", action="store_true", help="verify the source release contract")
    parser.add_argument("--artifacts", type=Path, help="verify a built release directory")
    parser.add_argument("--bundle", type=Path, help="verify a standalone packaged directory")
    parser.add_argument("--write-manifest", type=Path, help="write release provenance metadata")
    parser.add_argument("--commit", help="full Git commit SHA for the release manifest")
    parser.add_argument("--tag", help="require an exact canonical release tag")
    parser.add_argument("--print-version", action="store_true", help="print the canonical version")
    parser.add_argument(
        "--print-release-rank",
        action="store_true",
        help="print the fixed-width installer release rank",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if args.print_version:
        print(APPLICATION_VERSION)
        return 0
    if args.print_release_rank:
        print(release_rank(APPLICATION_VERSION))
        return 0
    checks = []
    if args.write_manifest:
        print(write_manifest(args.write_manifest, commit=args.commit))
    if args.source or not (args.artifacts or args.bundle or args.write_manifest):
        checks.extend(verify_source(args.root, tag=args.tag))
    if args.bundle:
        checks.extend(verify_bundle(args.bundle))
    if args.artifacts:
        checks.extend(verify_artifacts(args.artifacts))
    for check in checks:
        print(f"PASS: {check}")
    print(f"Release verification passed with {len(checks)} check(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
