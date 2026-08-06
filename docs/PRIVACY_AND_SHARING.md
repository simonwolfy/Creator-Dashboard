# Privacy and Sharing Boundaries

Creator Intelligence is application code. A creator's accounts, media, analytics,
transcripts, exports, and credentials are local runtime data and must not be
committed to the repository.

## Repository-safe content

- Application source code
- Database migrations and empty schemas
- Tests with synthetic fixtures
- Generic configuration templates
- Documentation and UI assets

## Creator-owned local content

- SQLite databases and analytics exports
- Twitch and YouTube OAuth credentials or tokens
- Raw videos, audio, proxies, thumbnails, and generated clips
- Transcripts, subtitle exports, and chapter data
- Local workspace configuration and watched-folder paths
- Backups, logs, caches, models, and temporary files

These files are covered by `.gitignore`. Existing files that were committed
before a rule was added must still be removed from Git tracking with
`git rm --cached <path>`; the local file is not deleted by that command.

## Product identity

Product services and schemas must remain creator-neutral. `SimonWolfy` is the
name of a local development workspace, not a default creator embedded in the
application. New workspaces should receive a user-supplied display name during
onboarding.

## Release check

`creator_intelligence.core.privacy_audit.audit_repository` can scan a proposed
release file set for media, databases, credential-like filenames, and creator
identity hard-coding. The regression tests also verify the required ignore
boundaries.
