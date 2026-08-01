# Phase 8.1A — Application Core

Creator Intelligence now starts through a central application core rather than allowing the UI to initialize services itself.

## Startup pipeline

The startup sequence is deterministic and recorded step by step:

1. Configure logging
2. Initialize the workspace
3. Load configuration
4. Open the database
5. Apply migrations
6. Create a startup backup when enabled
7. Load modules and services
8. Run startup diagnostics

Required-step failures stop startup. Optional-step failures are recorded and reported without preventing the application from opening.

## Shutdown pipeline

Shutdown steps run in reverse registration order. The current pipeline:

1. Emits the `application_closing` hook
2. Clears transient singleton services

Later background workers and integrations will register their own shutdown steps with the same lifecycle manager.

## Workspace layout

The existing repository remains the default workspace for backward compatibility. The manager creates and validates these folders:

- `data`
- `config`
- `logs`
- `cache`
- `assets`
- `exports`
- `backups`
- `temp`

`workspace.json` stores workspace metadata and a schema version. A later sprint will add workspace creation and switching in the UI.

## Runtime object

The application core produces one `ApplicationRuntime` object containing:

- workspace manager
- database
- settings
- application context
- module registry
- startup health checks
- lifecycle report

The main window consumes this runtime and no longer bootstraps modules independently.

## Extension points

Future services can access the application and workspace through the application context:

```python
application = context.get("application")
workspace = context.get("workspace")
```

The lifecycle manager also allows integrations and background workers to register safe startup and shutdown callbacks.
