from creator_intelligence.ui.pages.asset_library import AssetLibraryPage


def test_asset_size_formatting():
    assert AssetLibraryPage._format_size(None) == "—"
    assert AssetLibraryPage._format_size(500) == "500.0 B"
    assert AssetLibraryPage._format_size(2048) == "2.0 KB"
    assert AssetLibraryPage._format_size(5 * 1024 * 1024) == "5.0 MB"


def test_asset_formatters_treat_nan_and_invalid_metadata_as_missing():
    missing_values = (float("nan"), float("inf"), "not-a-number")
    for value in missing_values:
        assert AssetLibraryPage._format_size(value) == "—"
        assert AssetLibraryPage._format_duration(value) == "—"
        assert AssetLibraryPage._format_fps(value) == "—"
        assert AssetLibraryPage._format_bitrate(value) == "—"
        assert AssetLibraryPage._resolution({"width": value, "height": 1080}) == "—"
        assert AssetLibraryPage._aspect_ratio(value, 1080) == "—"


def test_asset_formatters_still_render_valid_numeric_metadata():
    assert AssetLibraryPage._resolution({"width": 1920.0, "height": 1080.0}) == "1920 × 1080"
    assert AssetLibraryPage._aspect_ratio(1920.0, 1080.0) == "16:9"
    assert AssetLibraryPage._format_duration(65.4) == "1:05"
    assert AssetLibraryPage._format_fps(59.94) == "59.94 fps"


def test_all_filter_maps_to_no_service_filter():
    class Combo:
        def __init__(self, value):
            self.value = value

        def currentText(self):
            return self.value

    assert AssetLibraryPage._selected(Combo("All")) is None
    assert AssetLibraryPage._selected(Combo("Video")) == "Video"
