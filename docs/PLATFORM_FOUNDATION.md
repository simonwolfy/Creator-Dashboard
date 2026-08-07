# Phase 8.1B — Platform Foundation

This sprint strengthens the Version 5 desktop platform without changing creator-facing workflows.

## Developer tooling

- `pyproject.toml` defines packaging, pytest, and Ruff configuration.
- `requirements-dev.txt` installs runtime dependencies, pytest, and Ruff.
- Generated databases, logs, caches, exports, backups, and workspace settings remain ignored by Git.

## Settings

Workspace settings are stored atomically in a versioned envelope. Values are validated before saving and invalid settings produce a clear `SettingsValidationError` rather than being silently accepted.

## Database migrations

`MigrationManager` validates migration identifiers, reports pending migrations, applies each migration exactly once, and exposes structured migration history. `Database.migrate()` returns the migrations applied during the current startup.

## Diagnostics

Lifecycle steps record elapsed milliseconds. The application runtime exposes a `DiagnosticsSnapshot` containing application and Python versions, platform, workspace, database integrity, migration state, module state, health issues, and startup duration.

## Logging

Logging setup is idempotent. Matplotlib, Pillow, and fontTools informational noise is suppressed while warnings and errors remain visible.

## Validation

Run:

```console
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check creator_intelligence tests
python -m creator_intelligence
```
