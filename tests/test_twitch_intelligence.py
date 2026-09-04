import pandas as pd

from creator_intelligence.services.twitch_intelligence import TwitchIntelligenceService


class FrameDatabase:
    def __init__(self, frame):
        self._frame = frame

    def frame(self, _sql):
        return self._frame.copy()


def test_daily_sorts_human_readable_dates_chronologically():
    frame = pd.DataFrame(
        [
            {
                "date": "Fri Apr 03 2026",
                "minutes_streamed": 60,
                "minutes_watched": 120,
                "average_viewers": 2,
                "follows": 1,
                "total_revenue": 0,
                "chat_messages": 4,
            },
            {
                "date": "Wed Sep 27 2023",
                "minutes_streamed": 60,
                "minutes_watched": 180,
                "average_viewers": 3,
                "follows": 1,
                "total_revenue": 0,
                "chat_messages": 5,
            },
            {
                "date": "Fri Apr 05 2024",
                "minutes_streamed": 60,
                "minutes_watched": 240,
                "average_viewers": 4,
                "follows": 1,
                "total_revenue": 0,
                "chat_messages": 6,
            },
        ]
    )

    result = TwitchIntelligenceService(FrameDatabase(frame)).daily()

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2023-09-27",
        "2024-04-05",
        "2026-04-03",
    ]
