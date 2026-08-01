# Architecture Overview

Creator Intelligence uses a modular desktop architecture.

## Layers

- `creator_intelligence/core`: application lifecycle, configuration, workspaces, module loading, dependency injection, diagnostics
- `creator_intelligence/data`: SQLite access and migrations
- `creator_intelligence/services`: business logic
- `creator_intelligence/modules`: module registration and navigation bindings
- `creator_intelligence/ui`: PySide6 desktop interface
- `creator_intelligence/repositories`: focused persistence abstractions
- `tests`: application and integration tests

## Startup ownership

`CreatorIntelligenceApplication` is the composition root. It prepares one `ApplicationRuntime`, which is passed into the main window.

The UI must not create databases, load modules, or perform migrations independently.

## Dependency direction

UI and modules depend on services registered through the application context. Services may depend on repositories and database abstractions. Core code must not depend on individual feature pages.

## Branch workflow

- `main`: stable releases
- `develop`: integrated development
- `feature/*`: isolated feature work merged through pull requests
