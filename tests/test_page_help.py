from creator_intelligence.ui.page_help import CATEGORY_ORDER, help_for_page, navigation_category
from creator_intelligence.ui.release_notes import CURRENT_RELEASE_NOTES, NOTES_REVISION


def test_navigation_categories_restore_grouped_sidebar():
    assert navigation_category("Dashboard", "content") == "Overview"
    assert navigation_category("Instagram", "analytics") == "Platforms"
    assert navigation_category("Packaging Review", "publishing") == "Production"
    assert navigation_category("Highlight Learning", "highlight_learning") == "Intelligence"
    assert navigation_category("FFmpeg Manager", "video_processing:ffmpeg-manager") == "Media Tools"
    assert CATEGORY_ORDER[-1] == "System"


def test_every_page_can_receive_first_time_help():
    help_content = help_for_page("Unknown Page", "Intelligence", "A useful module.")
    assert help_content.purpose == "A useful module."
    assert len(help_content.steps) == 3


def test_current_patch_notes_are_versioned_and_nonempty():
    assert NOTES_REVISION
    assert len(CURRENT_RELEASE_NOTES) >= 3
