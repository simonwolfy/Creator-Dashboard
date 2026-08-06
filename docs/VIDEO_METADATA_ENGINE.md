# Phase 8.8 — Video Metadata Engine

The Video Metadata Engine extracts technical information from canonical `managed_assets` video records by invoking FFprobe against local files.

## Captured metadata

- duration
- width and height
- average frame rate
- video codec and profile
- pixel format
- color space, transfer, and primaries
- HDR/SDR classification
- audio codec, track count, channels, and sample rate
- container format and aggregate bit rate
- rotation
- raw FFprobe JSON for diagnostics and future fields

## Workflow

1. Local recordings enter the Asset Library through import or the folder watcher.
2. Open **Video Metadata**.
3. Select a local video and choose **Probe selected**, or process up to 25 pending local videos in a batch.
4. Results are stored in `video_asset_metadata` and remain linked to the canonical managed asset.

## Cloud assets

Metadata-only Google Drive assets do not expose a local byte stream to FFprobe. They are recorded as `Needs local file` rather than treated as failures. A later download-manager phase can provide a local copy and then re-run the same probe service.

## Safety and performance

- FFprobe is invoked without shell execution.
- Probe calls have a 120-second timeout.
- Batch processing is limited to 25 items per run from the UI.
- The UI runs probes on a worker thread.
- Probe failures are persisted per asset and do not prevent other assets from being processed.

## Database

Migration 10 creates `video_asset_metadata`, keyed by `managed_asset_id`, with indexes for status, dimensions, frame rate, and duration.
