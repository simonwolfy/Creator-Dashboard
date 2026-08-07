# Creator Intelligence

Creator Intelligence is a local Windows desktop dashboard for managing a creator's
analytics, content library, transcripts, clip packaging, production workflow, and
publishing plan in one workspace.

It currently supports workflows for Twitch, YouTube, Instagram, TikTok, Google
Drive, long-form VODs, clips, editors, and historical content performance.

> **Project status:** Creator Intelligence 5.0 is an advanced alpha. Back up your
> workspace regularly and review generated titles, captions, and recommendations
> before publishing them.

## Download the current version

**[Download the current source code (ZIP)](https://github.com/simonwolfy/Creator-Dashboard/archive/refs/heads/main.zip)**

This link always downloads the newest version from the default `main` branch.
When a signed Windows installer is published, it will appear on the
[GitHub Releases](https://github.com/simonwolfy/Creator-Dashboard/releases) page
and become the recommended download.

## What it does

- Imports Twitch and YouTube analytics exports.
- Connects supported platform accounts and synchronizes permitted statistics.
- Organizes local media and metadata in an asset library.
- Watches selected folders for new content.
- Connects Google Drive using read-only metadata access.
- Extracts video metadata and creates proxies and thumbnails with FFmpeg.
- Imports, searches, edits, and exports timestamped transcripts.
- Finds clip candidates and generates platform-specific titles, captions, hooks,
  descriptions, and hashtags.
- Learns title and caption style from published history and explicit creator choices.
- Tracks editors, production handoffs, revisions, approvals, and publishing readiness.
- Keeps provider secrets in Windows Credential Manager rather than the workspace database.

## Requirements

Creator Intelligence currently targets 64-bit Windows 10 or Windows 11.

For the source version you need:

- Python 3.11 or newer; Python 3.12 is recommended.
- An internet connection for the initial dependency installation.
- Git, unless you download the repository as a ZIP file.
- FFmpeg and FFprobe for media processing. These are optional during setup and can
  be installed or selected later inside the app.

Platform connections also require credentials from the corresponding provider.
You can skip all platform connections and configure them later.

## Install with a Windows installer

When a signed installer is available:

1. Open the [GitHub Releases](https://github.com/simonwolfy/Creator-Dashboard/releases) page.
2. Download `CreatorIntelligence-<version>-windows-x64-setup.exe`.
3. Download the matching `.sha256` file if you want to verify it independently.
4. Run the installer and follow the prompts.
5. Open **Creator Intelligence** from the Start menu.

The installer changes application files only. Your selected workspace remains in
its original location during upgrades and uninstall.

If no installer is listed yet, use the source installation below.

## Install from source

### 1. Download the project

Using Git:

```powershell
git clone https://github.com/simonwolfy/Creator-Dashboard.git
cd Creator-Dashboard
```

To use a development branch, switch to it before running setup:

```powershell
git switch feature/creator-dna
```

Alternatively, choose **Code > Download ZIP** on GitHub, extract the ZIP, and open
the extracted `Creator-Dashboard` folder.

### 2. Run the one-time setup

Double-click:

```text
SETUP_ONCE.bat
```

This creates a private Python environment in `.venv` and installs the required
packages. It does not need to run before every launch. Run it again only after
dependency files change, or if the `.venv` folder is removed or damaged.

### 3. Launch the dashboard

Double-click:

```text
START_CREATOR_INTELLIGENCE.bat
```

You can also launch it from PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m creator_intelligence
```

### Manual environment setup

If the batch setup does not work, run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m creator_intelligence
```

If PowerShell blocks environment activation, the activation step can be skipped:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m creator_intelligence
```

## First launch

The welcome wizard guides you through initial setup:

1. Choose a workspace folder.
2. Enter a workspace and channel name.
3. Review the local-data privacy notice.
4. Run the computer and dependency check.
5. Select the platforms you plan to use, or skip connections for now.
6. Finish setup and allow the empty local database to initialize.

Choose a workspace outside the Git repository, such as:

```text
C:\Users\YourName\Documents\Creator Intelligence Workspace
```

The workspace may contain analytics, transcripts, media references, exports,
logs, settings, and database backups. Provider passwords, keys, and tokens are
stored separately through Windows Credential Manager.

You can reopen the wizard later from **Settings > Open welcome and workspace setup**.

## Recommended setup order

### 1. Configure FFmpeg

Open **FFmpeg Manager**.

- Click the WinGet installation option, or select a folder containing both
  `ffmpeg.exe` and `ffprobe.exe`.
- Confirm the page reports that both tools are ready.
- Restart Creator Intelligence after changing FFmpeg paths if an open processing
  page still shows the previous status.

FFmpeg is required for video inspection, audio extraction, proxies, thumbnails,
and other media-processing features.

### 2. Connect or import platform data

- **YouTube:** enter the YouTube Data API key and channel ID, save them, and use
  **Sync content**. Synced content titles and performance statistics can contribute
  to future packaging recommendations.
- **Twitch:** configure Twitch credentials under the live-stream connection area,
  or import Twitch analytics files through **Import Center**.
- **Instagram and TikTok:** enter credentials issued by approved provider apps,
  authorize the account, exchange the returned code when requested, and sync.
  Available statistics depend on provider permissions and app approval.
- **Google Drive:** select a Google OAuth desktop client JSON file, connect in the
  browser, test the connection, then choose folders under **Drive Folders**.

Use test or development provider applications while the project is in alpha.
Never commit credential JSON files or paste tokens into GitHub issues.

### 3. Add local content

Use one of these paths:

- Open **Asset Library** to manage known media.
- Open **Folder Watcher** to monitor selected local folders.
- Open **Import Center** to stage supported Twitch or YouTube exports.
- Open **Google Drive** and **Drive Folders** for metadata-only cloud discovery.

Review detected files before starting large processing jobs.

## Everyday workflow

### Analyze a VOD or video

1. Add the source media to the asset library or a watched folder.
2. Open **Video Metadata** to inspect duration, resolution, codecs, frame rate,
   audio, and container information.
3. Use **Proxy Engine** when the original is too large for efficient editing.
4. Use **Thumbnail Engine** to create candidate frames when needed.

Media-processing work is queued locally and leaves the original source file intact.

### Create or import a transcript

1. Open **Transcripts**.
2. Select a known media item.
3. Generate a transcript with a configured local Whisper-compatible tool, or import
   SRT, WebVTT, JSON, plain-text, or Markdown transcript data.
4. Review timestamps and correct important text before creating clip packages.
5. Use transcript search, chapters, statistics, and export controls as needed.

Long VOD transcription can take a substantial amount of time. Start with a smaller
Whisper model and process one long transcription job at a time.

### Generate and approve clip packaging

1. Create or select a transcript clip candidate.
2. Analyze or reanalyze the clip to generate title and caption alternatives.
3. Open **Packaging Review**.
4. Review the detected subject, action, outcome, confidence, and context.
5. Select or edit the final title, caption, description, hook, and hashtags.
6. Approve the package only when it accurately represents the clip.
7. Send the approved package to the publishing or production workflow.

Low-confidence clips may use a quote-driven fallback or report insufficient context.
Do not approve invented or misleading packaging.

### Teach Creator Intelligence your style

Open **Creator Intelligence** to inspect the learned creator profile.

- Import or add previously published titles and available performance statistics.
- Select the preferred generated title rather than accepting every first option.
- Edit titles and captions when necessary.
- Reject weak or inaccurate packages.
- Reanalyze new clips after adding meaningful historical evidence.

Published choices, approved suggestions, edits, and rejections have different
learning weights. Historical material guides style and ranking; it is not copied
directly into unrelated clips.

### Manage production and publishing

- Use **Production** to track editors, projects, asset readiness, handoffs, draft
  deliveries, revisions, and final approval.
- Use **Review & Revision** for timestamped feedback and revision tracking.
- Use **Publishing** to manage recurring slots, the release calendar, deadlines,
  metadata readiness, and publication status.
- Use **Packaging Review** to copy approved text into the final publishing record.

The current publishing planner organizes and tracks releases. It does not directly
publish content to every connected social platform.

## Backups and updates

Open **Settings** to:

- Create a manual database backup.
- Control startup and pre-write backup behavior.
- Set backup retention.
- Run startup health checks.
- Reopen first-run setup.
- Enable or disable automatic update checks.
- Select the stable or preview update channel.
- Check GitHub Releases manually.

Installed builds check for updates in the background at most once per day. A
downloaded installer must pass its matching SHA-256 check and is never run silently.
Source installations do not update themselves; update them with Git:

```powershell
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Before deleting a workspace, copy any exports and backups you want to keep.
Uninstalling the app does not delete an external workspace.

## Troubleshooting

### `Run SETUP_ONCE.bat first`

The `.venv` environment is missing. Run `SETUP_ONCE.bat` from the repository root.

### Python or `py` is not recognized

Install 64-bit Python 3.12 from Python's official Windows installer and enable the
Python launcher during setup. Close and reopen the terminal afterward.

### FFmpeg is not ready

Open **FFmpeg Manager**, use the guided WinGet installation, or select the `bin`
folder containing both FFmpeg executables.

### A platform will not connect

- Confirm the client ID, redirect URI, API key, channel/user ID, and provider app
  permissions match the selected platform.
- Confirm the provider app is allowed to access the requested analytics scopes.
- Disconnect and reconnect after changing provider credentials.
- Review the platform status message without posting credential values publicly.

### The app does not open

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m creator_intelligence
```

Then inspect the workspace `logs` folder for the latest error. Remove secrets and
personal data before sharing any log excerpt.

### Generated build files appear in GitHub Desktop

Do not commit `build`, `dist`, `__pycache__`, workspace databases, logs, media, or
credential files. Switch to the intended development branch and confirm its
`.gitignore` is current.

## Privacy and current limitations

- Creator data is stored in the workspace selected on your computer.
- Secrets are stored through the operating-system credential vault.
- The app currently has no product-usage telemetry or automatic crash-reporting service.
- Transcript processing is local in the current implementation.
- Provider API availability depends on account type, scopes, quotas, and app approval.
- Generated recommendations require creator review.
- Direct publishing support is not available for every platform.

Read the complete [privacy notice](PRIVACY.md) before connecting real creator accounts.

## Development and validation

Install build and test dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Run the regression and release checks:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m creator_intelligence.core.release_verification --source
.\.venv\Scripts\python.exe -m creator_intelligence.core.privacy_audit --history
```

Build a standalone local app without the installer:

```powershell
.\tools\build_release.ps1 -SkipInstaller
```

The standalone executable is written to:

```text
dist\CreatorIntelligence\CreatorIntelligence.exe
```

Additional technical documentation is available in [`docs`](docs/).

## Important documentation

- [Public privacy notice](PRIVACY.md)
- [First-run onboarding](docs/FIRST_RUN_ONBOARDING.md)
- [Secure account storage](docs/SECURE_ACCOUNTS.md)
- [Windows builds and releases](docs/WINDOWS_RELEASES.md)
- [Public-release checklist](docs/PUBLIC_RELEASE_CHECKLIST.md)
- [Architecture and ownership boundaries](docs/ARCHITECTURE.md)

## License

No public license file is currently included. Unless the repository owner states
otherwise, do not assume permission to redistribute or commercially reuse the code.
