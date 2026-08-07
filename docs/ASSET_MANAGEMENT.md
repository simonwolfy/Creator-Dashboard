# Asset Management

Phase 8.4 introduces a canonical registry for production files and externally stored assets.

## Core records

`managed_assets` stores one permanent UUID for each raw recording, VOD, editor export, thumbnail, project file, subtitle file, audio file, overlay, or other production asset. The record tracks its type, workflow role, storage provider, provider identifier, location, MIME type, extension, size, SHA-256 checksum, availability status, recording date, verification date, and notes.

`content_asset_links` connects assets to unified content items. A content item can have multiple assets, and each link records the asset's role and whether it is the primary asset for that role.

`managed_asset_relationships` forms a directed derivation graph. Raw recordings can lead to editor projects, editor projects can lead to final exports, and exports can lead to platform-specific deliverables.

## Service operations

`AssetManagementService` provides:

- asset creation and updates
- text and metadata filtering
- checksum-based duplicate lookup
- content-to-asset and asset-to-content navigation
- parent and derived asset relationships
- availability verification and missing-file status

## Storage independence

The database stores references rather than file bytes. `storage_provider`, `provider_key`, and `location` allow the same model to represent local disks, Google Drive, cloud object storage, editor delivery services, and future integrations.

## Safety and compatibility

The schema uses dedicated `managed_*` table names to avoid collisions with older production tables. Asset records are not deleted when a file becomes unavailable; they are marked `Missing` so relationships and production history remain intact.
