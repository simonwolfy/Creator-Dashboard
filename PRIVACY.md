# Creator Intelligence privacy notice

Last updated: August 6, 2026

This notice describes Creator Intelligence as currently implemented. Creator
Intelligence is a local Windows desktop application. It does not operate a hosted
Creator Intelligence account service.

## Data stored on your computer

The workspace you choose can contain analytics, platform content metadata,
transcripts, media paths and metadata, packaging and production decisions,
exports, logs, settings, database backups, and temporary processing files. The
small first-run profile stored in your operating-system application-data folder
contains the workspace location and setup choices, but no provider secrets.

API keys, client secrets, access tokens, refresh tokens, authorization data, and
other provider credentials are stored through the operating-system credential
vault. They are not intentionally stored in the workspace database, backups, or
logs. Connection errors pass through secret-redaction filters before logging.

## Network requests

Creator Intelligence sends requests only when needed for features you enable:

- Connected Twitch, YouTube, Instagram, TikTok, and Google Drive features send
  the requests required to authenticate, synchronize permitted metadata and
  analytics, refresh tokens, or revoke access.
- Google Drive requests metadata-only access. Instagram requests business basic
  and insights permissions. TikTok requests basic user information and video-list
  access. The exact consent screen shown by each provider remains authoritative.
- The installed app checks public GitHub Releases at most once per day by default.
  That unauthenticated request identifies the application version but does not
  include creator content, workspace paths, or provider credentials. Automatic
  checks can be disabled in Settings.
- Setup Once contacts Windows Package Manager sources to install FFmpeg when it
  is missing and Hugging Face to download the selected open-source Whisper model.
  These downloads do not include creator content, workspace data, platform
  credentials, or account identifiers. Setup Once runs only when the user selects it.

The current application has no product-usage telemetry, advertising tracker, or
automatic crash-reporting service. Transcription engines currently supported by
the app run locally; Creator Intelligence does not send transcripts to a hosted
generative-AI service as part of the current product implementation.

## Retention and deletion

Creator-owned data remains until you delete it or a configured local retention
rule removes it. Disconnecting a provider clears its local vault entry; provider-
side access can also be revoked in that provider's account controls. Uninstalling
the application preserves external workspaces so an uninstall cannot silently
destroy creator data. To remove all local data, disconnect providers, uninstall
the application, and delete the selected workspace and first-run profile after
confirming any wanted exports or backups have been retained.

## Sharing and support

Do not attach real databases, logs, OAuth files, tokens, media, transcripts, or
analytics exports to a public issue. Use synthetic examples and redact account
identifiers. Questions and privacy reports can be filed through the repository's
[GitHub issue tracker](https://github.com/simonwolfy/Creator-Dashboard/issues).

The detailed developer and repository-sharing boundaries are documented in
[`docs/PRIVACY_AND_SHARING.md`](docs/PRIVACY_AND_SHARING.md).
