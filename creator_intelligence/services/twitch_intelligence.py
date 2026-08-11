from __future__ import annotations
import pandas as pd
import numpy as np

class TwitchIntelligenceService:
    def __init__(self, db):
        self.db = db
        from creator_intelligence.services.live_stream import LiveStreamService
        self.live = LiveStreamService(db)

    def sync_connected_account(self):
        return self.live.sync_twitch_content()

    def connected_content(self):
        return self.live.twitch_api_content()

    def connected_status(self):
        return self.live.latest_twitch_status()

    def historical_health_summary(self):
        row = self.db.frame(
            """SELECT COUNT(*) AS stream_days,
                      SUM(CASE WHEN mapping_status='Source-backed' THEN 1 ELSE 0 END) AS source_backed,
                      SUM(CASE WHEN mapping_status='Unresolved' THEN 1 ELSE 0 END) AS unresolved,
                      SUM(CASE WHEN game_count=1 THEN 1 ELSE 0 END) AS single_game,
                      SUM(CASE WHEN game_count>=2 THEN 1 ELSE 0 END) AS multi_game
               FROM historical_stream_days"""
        ).iloc[0].to_dict()
        row["matched_events"] = self.db.scalar(
            "SELECT COUNT(*) FROM historical_game_events"
        )
        row["events_for_review"] = self.db.scalar(
            "SELECT COUNT(*) FROM historical_game_event_review"
        )
        return {key: int(value or 0) for key, value in row.items()}

    def historical_stream_days(self):
        return self.db.frame(
            """SELECT date,canonical_game_sequence,game_count,mapping_status,
                      mapping_confidence,evidence_coverage,mapping_source,
                      minutes_streamed,average_viewers,peak_viewers,follows,
                      chat_messages,quality_flags
               FROM historical_stream_days ORDER BY date DESC"""
        )

    def historical_game_events(self):
        return self.db.frame(
            """SELECT stream_day_date,event_ts,event_type,game,changed_by,
                      parse_method,source_line,source_file
               FROM historical_game_events ORDER BY event_ts DESC"""
        )

    def historical_event_review(self):
        return self.db.frame(
            """SELECT stream_day_date,event_ts,event_type,game,review_reason,
                      source_line,source_file
               FROM historical_game_event_review ORDER BY event_ts DESC"""
        )

    def historical_single_game_benchmarks(self):
        """Daily metrics are safe to associate with a game only on one-game days."""
        return self.db.frame(
            """SELECT canonical_game_sequence AS game, COUNT(*) AS stream_days,
                      ROUND(AVG(minutes_streamed) / 60.0, 2) AS average_hours,
                      ROUND(AVG(average_viewers), 2) AS average_viewers,
                      MAX(peak_viewers) AS peak_viewers,
                      SUM(follows) AS follows,
                      SUM(chat_messages) AS chat_messages
               FROM historical_stream_days
               WHERE game_count=1 AND mapping_status='Source-backed'
               GROUP BY canonical_game_sequence
               ORDER BY stream_days DESC, average_viewers DESC"""
        )

    def daily(self, start=None, end=None):
        df = self.db.frame("SELECT * FROM twitch_daily ORDER BY date")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        numeric = [c for c in df.columns if c not in {"date","source_file","imported_at"}]
        for c in numeric:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        df["duration_hours"] = df["minutes_streamed"] / 60
        df["watch_hours"] = df["minutes_watched"] / 60
        df["followers_per_hour"] = np.where(df["duration_hours"] > 0, df["follows"] / df["duration_hours"], 0)
        df["revenue_per_hour"] = np.where(df["duration_hours"] > 0, df["total_revenue"] / df["duration_hours"], 0)
        df["messages_per_hour"] = np.where(df["duration_hours"] > 0, df["chat_messages"] / df["duration_hours"], 0)
        df["weekday"] = df["date"].dt.day_name()
        df["month"] = df["date"].dt.to_period("M").astype(str)
        df = df[df["minutes_streamed"] > 0].copy()
        if start:
            df = df[df["date"] >= pd.Timestamp(start)]
        if end:
            df = df[df["date"] <= pd.Timestamp(end)]
        return df

    def summary(self, start=None, end=None):
        df = self.daily(start, end)
        if df.empty:
            return {}
        return {
            "streams": len(df),
            "hours": df["duration_hours"].sum(),
            "average_viewers": df["average_viewers"].mean(),
            "peak_viewers": df["max_viewers"].max(),
            "unique_viewers": df["unique_viewers"].sum(),
            "follows": df["follows"].sum(),
            "followers_per_hour": df["followers_per_hour"].mean(),
            "watch_hours": df["watch_hours"].sum(),
            "revenue": df["total_revenue"].sum(),
            "revenue_per_hour": df["revenue_per_hour"].mean(),
            "chat_messages": df["chat_messages"].sum(),
        }

    def weekday(self, start=None, end=None):
        df = self.daily(start, end)
        if df.empty:
            return df
        order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        out = df.groupby("weekday", as_index=False).agg(
            streams=("date","count"),
            average_viewers=("average_viewers","mean"),
            peak_viewers=("max_viewers","mean"),
            follows=("follows","sum"),
            followers_per_hour=("followers_per_hour","mean"),
            revenue=("total_revenue","sum"),
            revenue_per_hour=("revenue_per_hour","mean"),
            watch_hours=("watch_hours","sum"),
        )
        out["weekday"] = pd.Categorical(out["weekday"], order, ordered=True)
        return out.sort_values("weekday")

    def duration_bands(self, start=None, end=None):
        df = self.daily(start, end)
        if df.empty:
            return df
        bins = [0,2,4,6,8,12,100]
        labels = ["<2h","2–4h","4–6h","6–8h","8–12h","12h+"]
        df["duration_band"] = pd.cut(df["duration_hours"], bins=bins, labels=labels, right=False)
        return df.groupby("duration_band", observed=False, as_index=False).agg(
            streams=("date","count"),
            average_viewers=("average_viewers","mean"),
            follows_per_hour=("followers_per_hour","mean"),
            revenue_per_hour=("revenue_per_hour","mean"),
            watch_hours=("watch_hours","sum"),
        )

    def game_segments(self):
        df = self.db.frame("SELECT * FROM game_segments ORDER BY segment_start_ts")
        if df.empty:
            return df
        for c in ["stream_start_ts","segment_start_ts","segment_end_ts"]:
            df[c] = pd.to_datetime(df[c], errors="coerce")
        df["duration_hours"] = (df["segment_end_ts"] - df["segment_start_ts"]).dt.total_seconds() / 3600
        df["duration_hours"] = df["duration_hours"].clip(lower=0)
        return df

    def game_summary(self):
        seg = self.game_segments()
        if seg.empty:
            return seg
        summary = seg.groupby("game", as_index=False).agg(
            segments=("id","count"),
            hours=("duration_hours","sum"),
            streams=("stream_start_ts","nunique"),
            first_seen=("segment_start_ts","min"),
            last_seen=("segment_end_ts","max"),
        )
        # Enrich the one minute-level session where viewer data exists.
        mins = self.db.frame("SELECT * FROM twitch_session_minutes")
        if not mins.empty:
            mins["game"] = mins["game"].fillna("Unknown")
            enriched = mins.groupby("game", as_index=False).agg(
                measured_minutes=("timestamp","count"),
                measured_average_viewers=("average_viewers","mean"),
                measured_follows=("new_followers","sum"),
                measured_chat_messages=("chat_messages","sum"),
            )
            summary = summary.merge(enriched, on="game", how="left")
        return summary.sort_values(["hours","segments"], ascending=False)

    def switch_impact(self):
        mins = self.db.frame("SELECT * FROM twitch_session_minutes ORDER BY timestamp")
        if mins.empty:
            return pd.DataFrame()
        mins["timestamp"] = pd.to_datetime(mins["timestamp"], errors="coerce")
        mins["game"] = mins["game"].fillna("Unknown")
        mins["average_viewers"] = pd.to_numeric(mins["average_viewers"], errors="coerce")
        rows = []
        for session_id, group in mins.groupby("session_id"):
            group = group.sort_values("timestamp").reset_index(drop=True)
            changes = group.index[group["game"].ne(group["game"].shift())].tolist()
            for idx in changes[1:]:
                before = group.iloc[max(0, idx-5):idx]["average_viewers"].mean()
                base_time = group.iloc[idx]["timestamp"]
                row = {
                    "session_id": session_id,
                    "switch_time": base_time,
                    "from_game": group.iloc[idx-1]["game"],
                    "to_game": group.iloc[idx]["game"],
                    "viewers_before": before,
                }
                for n in (5,15,30):
                    after = group.iloc[idx:min(len(group),idx+n)]["average_viewers"].mean()
                    row[f"viewers_after_{n}m"] = after
                    row[f"change_{n}m"] = after - before if pd.notna(after) and pd.notna(before) else np.nan
                rows.append(row)
        return pd.DataFrame(rows)

    def chat_by_game(self):
        df = self.db.frame("SELECT * FROM chat_events")
        if df.empty:
            return df
        return df.groupby(df["game"].fillna("Unknown"), as_index=False).agg(
            events=("event_ts","count"),
            category_changes=("event_type", lambda s: (s == "game_change").sum()),
        ).sort_values("events", ascending=False)

    def raids(self):
        return self.db.frame("SELECT * FROM raids ORDER BY event_ts DESC")

    def period_comparison(self, start, end):
        start = pd.Timestamp(start)
        end = pd.Timestamp(end)
        days = max(1, (end-start).days + 1)
        current = self.summary(start, end)
        previous = self.summary(start-pd.Timedelta(days=days), start-pd.Timedelta(days=1))
        rows = []
        for metric in sorted(set(current) | set(previous)):
            c = current.get(metric, 0) or 0
            p = previous.get(metric, 0) or 0
            change = ((c-p)/p*100) if p else None
            rows.append({"metric":metric,"current":c,"previous":p,"change_pct":change})
        return pd.DataFrame(rows)
