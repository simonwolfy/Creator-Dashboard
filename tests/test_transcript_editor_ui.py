from creator_intelligence.ui.pages.transcript_editor import (
    EXPORT_FORMATS,
    TranscriptEditorPage,
    format_transcript_statistics,
)
from creator_intelligence.ui.pages.transcript_editor_polished import (
    MetricCard,
    PolishedTranscriptEditorPage,
)


def test_transcript_statistics_summary_formats_review_metrics():
    text = format_transcript_statistics({
        "word_count": 1234,
        "segment_count": 98,
        "chapter_count": 7,
        "speaker_count": 2,
        "words_per_minute": 142.25,
        "silence_percent": 31.5,
        "longest_pause_seconds": 8.75,
        "average_confidence": 0.876,
    })

    assert "Words: 1,234" in text
    assert "Segments: 98" in text
    assert "Chapters: 7" in text
    assert "Speakers: 2" in text
    assert "WPM: 142.2" in text
    assert "Silence: 31.5%" in text
    assert "Confidence: 87.6%" in text


def test_editor_exposes_every_supported_export_format():
    assert set(EXPORT_FORMATS) == {
        "SRT subtitles",
        "Markdown transcript",
        "CSV transcript",
        "YouTube chapters",
        "Premiere markers",
        "Resolve markers",
        "Final Cut Pro XML",
        "Review package JSON",
    }
    assert EXPORT_FORMATS["Premiere markers"][2] == "export_marker_csv:premiere"
    assert EXPORT_FORMATS["Resolve markers"][2] == "export_marker_csv:resolve"


def test_transcript_editor_page_keeps_seek_signal_contract():
    assert hasattr(TranscriptEditorPage, "seek_requested")


def test_polished_editor_preserves_editor_contract():
    assert issubclass(PolishedTranscriptEditorPage, TranscriptEditorPage)
    assert hasattr(PolishedTranscriptEditorPage, "_update_action_states")
    assert hasattr(PolishedTranscriptEditorPage, "_update_polished_state")
    assert hasattr(MetricCard, "set_value")
