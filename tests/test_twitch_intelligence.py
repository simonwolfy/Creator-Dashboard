from __future__ import annotations

import pandas as pd

from creator_intelligence.data.database import Database
from creator_intelligence.services.twitch_intelligence import TwitchIntelligenceService
from creator_intelligence.ui.pages.twitch import prepare_time_trend, trend_title


def test_daily_streams_sort_mixed_date_formats_chronologically(tmp_path):
    db = Database(tmp_path / "twitch.db")
    db.migrate()
    for date, viewers in (
        ("12/31/2023", 8),
        ("2024-01-02", 12),
        ("Jan 1, 2024", 10),
    ):
        db.execute(
            """INSERT INTO twitch_daily(
                   date,average_viewers,minutes_streamed,minutes_watched
               ) VALUES(?,?,?,?)""",
            (date, viewers, 60, viewers * 60),
        )

    frame = TwitchIntelligenceService(db).daily()

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2023-12-31",
        "2024-01-01",
        "2024-01-02",
    ]
    assert frame["average_viewers"].tolist() == [8, 10, 12]


def test_multi_year_viewer_chart_uses_sorted_monthly_points():
    frame = pd.DataFrame(
        {
            "date": [
                "2025-01-15",
                "2023-01-02",
                "2025-01-01",
                "2024-01-01",
            ],
            "average_viewers": [30, 5, 10, 20],
        }
    )

    trend, resolution = prepare_time_trend(frame, "average_viewers", "mean")

    assert resolution == "monthly"
    assert trend["date"].is_monotonic_increasing
    assert trend.iloc[-1]["average_viewers"] == 20
    assert trend_title("Average viewers over time", resolution) == (
        "Average viewers over time (monthly)"
    )


def test_short_viewer_chart_collapses_duplicate_days_without_reordering():
    frame = pd.DataFrame(
        {
            "date": ["2026-08-03", "2026-08-01", "2026-08-01"],
            "average_viewers": [12, 6, 10],
        }
    )

    trend, resolution = prepare_time_trend(frame, "average_viewers", "mean")

    assert resolution == "daily"
    assert trend["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-08-01",
        "2026-08-03",
    ]
    assert trend["average_viewers"].tolist() == [8, 12]
