from creator_intelligence.ui.pages.asset_library import AssetLibraryPage


def test_asset_size_formatting():
    assert AssetLibraryPage._format_size(None) == "—"
    assert AssetLibraryPage._format_size(500) == "500.0 B"
    assert AssetLibraryPage._format_size(2048) == "2.0 KB"
    assert AssetLibraryPage._format_size(5 * 1024 * 1024) == "5.0 MB"


def test_all_filter_maps_to_no_service_filter():
    class Combo:
        def __init__(self, value):
            self.value = value

        def currentText(self):
            return self.value

    assert AssetLibraryPage._selected(Combo("All")) is None
    assert AssetLibraryPage._selected(Combo("Video")) == "Video"
