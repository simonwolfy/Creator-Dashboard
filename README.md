# Creator Intelligence

Creator Intelligence is a local Windows desktop dashboard for managing a creator's
analytics, content library, transcripts, clip packaging, production workflow, and
publishing plan in one workspace.

It currently supports workflows for Twitch, YouTube, Instagram, TikTok, Google
Drive, long-form VODs, clips, editors, and historical content performance.

> **Project status:** Creator Intelligence 5.0 is an advanced alpha. Back up your
> workspace regularly and review generated titles, captions, and recommendations
> before publishing them.

## Download and install the current Windows version

**[Open the latest successful Windows installer builds](https://github.com/simonwolfy/Creator-Dashboard/actions/workflows/release.yml?query=branch%3Amain+is%3Asuccess)**

The recommended preview download is the artifact named
`CreatorIntelligence-Windows-Setup`. GitHub downloads it as a ZIP containing the
setup `.exe`, its SHA-256 checksum, and the release manifest at the top level.
Extract that ZIP before running the setup executable.

GitHub's automatic **Source code (zip)** and **Code > Download ZIP** downloads do
not contain a generated Windows installer. Use those only when you intend to run
Creator Intelligence from Python source. Signed public installers will also appear
on the [GitHub Releases](https://github.com/simonwolfy/Creator-Dashboard/releases)
page after a release is published.

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

Installed and source setups differ:

- The Windows installer includes Python and all application libraries. Installed
  users do not need to install Python separately.
- Source users need Python 3.11 or newer; Setup Once installs Python 3.12 through
  WinGet when Python is missing.
- An internet connection for Setup Once to obtain FFmpeg and the Whisper base model.
- Git, unless you download the repository as a ZIP file.
- FFmpeg and FFprobe for media processing. These are optional during setup and can
  be installed or selected later inside the app.

Platform connections also require credentials from the corresponding provider.
You can skip all platform connections and configure them later.

## Install with the Windows installer

For the newest tested build from `main`:

1. Open [Windows installer builds](https://github.com/simonwolfy/Creator-Dashboard/actions/workflows/release.yml?query=branch%3Amain+is%3Asuccess).
2. Select the first successful **Windows Release** run in the list.
3. Scroll to **Artifacts** at the bottom of the run summary.
4. Download `CreatorIntelligence-Windows-Setup`. GitHub supplies it as a ZIP file
   and may ask you to sign in first.
5. Extract the downloaded ZIP. Do not try to run the installer from inside the ZIP.
6. Run `CreatorIntelligence-<version>-windows-x64-setup.exe`.
7. Follow the installer prompts, then open **Creator Intelligence** from the Start menu.
8. In the welcome wizard, choose **Run Setup Once** to prepare FFmpeg, Faster
   Whisper, and the local speech model used by media-processing jobs.

The ZIP also contains a `.sha256` file and JSON release manifest. Main-branch
preview installers are automated test builds and may be unsigned, so Windows can
display a SmartScreen warning. A published signed build should instead be downloaded
from [GitHub Releases](https://github.com/simonwolfy/Creator-Dashboard/releases).

The installer changes application files only. Your selected workspace remains in
its original location during upgrades and uninstall.

If no successful installer build is listed, use the source installation below.

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

This installs Python 3.12 through WinGet when needed, creates a private Python
environment in `.venv`, installs the application libraries, installs FFmpeg and
FFprobe, and downloads the Whisper base model. It does not need to run before
every launch. Run it again only after dependency files change, if `.venv` is
removed or damaged, or if Settings reports a missing local component.

### 3. Launch the dashboard

For a normal launch with no Command Prompt window, double-click:

```text
START_CREATOR_INTELLIGENCE.vbs
```

The windowless launcher continues writing application errors to the workspace
logs. Use `START_CREATOR_INTELLIGENCE.bat` when troubleshooting and you want to
see terminal output.

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

1. Review the local-data privacy notice.
2. Choose a workspace folder and enter the workspace and channel names.
3. Run the computer check and **Setup Once** for FFmpeg, FFprobe, and Whisper.
4. Select the platforms you plan to use, or skip connections for now.
5. Finish setup and allow the empty local database to initialize.

Choose a workspace outside the Git repository, such as:

```text
C:\Users\YourName\Documents\Creator Intelligence Workspace
```

The workspace may contain analytics, transcripts, media references, exports,
logs, settings, and database backups. Provider passwords, keys, and tokens are
stored separately through Windows Credential Manager.

You can reopen the wizard later from **Settings > Open welcome and workspace setup**.

## Recommended setup order

### 1. Complete local processing setup

Open **Settings → Local processing setup → Open Setup Once** if you skipped it
during the welcome wizard.

- Keep both installation options selected and choose **Run Setup Once**.
- Confirm Python/application libraries, Whisper, FFmpeg, and the base model all
  report **Ready**.
- GPU drivers and CUDA are optional. Whisper automatically falls back to CPU.
- Restart Creator Intelligence after changing FFmpeg paths if an open processing
  page still shows the previous status.

FFmpeg is required for video inspection, audio extraction, proxies, thumbnails,
and other media-processing features.

### 2. Connect or import platform data

- **YouTube:** enable YouTube Data API v3 and YouTube Analytics API, import a Google
  OAuth client JSON created as a **Desktop app**, click **Connect YouTube**, and
  approve read-only access. The channel ID, refreshable tokens, content, watch time,
  retention, subscriber, and engagement statistics sync automatically. An API key
  and channel ID remain available as a public-data fallback.
- **Twitch:** paste the Client ID from a Twitch app registered as **Public**, then
  click **Connect Twitch** under **Live Stream > Connections and rules**. Twitch's
  device page fills the broadcaster ID and tokens automatically. No Client Secret
  or redirect URL is used.
- **Instagram:** enter the Meta app ID, app secret, and registered redirect URI,
  then click **Connect Instagram**. A local development callback can use
  `http://127.0.0.1:49153/callback/`; an approved HTTPS redirect uses the guided
  callback-URL fallback. Instagram Login supports professional Business and Creator
  accounts. Creator Intelligence syncs basic media and the insights Meta makes
  available, shows partial permissions as Limited, and does not request publishing.
- **TikTok:** enter the client key and client secret, register
  `http://127.0.0.1:49152/callback/` as the Desktop Login Kit redirect, then click
  **Connect TikTok**. The PKCE browser flow fills the open ID and refreshable
  tokens. TikTok's Display API supplies public video views, likes, comments, and
  shares; it does not supply watch time, retention, revenue, or audience analytics.
- **Google Drive:** enable Google Drive API, select a Google OAuth desktop client
  JSON file, connect in the browser, then choose folders under **Drive Folders**.
  The app requests metadata-only access and automatically validates and refreshes
  the connection while its page is open.

Instagram and TikTok connections are validated hourly and sync every 30 minutes
while their pages are open. Each workspace stores one active account per platform;
reconnecting replaces it. Disconnect always clears local OS-vault credentials,
even if a provider is temporarily unavailable.

See [Platform account connections](docs/PLATFORM_ACCOUNT_CONNECTIONS.md) for the
provider-console setup and requested permissions.

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

### Track a live Twitch stream

1. Connect Twitch under **Live Stream > Connections and rules**.
2. Open **Live Stream** and click **Start Twitch tracking**.
3. Leave Creator Intelligence running while streaming. The dashboard polls current
   viewers, title, category, follower count, and subscriber count while Twitch
   EventSub supplies chat and channel events.
4. Open **Live chat** for the read-only chat feed and **Markers** for detected or
   manually marked moments.
5. Click **Stop Twitch tracking** when you no longer want the connection running.

The tracker may be started while the channel is offline; it will keep watching,
create a real Twitch session when the channel goes live, and complete that session
when Twitch reports it offline. End any simulation session before starting real
tracking.

For connected Twitch content statistics, open **Twitch > Connected Twitch API**
and click **Sync connected Twitch data**. This imports current channel status,
recent broadcasts, clips, and their public view counts. Historical metrics that
Twitch does not expose through Helix, including full watch-time and revenue history,
still come from imported Twitch analytics reports.

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

Installed builds check for updates in the background after every launch. A
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

### Whisper model is not ready

Open **Settings → Local processing setup → Open Setup Once** and run the model
download again. Partial downloads are safe to retry. The model is stored under
your local application-data folder and is shared by all Creator Intelligence
workspaces.

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
