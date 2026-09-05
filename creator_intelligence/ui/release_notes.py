from __future__ import annotations

from creator_intelligence.core.versioning import APPLICATION_VERSION


NOTES_REVISION = f"{APPLICATION_VERSION}:twitch-revenue-import-1"

CURRENT_RELEASE_NOTES = (
    "A restored grouped sidebar organizes pages into Overview, Platforms, Content, Intelligence, Production, Media Tools, and System.",
    "Every page now includes a ? help button with its purpose and first-time setup steps.",
    "Tables, headers, fields, and buttons have improved spacing so labels remain legible.",
    "Windows media and hardware checks now run without flashing command-prompt windows.",
    "The installed app can check GitHub Releases for verified updates without delaying startup.",
    "Real Twitch connection, account validation, Helix polling, EventSub events, and live chat have been restored.",
    "Twitch connection status now explains expired access, missing permissions, and which live features are available.",
    "Twitch analytics are chronological, use the dark theme, and clearly distinguish missing revenue data from zero revenue.",
    "The Twitch connection and marker settings now scroll vertically instead of compressing controls together.",
    "Twitch CSV imports now combine subscriptions, gifts, bits, ads, and other earnings into total revenue.",
)
