# Phase 8.7.1 — Google Drive Foundation

This phase establishes Google OAuth authentication and connection testing without syncing or downloading files.

## Security model

- OAuth access and refresh tokens are stored through Python `keyring` in the operating-system credential vault.
- SQLite stores only non-secret metadata: client-secrets path, account identity, status, timestamps, and errors.
- The OAuth client-secrets JSON remains at the location selected by the user and must not be committed to Git.
- The requested scope is read-only Drive metadata access.

## User flow

1. Open **Google Drive** in Creator Intelligence.
2. Select a Google OAuth desktop client-secrets JSON file.
3. Click **Connect Google Drive**.
4. Complete authorization in the browser.
5. Creator Intelligence reads the connected account profile and records connection status.
6. Use **Test connection** to verify the stored credentials and refresh them when necessary.
7. Use **Disconnect** to remove the token from the credential vault.

## Architecture

`GoogleDriveService` owns configuration, OAuth, secure token storage, profile testing, and status persistence. OAuth and Drive factories are injectable so tests do not require live credentials or network access.

Migration 7 creates a singleton `google_drive_connections` record. No token material is stored in that table.

## Deferred work

- Drive folder browsing and mappings
- metadata reconciliation into managed assets
- incremental synchronization
- optional file downloads
- scheduled background synchronization
