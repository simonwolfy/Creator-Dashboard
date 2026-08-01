# Creator Intelligence 5.0.0-dev

## Phase 8.1A — Application Core

This development release moves application startup out of the UI and into a central lifecycle owner.

### Highlights

- Deterministic startup and shutdown
- Workspace metadata and standard folders
- Central application runtime
- Startup diagnostics
- Module and service loading through the application core
- Windows GitHub Actions test workflow

### Compatibility

The repository root remains the default workspace, preserving the current database, configuration, logs, backups, and existing Phase 7 modules.
