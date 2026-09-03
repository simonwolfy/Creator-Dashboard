# Content Intelligence Rollout

Version 5.0.0-alpha.3 establishes the contracts used by the four quarterly rollouts. Simon's Creator Cove is the only production-validation workspace until invited beta readiness.

## Operating flow

1. Add or scan an edited-video folder. Supported clips become durable analysis jobs.
2. Local transcription creates transcript evidence and deterministic cross-platform packages.
3. Optional visual analysis samples three frames. A cloud failure never removes transcript-only operation.
4. Packaging Review shows the generated variants, evidence, confidence, provider/model version, and latest failure.
5. A person edits, approves, or rejects every platform package. Nothing is scheduled or published without approval.
6. Approved packages can enter the publishing calendar. Connector outcomes are stored in a normalized schema while raw payloads remain available for audit.
7. Performance, edit behavior, review time, processing time, and provider usage feed the dashboard and future learning updates without replacing historical evidence.

Google Drive can be the permanent video library. Mapped Drive videos are queued from metadata only, downloaded in resumable chunks to an isolated temporary directory when analysis starts, size-checked, processed locally, and deleted whether processing succeeds or fails. Reconnect an existing Drive account once after upgrading so the application can request the read-only file-content scope; it never requests write access to Drive.

## Durable contracts

- Analysis states: `Queued`, `Running`, `Completed`, `Needs review`, `Failed`, `Cancelled`, and `Retrying`.
- Provenance: source type/id, evidence payload, confidence, provider, model, intelligence version, and timestamp.
- Outcomes: canonical content/package/variant identity plus nullable common metrics and a raw platform payload.
- Missing platform metrics are null, never zero.
- Intelligence outputs use `creator-packaging-v6`; normalized outcomes use `outcome-v1`.
- API keys are held by the operating-system credential vault, not SQLite.

## Quarterly capability gates

### Q1 — 5.0.0-alpha.3

Bulk intake, local transcription, frame sampling, deterministic fallbacks, provenance, review metrics, and job recovery are implemented. Promotion still requires a verified pre-upgrade backup, the full regression suite, installer checksum, upgrade smoke test, rollback notes, and successful June–August acceptance processing.

### Q2 — 5.0.0-alpha.4

The canonical-link and normalized-outcome contracts are implemented for all four platforms. Promotion requires authenticated connector fixtures and traceability from every published validation clip through its learning update.

### Q3 — 5.0.0-beta.1

Watched-folder discovery, durable job states, conflict detection, approval-gated calendar handoff, and bulk review validation are implemented. Promotion requires a complete monthly validation batch with no manual data re-entry.

### Q4 — 5.0.0-beta.2

Versioned experiment variants, learned packaging inputs, thumbnail-frame candidates, explanations, provider usage, privacy-safe credentials, and exportable diagnostics provide the beta foundation. Promotion requires a full-quarter comparison with the Q1 baseline and no critical privacy, migration, publishing, or data-integrity defects.

## Release checklist

- Create and restore-test a pre-upgrade backup.
- Run migration and full regression tests, including offline, missing FFmpeg/media, cloud failure, interruption, expired credentials, pagination, rate limits, deleted posts, and partial metrics.
- Process the fixed June–August acceptance dataset without crashes or data loss.
- Build the Windows installer, verify its checksum, install over the prior version, and run smoke tests.
- Document rollback and block promotion for any critical open migration, credential, publishing, privacy, or data-loss defect.
