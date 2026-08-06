# Windows builds and releases

## Local build

Install Python 3.12, the application requirements, the build requirements, and Inno Setup 6. Then run:

```powershell
pip install -r requirements.txt -r requirements-build.txt
.\tools\build_release.ps1
```

The standalone app is written to `dist/CreatorIntelligence`. The signed-ready installer and SHA-256 checksum are written to `release`.

For a quick standalone build without the installer, run `.\tools\build_release.ps1 -SkipInstaller`.

## FFmpeg

FFmpeg is deliberately not bundled. On first use, open the FFmpeg settings page to detect an existing copy, select a local `bin` folder, or use the guided Winget installation.

## Upgrades and uninstall

The installer replaces only application files. Creator workspaces remain in the user-selected location. Before an existing database receives schema migrations, the app writes a `pre_upgrade` SQLite backup to the workspace `backups` folder. The workspace metadata records the application version after startup succeeds.

Uninstalling does not delete creator workspaces. Remove a workspace manually only after confirming its backups and exports are no longer required.

## GitHub releases

Pushing a `v*` tag runs regression tests, scans the current tree and full Git history for private artifacts, builds the app and installer, emits checksums, and creates a GitHub release. The history gate intentionally blocks publication until legacy databases and workspace metadata have been purged from shared Git history.
