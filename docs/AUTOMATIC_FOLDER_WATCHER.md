# Automatic Folder Watcher

Phase 8.6 introduces a persistent local-folder discovery and reconciliation layer.

## Architecture

`FolderWatcherService` stores watched-folder configuration in `watched_folders`. Each scan enumerates eligible files, creates or updates canonical `managed_assets`, and records file state in `watched_folder_assets`. Every scan produces a durable `folder_scan_runs` record for diagnostics.

The first release intentionally uses explicit on-demand polling rather than a continuously running OS watcher. This keeps startup deterministic and avoids importing partially written OBS recordings. Background scheduling and file-stability delays can be layered onto the same scan API later.

## Reconciliation behavior

- New files create managed assets.
- Existing unchanged files are verified without duplication.
- Size or modification-time changes refresh the asset record.
- Files no longer present are marked `Missing`; records are preserved.
- Disabled folders are excluded from `scan_all()`.
- Include and exclude extension filters are normalized case-insensitively.
- SHA-256 calculation is optional because large VODs can be expensive to hash.
- Folder-level errors are stored and returned without crashing the application.

## UI

The Folder Watcher page allows users to add local directories, inspect configuration and errors, run all enabled watchers, and review aggregate scan results. It is registered in the existing Content module, so the application remains at 21 modules.
