from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from creator_intelligence.data.database import Database
from creator_intelligence.services.import_center import ImportCenterService
from creator_intelligence.services.twitch_intelligence import TwitchIntelligenceService


DAY_ROWS = [
    {
        "Stream Day ID": "day-2026-01-01", "Date": "2026-01-01",
        "Minutes Streamed": 240, "Average Viewers": 12, "Peak Viewers": 24,
        "Follows": 3, "Chat Messages": 90, "Canonical Game Sequence": "Game A",
        "Game Count": 1, "Mapping Status": "Source-backed",
        "Mapping Confidence": "High", "Mapping Source": "stream title evidence",
        "Original Game Sequence": "Game A", "Original Mapping Status": "Source-backed",
        "Original Confidence": "High",
    },
    {
        "Stream Day ID": "day-2026-01-02", "Date": "2026-01-02",
        "Minutes Streamed": 300, "Average Viewers": 20, "Peak Viewers": 40,
        "Follows": 5, "Chat Messages": 130,
        "Canonical Game Sequence": "Game A → Game B", "Game Count": 2,
        "Mapping Status": "Source-backed", "Mapping Confidence": "Medium",
        "Mapping Source": "category event evidence",
        "Original Game Sequence": "Game B → Game A",
        "Original Mapping Status": "Source-backed", "Original Confidence": "Medium",
    },
    {
        "Stream Day ID": "day-2026-01-03", "Date": "2026-01-03",
        "Minutes Streamed": 60, "Canonical Game Sequence": "", "Game Count": 0,
        "Mapping Status": "Unresolved", "Mapping Confidence": "None",
        "Mapping Source": "No source-backed category evidence",
        "Original Game Sequence": "", "Original Mapping Status": "Unresolved",
        "Original Confidence": "None",
    },
]


EVENT_ROWS = [
    {"Date": "2026-01-01", "Event Timestamp": "2026-01-01 10:00:00", "Event Type": "category_change", "Game": "Game A", "Matches Stream Day": "Yes"},
    {"Date": "2026-01-02", "Event Timestamp": "2026-01-02 11:00:00", "Event Type": "category_change", "Game": "Game B", "Matches Stream Day": "Yes"},
    {"Date": "2025-12-31", "Event Timestamp": "2025-12-31 09:00:00", "Event Type": "category_change", "Game": "Unknown Game", "Matches Stream Day": "No"},
]


def write_csv(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def service(tmp_path: Path):
    db = Database(tmp_path / "creator.db"); db.migrate()
    return db, ImportCenterService(db, tmp_path)


def test_historical_import_preserves_evidence_and_is_idempotent(tmp_path: Path):
    db, importer = service(tmp_path)
    days = tmp_path / "days.csv"; events = tmp_path / "events.csv"
    write_csv(days, DAY_ROWS); write_csv(events, EVENT_ROWS)
    staged = importer.stage(days)
    assert staged["detected_type"] == "twitch_game_history"
    importer.commit(staged["batch_id"], archive_source=False)
    staged_events = importer.stage(events)
    assert staged_events["rows_review"] == 1
    importer.commit(staged_events["batch_id"], archive_source=False)

    assert db.scalar("SELECT COUNT(*) FROM historical_stream_days") == 3
    assert db.scalar("SELECT COUNT(*) FROM historical_game_events") == 2
    assert db.scalar("SELECT COUNT(*) FROM historical_game_event_review") == 1
    preserved = db.frame("SELECT * FROM historical_stream_days WHERE date='2026-01-02'").iloc[0]
    assert preserved["canonical_game_sequence"] == "Game A → Game B"
    assert preserved["original_game_sequence"] == "Game B → Game A"
    assert preserved["mapping_confidence"] == "Medium"

    second_days = importer.stage(days)
    second_events = importer.stage(events)
    assert (second_days["rows_staged"], second_days["rows_unchanged"]) == (0, 3)
    assert (second_events["rows_staged"], second_events["rows_unchanged"]) == (0, 3)


def test_excel_detection_and_single_game_benchmark_safety(tmp_path: Path):
    db, importer = service(tmp_path)
    workbook = tmp_path / "history.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        pd.DataFrame({"Notes": ["not the table"]}).to_excel(writer, sheet_name="Read me", index=False)
        pd.DataFrame(DAY_ROWS).to_excel(writer, sheet_name="Historical Stream Days", index=False)
    staged = importer.stage(workbook)
    assert staged["rows_detected"] == 3
    importer.commit(staged["batch_id"], archive_source=False)

    intelligence = TwitchIntelligenceService(db)
    health = intelligence.historical_health_summary()
    assert health == {
        "stream_days": 3, "source_backed": 2, "unresolved": 1,
        "single_game": 1, "multi_game": 1, "matched_events": 0,
        "events_for_review": 0,
    }
    benchmark = intelligence.historical_single_game_benchmarks()
    assert benchmark["game"].tolist() == ["Game A"]
    assert int(benchmark.iloc[0]["stream_days"]) == 1
    assert float(benchmark.iloc[0]["average_viewers"]) == 12.0
