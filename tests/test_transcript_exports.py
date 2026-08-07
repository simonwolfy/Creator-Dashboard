from __future__ import annotations

from pathlib import Path

from tests.test_transcript_intelligence import make_service


def prepare(tmp_path):
    service, transcript_id = make_service(tmp_path)
    service.create_manual_chapter(transcript_id, 0, 25, "Opening")
    service.create_manual_chapter(transcript_id, 25, 50, "Finale")
    first_id = int(service.segments(transcript_id).iloc[0]["id"])
    service.update_segment(first_id, speaker="Streamer")
    return service, transcript_id


def test_markdown_and_csv_exports(tmp_path):
    service, transcript_id = prepare(tmp_path)
    markdown = service.export_markdown(transcript_id, tmp_path / "transcript.md")
    csv_path = service.export_csv(transcript_id, tmp_path / "transcript.csv")

    assert "# Test stream" in markdown.read_text(encoding="utf-8")
    assert "**Streamer:**" in markdown.read_text(encoding="utf-8")
    assert "segment_index,start_seconds" in csv_path.read_text(encoding="utf-8-sig")


def test_youtube_and_nle_marker_exports(tmp_path):
    service, transcript_id = prepare(tmp_path)
    youtube = service.export_youtube_chapters(transcript_id, tmp_path / "chapters.txt")
    premiere = service.export_marker_csv(transcript_id, tmp_path / "premiere.csv", "premiere")
    resolve = service.export_marker_csv(transcript_id, tmp_path / "resolve.csv", "resolve")

    assert youtube.read_text(encoding="utf-8").splitlines() == ["0:00 Opening", "0:25 Finale"]
    assert "Marker Name" in premiere.read_text(encoding="utf-8-sig")
    assert "Color" in resolve.read_text(encoding="utf-8-sig")


def test_fcpxml_and_review_package_exports(tmp_path):
    service, transcript_id = prepare(tmp_path)
    fcpxml = service.export_fcpxml(transcript_id, tmp_path / "markers.fcpxml")
    review = service.export_review_json(transcript_id, tmp_path / "review.json")

    xml_text = fcpxml.read_text(encoding="utf-8")
    json_text = review.read_text(encoding="utf-8")
    assert "<fcpxml" in xml_text
    assert "Opening" in xml_text
    assert '"statistics"' in json_text
    assert '"chapters"' in json_text
