from __future__ import annotations
import pandas as pd
import numpy as np

class AnalyticsService:
    def __init__(self, db):
        self.db = db

    def twitch_daily(self) -> pd.DataFrame:
        df = self.db.frame("SELECT * FROM twitch_daily ORDER BY date")
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["duration_hours"] = df["minutes_streamed"].fillna(0) / 60
        df["watch_hours"] = df["minutes_watched"].fillna(0) / 60
        df["streamed"] = df["minutes_streamed"].fillna(0) > 0
        df["weekday"] = df["date"].dt.day_name()
        return df

    def youtube_content(self) -> pd.DataFrame:
        df = self.db.frame("SELECT * FROM youtube_content")
        if df.empty:
            return df
        df["publish_date"] = pd.to_datetime(df["publish_time"], errors="coerce")
        df["net_subscribers"] = df["subscribers_gained"].fillna(0) - df["subscribers_lost"].fillna(0)
        df["format"] = np.where(df["duration_seconds"].fillna(9999) <= 180, "Short", "Video")
        return df

    def summary(self) -> dict:
        tw = self.twitch_daily()
        yt = self.youtube_content()
        streamed = tw[tw["streamed"]] if not tw.empty else tw
        return {
            "stream_hours": float(streamed["duration_hours"].sum()) if not streamed.empty else 0,
            "twitch_revenue": float(streamed["total_revenue"].fillna(0).sum()) if not streamed.empty else 0,
            "avg_viewers": float(streamed["average_viewers"].mean()) if not streamed.empty else 0,
            "youtube_views": float(yt["views"].fillna(0).sum()) if not yt.empty else 0,
            "youtube_subscribers": float(yt["net_subscribers"].fillna(0).sum()) if not yt.empty else 0,
        }
