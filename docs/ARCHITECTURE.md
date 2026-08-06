# Architecture overview

Creator Intelligence uses a modular desktop architecture.

## Layers

- `creator_intelligence/core`: lifecycle, configuration, workspaces, module loading, dependency injection, and diagnostics
- `creator_intelligence/data`: SQLite access and ordered migrations
- `creator_intelligence/services`: business logic and subsystem boundaries
- `creator_intelligence/modules`: module registration and navigation bindings
- `creator_intelligence/ui`: PySide6 desktop interface
- `creator_intelligence/repositories`: focused persistence abstractions
- `tests`: application and integration tests

## Startup and modules

`config/modules.json` is the single ordered module manifest. Its schema is validated, dependencies must already be loaded, duplicate paths are rejected, and startup asserts the exact required module set. Missing configuration uses the same canonical list from `core.loader`; malformed configuration is an error rather than a silent fallback.

Persistent contract versions live in `core.versioning`. Application, module-manifest, and workspace versions must not be duplicated in feature modules. Database schema versions remain the ordered integer migration identifiers owned by `data`.

`CreatorIntelligenceApplication` is the composition root. It prepares one `ApplicationRuntime` for the main window. The UI must not create databases, load modules, or perform migrations independently. UI and modules depend on registered services; services may depend on repositories and database abstractions; core code must not depend on individual feature pages.

## Transcript

Transcript owns media-derived text, segments, speakers, timing, chapters, transcript edits, and clip-candidate boundaries. It exposes context to Packaging but does not own publishing decisions or creator preference weights.

## Packaging

Packaging owns event/context extraction, title and caption candidates, platform formatting, duplicate checks, experiments, package review, and approval state. External callers use `services.packaging`; the mixins behind that facade are internal implementation layers.

Packaging consumes transcript context and Creator DNA evidence. It emits package decisions and feedback evidence rather than directly mutating Creator DNA aggregates.

## Creator DNA

Creator DNA owns creator preference evidence, learned style profiles, evidence weighting, and recommendations. It consumes creator actions and published outcomes. It does not generate transcript facts, approve packages, or create production jobs.

## Production

Production owns projects, clip jobs, assignments, export settings, editor notes, status, and delivery. It accepts explicit handoffs from approved packaging or deliberate transcript actions. It does not reinterpret transcripts or choose packaging copy.

## UI variants

The active transcript route is `CreatorPackagingPage`, layered on `TranscriptProductionPage` and the transcript editor. `ProductionPipelinePage` and `IntegratedEditorWorkspacePage` are active extensions. Their base pages remain implementation dependencies and are not alternate navigation routes; removing them would break the canonical pages.

## Branch workflow

- `main`: stable releases
- `develop`: integrated development
- `feature/*`: isolated feature work merged through pull requests
