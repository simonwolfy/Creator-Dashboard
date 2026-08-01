# Asset Library UI

The Asset Library is the visual front end for the canonical asset registry introduced in Phase 8.4.

## Navigation

The page is registered by the existing Content module immediately after Dashboard. This preserves the 21-module architecture while exposing asset management as a first-class workflow.

## Capabilities

- searches asset names, locations, URLs, and notes
- filters by asset type, storage provider, and status
- displays name, role, storage, status, size, update time, and location
- shows detailed metadata for the selected asset
- summarizes missing assets
- identifies possible duplicates when multiple visible assets share a checksum
- renders safely when the asset registry is empty

## Boundaries

This phase is read-only. Asset creation, editing, folder scanning, previews, drag and drop, and Google Drive synchronization belong to later phases. The UI consumes `AssetManagementService` rather than issuing SQL directly.
