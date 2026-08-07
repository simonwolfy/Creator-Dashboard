# Changelog

## 5.0.0-dev

### Public-release verification

- Added offline-safe automatic GitHub Release checks with stable and preview channels.
- Added exact Windows installer/checksum selection and verified installer downloads.
- Unified application, package, installer, and tag version validation.
- Added standalone and installed-app smoke tests, a packaged OAuth loopback round-trip,
  genuine N-1 workspace migration/backup verification, downgrade rejection, reinstall,
  uninstall, and external-workspace preservation checks.
- Required verified Authenticode signatures for tagged public builds and added exact
  installer provenance manifests plus public-repository build attestations.
- Changed tagged release creation to draft-first so credentialed clean-VM acceptance happens before publication.

### Phase 8.1A — Application Core

- Added deterministic startup and shutdown lifecycle pipelines.
- Added lifecycle state, step results, and failure reporting.
- Added workspace initialization, validation, and versioned metadata.
- Added the canonical `CreatorIntelligenceApplication` runtime owner.
- Centralized configuration, database, migrations, backups, modules, and diagnostics.
- Refactored the main window to consume a prepared runtime.
- Added application-core tests and architecture documentation.
