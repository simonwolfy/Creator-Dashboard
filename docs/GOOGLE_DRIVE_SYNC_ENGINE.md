# Google Drive Sync Engine

Phase 8.7.3a introduces a provider-neutral, read-only enumeration engine.

## Responsibilities

- paginated folder listing
- optional recursive traversal
- progress callbacks after each page
- cooperative cancellation with partial results
- bounded exponential-backoff retries for transient failures
- normalized provider items for later persistence and reconciliation

## Boundaries

This phase does not write Drive metadata to SQLite and does not create or update managed assets. Those responsibilities remain in 8.7.3b and 8.7.3c. The engine performs no file downloads.

## Provider contract

A provider implements `list_folder_page(folder_id, page_token)` and returns a dictionary containing `items` and an optional `next_page_token`. The Google Drive adapter translates Drive v3 file responses into that contract.

## Safety

The engine uses the existing read-only Google Drive metadata scope. Cancellation is checked before folders and pages. Retry attempts are bounded and only applied to transient network, quota, and server failures.
