# Creator Intelligence 5.0 — Application Core

Creator Intelligence is a desktop creator operating system for Twitch, YouTube, long-form VOD analysis, highlight detection, production planning, and review workflows.

## Version 5 development

Phase 8.1A introduces the central desktop application framework:

- deterministic startup and shutdown pipelines
- application lifecycle state and step reporting
- a canonical application runtime
- workspace initialization and validation
- versioned workspace metadata
- centralized configuration, database, backup, module, and diagnostic startup
- application and workspace services exposed through dependency injection
- a main window that consumes the prepared runtime instead of initializing services itself

The existing Phase 7 features remain available, including transcription, scene intelligence, highlight scoring and learning, production management, editor workspace, and review/revision tracking.

## Run

On the first launch, a welcome wizard asks where to create your local workspace,
checks required and optional media tools, explains the privacy boundary, and
lets you skip platform connections until later.

On Windows, run:

```text
START_CREATOR_INTELLIGENCE.bat
```

Or from a configured Python environment:

```bash
python -m creator_intelligence
```

## Tests

```bash
python -m pytest
```

See [`docs/APPLICATION_CORE.md`](docs/APPLICATION_CORE.md) for the Phase 8.1A architecture.
See [`docs/FIRST_RUN_ONBOARDING.md`](docs/FIRST_RUN_ONBOARDING.md) for fresh-install and existing-workspace behavior.
