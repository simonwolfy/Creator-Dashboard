# Windows builds and releases

## Local build

Install Python 3.12, the application requirements, the pinned build requirements, and Inno Setup 6.7.1. Then run:

```powershell
pip install -r requirements.txt -r requirements-build.txt
.\tools\build_release.ps1
```

The standalone app is written to `dist/CreatorIntelligence`. The unsigned local-test installer, SHA-256 checksum, and JSON provenance manifest are written to `release`. The build also runs the packaged startup/OAuth loopback smoke test and verifies the exact three-file release allowlist.

For a quick standalone build without the installer, run `.\tools\build_release.ps1 -SkipInstaller`.

## First-run local processing setup

Python and the application libraries are bundled in the installed application. FFmpeg and the Whisper base model are deliberately prepared after installation so the installer stays smaller and the machine-specific runtime can be repaired without reinstalling the app. On first launch, run **Setup Once** when prompted. The same setup can be checked or retried later under **Settings > Local processing setup**.

## Upgrades and uninstall

The installer replaces only application files, rejects attempts to install an older version over a newer one, and never owns creator workspaces. Before an existing database receives schema migrations, the app writes a `pre_upgrade` SQLite backup to the workspace `backups` folder. The workspace metadata records the application version after startup succeeds.

Uninstalling does not delete creator workspaces. Remove a workspace manually only after confirming its backups and exports are no longer required.

## GitHub releases

Pushing an exact canonical `v*` tag runs regression tests, scans the current tree and full Git history for private artifacts, builds and smoke-tests the app and installer, performs clean install, downgrade-rejection, N-1 workspace upgrade, reinstall, and uninstall checks, emits checksums and provenance metadata, and creates a **draft** GitHub release. Tagged builds require the `WINDOWS_SIGNING_CERTIFICATE_BASE64` and `WINDOWS_SIGNING_CERTIFICATE_PASSWORD` repository secrets; the workflow signs and verifies both Windows executables before release creation. Preview versions are marked as GitHub prereleases. Public-repository builds also receive a GitHub artifact attestation. The history gate intentionally blocks release creation if private runtime artifacts are reachable from shared Git history. Complete [`PUBLIC_RELEASE_CHECKLIST.md`](PUBLIC_RELEASE_CHECKLIST.md) before publishing the draft.

## Automatic update checks

The installed app checks GitHub Releases at most once per day after startup. This work runs in the background and any network failure is nonfatal. Stable is the default channel; preview releases are opt-in under **Settings > Software updates**. A creator may disable automatic checks, check manually, or skip one version.

The app accepts only an exact versioned Windows installer and its exact companion SHA-256 asset. A verified installer can be downloaded to the workspace temporary update folder, but it is never run silently. Source checkouts do not attempt to update themselves.
