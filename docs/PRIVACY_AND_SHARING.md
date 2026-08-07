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

Run the tracked-file audit before every release:

```powershell
python -m creator_intelligence.core.privacy_audit
```

To audit filenames across all local Git history as well:

```powershell
python -m creator_intelligence.core.privacy_audit --history
```

The history audit intentionally fails while an older populated workspace
database remains reachable from the repository's history. Deleting the current
file is not sufficient. Before making the repository public, coordinate a
history rewrite with every collaborator, remove both historical database paths
with `git filter-repo`, force-push all affected branches and tags, and require
fresh clones. Treat any local paths and creator analytics in those databases as
previously disclosed. The audit prints paths and finding categories only, never
stored values.

## Update-check privacy

In the installed Windows app, automatic update checking is enabled by default and
runs at most once per day after startup. It makes an unauthenticated HTTPS request
to the public GitHub Releases API with the application version in the user-agent.
It does not send channel statistics, transcripts, media, workspace paths, account
identifiers, provider credentials, or OAuth tokens. The last-check time, selected
skip version, and non-secret release metadata are stored in the workspace's
`config/update_state.json`. Automatic checks can be disabled in **Settings →
Software updates**.
