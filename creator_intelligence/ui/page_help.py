from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageHelp:
    purpose: str
    steps: tuple[str, ...]


CATEGORY_ORDER = (
    "Overview",
    "Platforms",
    "Content",
    "Intelligence",
    "Production",
    "Media Tools",
    "System",
)

_CATEGORY_BY_LABEL = {
    "Dashboard": "Overview",
    "Home": "Overview",
    "Live Stream": "Overview",
    "Twitch": "Platforms",
    "YouTube": "Platforms",
    "Instagram": "Platforms",
    "TikTok": "Platforms",
    "Drive Folders": "Platforms",
    "Cross-platform": "Platforms",
    "Google Drive": "Platforms",
    "Import Center": "Content",
    "Import Watcher": "Content",
    "Notifications": "Content",
    "Transcripts": "Content",
    "Folder Watcher": "Content",
    "Content Pipeline": "Content",
    "Asset Library": "Content",
    "FFmpeg Manager": "Media Tools",
    "Video Processing": "Media Tools",
    "Video Metadata": "Media Tools",
    "Proxy Engine": "Media Tools",
    "Thumbnail Engine": "Media Tools",
    "Processing Scheduler": "Media Tools",
    "Goals": "System",
    "Data Quality": "System",
    "Modules": "System",
    "Settings": "System",
}

_CATEGORY_BY_MODULE = {
    "analytics": "Platforms",
    "content": "Content",
    "imports": "Content",
    "transcripts": "Content",
    "video_processing": "Media Tools",
    "system": "System",
    "production": "Production",
    "publishing": "Production",
    "editor_workspace": "Production",
    "review_revision": "Production",
}

_CATEGORY_STEPS = {
    "Overview": (
        "Review the summary cards first to understand the current workspace.",
        "Use the tables and status areas to find work that needs attention.",
        "Refresh after importing or editing data to see the latest totals.",
    ),
    "Platforms": (
        "Open the connection or API section and enter the requested platform details.",
        "Run the connection check before attempting a sync.",
        "Sync content and metrics, then review the results before using them for recommendations.",
    ),
    "Content": (
        "Choose or connect the source that contains your creator files.",
        "Import or scan the source, then review any warnings or duplicates.",
        "Open the resulting content item to continue through transcription and packaging.",
    ),
    "Intelligence": (
        "Select a content item or date range to analyze.",
        "Review the evidence and confidence shown with each recommendation.",
        "Approve or edit the result; your final choice becomes feedback for future suggestions.",
    ),
    "Production": (
        "Select the content item you want to move through production.",
        "Complete the readiness fields and resolve any validation warnings.",
        "Review and explicitly approve work before scheduling or publishing it.",
    ),
    "Media Tools": (
        "Confirm FFmpeg and FFprobe are available before processing video.",
        "Choose an asset and the operation you want to run.",
        "Monitor the job status; failed or cancelled jobs can be reviewed and retried.",
    ),
    "System": (
        "Review the current workspace and application status.",
        "Change only the settings needed for this workspace.",
        "Run the available checks after changes and review any reported issue before continuing.",
    ),
}

_PURPOSE_BY_LABEL = {
    "Dashboard": "See today’s work queue, recent activity, upcoming publications, and content totals in one place.",
    "Home": "Review the creator’s cross-platform performance and the most important recommendations.",
    "Asset Library": "Find and manage the canonical local and cloud media records used throughout the app.",
    "Folder Watcher": "Discover new or changed local media without importing the same file twice.",
    "Drive Folders": "Map Google Drive folders into the workspace while keeping cloud files cloud-first.",
    "Content Pipeline": "Track each content item from intake through analysis, review, scheduling, and publication.",
    "Transcripts": "Create, import, review, and reuse time-aligned transcripts for creator content.",
    "Creator DNA": "Learn repeatable creator style signals from approved work and historical outcomes.",
    "Packaging Review": "Review title and caption variants, their evidence, and the final approved selection.",
    "Content Intelligence": "Process content in bulk and inspect the status, evidence, and failures for each analysis job.",
    "Settings": "Control workspace behavior, software updates, privacy choices, and health checks.",
}


def navigation_category(label: str, module_id: str | None) -> str:
    if label in _CATEGORY_BY_LABEL:
        return _CATEGORY_BY_LABEL[label]
    module = str(module_id or "").split(":", 1)[0]
    return _CATEGORY_BY_MODULE.get(module, "Intelligence")


def help_for_page(label: str, category: str, module_description: str = "") -> PageHelp:
    purpose = _PURPOSE_BY_LABEL.get(label) or module_description.strip()
    if not purpose:
        purpose = f"Use {label} as part of the {category.lower()} workflow."
    return PageHelp(purpose, _CATEGORY_STEPS[category])
