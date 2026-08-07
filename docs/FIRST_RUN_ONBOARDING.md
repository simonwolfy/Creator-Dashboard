# First-Run Onboarding

Creator Intelligence opens a welcome wizard before creating application data on
a new computer. The creator chooses a workspace folder, workspace name, and
channel name. The wizard explains that analytics, transcripts, media references,
exports, backups, and settings are stored in that local workspace.

The computer check distinguishes required items from optional media tools.
Python and a writable workspace are required. FFmpeg and FFprobe are optional at
setup time and can be configured later from the dashboard.

Platform connections are optional. Selecting YouTube, Twitch, Instagram, or
TikTok records only a setup preference; the welcome wizard never asks for or
stores credentials. Provider setup remains in the corresponding platform tab.

Finishing setup creates the workspace folders, initializes and migrates an empty
SQLite database, writes workspace-local settings, and stores a small installation
profile in the operating system's user configuration directory. That profile
contains the workspace location and onboarding choices, but no provider secrets.

The wizard can be reopened from **Settings → Open welcome and workspace setup**.
Reopening or resetting onboarding does not delete the existing database or files.
An existing valid workspace can be adopted without recreating its database.
