# Public release checklist

Creator Intelligence releases are built in two stages. GitHub Actions creates a
**draft** release after automated checks pass. A person publishes that draft only
after the credentialed Windows checks below are recorded. Drafts are deliberately
invisible to the in-app update checker.

## Automated release gates

The Windows release workflow must pass all of these checks:

- Full regression suite.
- Current-tree and full-Git-history privacy audit.
- Canonical app, package, installer, and Git tag version agreement.
- No ignored runtime file remains tracked.
- Clean PyInstaller build.
- Standalone packaged startup with all required modules.
- Packaged Google OAuth loopback callback round-trip, Google API import, and Windows keyring access.
- Fresh disposable workspace, database integrity, and idempotent migrations.
- Silent install on a clean Windows runner.
- Installed-app startup, simulated downgrade rejection, genuine N-1 schema upgrade with backup,
  same-version reinstall, uninstall, and external-workspace preservation.
- Authenticode signatures on both the standalone executable and installer for tagged builds.
- Exact Windows installer filename and companion SHA-256 file.
- Exact JSON manifest with version, tag, commit, size, checksum, and workspace-schema contract.
- Independent checksum verification before the draft release is created.
- GitHub build-provenance attestation when the repository is public.

Run the source gates locally with:

```powershell
python -m pytest
python -m creator_intelligence.core.release_verification --source
python -m creator_intelligence.core.privacy_audit --history
```

Build the same installer contract locally with:

```powershell
.\tools\build_release.ps1
```

## Credentialed clean-VM acceptance

Record the Windows edition/build, installer version, tester, date, and result for
each item. Use test creator accounts and synthetic media; never use production
credentials in screenshots, logs, or issue attachments.

- Install without Python, Git, or a source checkout present.
- Complete first-run setup in a new workspace and confirm it contains no creator content.
- Restart and confirm setup is not requested again.
- Disable the network, launch normally, and confirm update checking does not delay startup.
- Re-enable the network, use **Settings > Software updates > Check now**, and confirm the
  current stable/preview result is friendly.
- Connect Google Drive through its localhost browser callback; restart and test the connection.
- Connect Twitch and YouTube, perform an initial sync, disconnect, reconnect, and test revoked access.
- Exercise Instagram and TikTok only with approved test applications and document unavailable API
  capabilities as graceful limitations, not release failures.
- Expire or revoke each test token and confirm the UI gives a recoverable, redacted error.
- Inspect the application log and workspace database with the privacy audit helpers; confirm no token,
  authorization code, client secret, or API key was written.
- Install the new version over the previous public installer and open the existing synthetic workspace.
- Confirm a `pre_upgrade` database backup exists before pending migrations and that synthetic records remain.
- Uninstall and confirm the external workspace, exports, and backups remain intact.
- Verify the Authenticode signatures and expected publisher on both the installed executable and installer.
  A tagged build without a trusted signing certificate is a release failure.

## Publish decision

Before changing the GitHub release from draft to published:

- Automated release workflow: pass / fail
- Credentialed clean-VM matrix: pass / fail
- Upgrade from previous public version: pass / fail
- Installer SHA-256 independently verified: pass / fail
- Authenticode publisher and signatures independently verified: pass / fail
- Privacy statement reviewed for this version: pass / fail
- Known limitations included in release notes: yes / no
- Release approver and date recorded: yes / no

Do not publish with an unexplained failure. A platform feature that is unavailable
because the provider has not granted access must be described clearly and degrade
safely; it must never be worked around by storing credentials insecurely.
