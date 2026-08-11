"""Verify a private Pre-Codex historical data pack without copying it into Git."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from creator_intelligence.data.database import Database
from creator_intelligence.services.import_center import ImportCenterService
from creator_intelligence.services.twitch_intelligence import TwitchIntelligenceService


EXPECTED = {
    "stream_days": 617,
    "source_backed": 559,
    "unresolved": 58,
    "single_game": 251,
    "multi_game": 308,
    "matched_events": 1380,
    "events_for_review": 10,
}


def verify(pack: Path) -> None:
    required = [
        "historical_stream_days.csv", "game_event_evidence.csv",
        "regression_cohort.csv",
    ]
    missing = [name for name in required if not (pack / name).is_file()]
    if missing:
        raise SystemExit(f"Missing pack files: {', '.join(missing)}")

    with tempfile.TemporaryDirectory(prefix="creator-history-verify-") as temp:
        workspace = Path(temp)
        db = Database(workspace / "verify.db"); db.migrate()
        importer = ImportCenterService(db, workspace)
        for name in required[:2]:
            staged = importer.stage(pack / name)
            if staged["rows_rejected"]:
                raise AssertionError(f"{name}: {staged['rows_rejected']} rejected rows")
            importer.commit(staged["batch_id"], archive_source=False)

        intelligence = TwitchIntelligenceService(db)
        health = intelligence.historical_health_summary()
        assert health == EXPECTED, (health, EXPECTED)
        assert db.scalar(
            """SELECT COUNT(*) FROM historical_stream_days
               WHERE mapping_status='Unresolved'
                 AND COALESCE(TRIM(canonical_game_sequence),'')<>''"""
        ) == 0, "An unresolved day was assigned a guessed game"
        benchmark_games = set(
            intelligence.historical_single_game_benchmarks()["game"].astype(str)
        )
        multi_game_sequences = set(
            db.frame(
                "SELECT canonical_game_sequence FROM historical_stream_days WHERE game_count>=2"
            )["canonical_game_sequence"].astype(str)
        )
        assert not (benchmark_games & multi_game_sequences), (
            "Multi-game daily metrics were falsely attributed to one game"
        )

        cohort = pd.read_csv(pack / "regression_cohort.csv")
        assert len(cohort) == 25
        for _, expected in cohort.iterrows():
            actual = db.frame(
                """SELECT canonical_game_sequence,game_count,mapping_confidence
                   FROM historical_stream_days WHERE date=?""",
                (str(expected["Date"]),),
            )
            assert len(actual) == 1, expected["Case ID"]
            row = actual.iloc[0]
            assert str(row["canonical_game_sequence"]) == str(expected["Canonical Game Sequence"])
            assert int(row["game_count"]) == int(expected["Game Count"])
            assert str(row["mapping_confidence"]) == str(expected["Mapping Confidence"])
            assert db.scalar(
                "SELECT COUNT(*) FROM historical_game_events WHERE stream_day_date=?",
                (str(expected["Date"]),),
            ) > 0, f"{expected['Case ID']} has no retained event evidence"

        for name, count in (
            ("historical_stream_days.csv", 617),
            ("game_event_evidence.csv", 1390),
        ):
            staged = importer.stage(pack / name)
            assert staged["rows_staged"] == 0, f"{name} changed on re-import"
            assert staged["rows_unchanged"] == count, f"{name} duplicate count mismatch"
        assert db.scalar("SELECT COUNT(*) FROM historical_stream_days") == 617
        assert db.scalar("SELECT COUNT(*) FROM historical_game_events") == 1380
        assert db.scalar("SELECT COUNT(*) FROM historical_game_event_review") == 10

    print("Historical pack verification passed: 617 days, 1,380 matched events, 25/25 cohort, idempotent re-import.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pack", type=Path, help="Extracted Creator Intelligence Pre-Codex pack")
    verify(parser.parse_args().pack.resolve())
