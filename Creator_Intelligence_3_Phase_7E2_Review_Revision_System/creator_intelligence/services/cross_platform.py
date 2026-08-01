from __future__ import annotations
from datetime import datetime
import pandas as pd
import numpy as np
import json

class CrossPlatformService:
    def __init__(self, db):
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS content_relationships(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_platform TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_platform TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                source_start_seconds INTEGER,
                source_end_seconds INTEGER,
                confidence REAL DEFAULT 1.0,
                notes TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(source_platform,source_id,target_platform,target_id,relationship_type)
            )""",
            """CREATE TABLE IF NOT EXISTS stream_content_metrics(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id TEXT NOT NULL,
                content_id TEXT NOT NULL,
                editing_hours REAL DEFAULT 0,
                direct_cost REAL DEFAULT 0,
                attributed_revenue REAL DEFAULT 0,
                attributed_subscribers REAL DEFAULT 0,
                attributed_views REAL DEFAULT 0,
                notes TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(stream_id,content_id)
            )""",
            """CREATE TABLE IF NOT EXISTS content_calendar(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL,
                platform TEXT,
                scheduled_start TEXT NOT NULL,
                scheduled_end TEXT,
                status TEXT NOT NULL DEFAULT 'Planned',
                linked_pipeline_id INTEGER,
                linked_stream_id TEXT,
                linked_content_id TEXT,
                recurrence TEXT,
                priority TEXT DEFAULT 'Normal',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_relationship_source
               ON content_relationships(source_platform,source_id)""",
            """CREATE INDEX IF NOT EXISTS idx_relationship_target
               ON content_relationships(target_platform,target_id)""",
            """CREATE INDEX IF NOT EXISTS idx_calendar_start
               ON content_calendar(scheduled_start)""",
        ]
        for sql in statements:
            self.db.execute(sql)

    def twitch_streams(self):
        df = self.db.frame("""
            SELECT date AS stream_id, date, average_viewers, max_viewers, unique_viewers,
                   follows, minutes_streamed, minutes_watched, chat_messages, total_revenue
            FROM twitch_daily
            WHERE minutes_streamed > 0
            ORDER BY date DESC
        """)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["stream_id"] = df["date"].dt.strftime("%Y-%m-%d")
        df["duration_hours"] = pd.to_numeric(df["minutes_streamed"], errors="coerce").fillna(0)/60
        df["watch_hours"] = pd.to_numeric(df["minutes_watched"], errors="coerce").fillna(0)/60
        return df

    def youtube_content(self):
        df = self.db.frame("""
            SELECT content_id,title,publish_time,duration_seconds,views,engaged_views,
                   watch_time_hours,subscribers_gained,subscribers_lost,likes,comments,
                   shares,impressions,ctr
            FROM youtube_content ORDER BY publish_time DESC
        """)
        if not df.empty:
            df["publish_time"] = pd.to_datetime(df["publish_time"], errors="coerce")
            df["format"] = np.where(pd.to_numeric(df["duration_seconds"], errors="coerce").fillna(0) <= 180, "Short", "Video")
            df["net_subscribers"] = (
                pd.to_numeric(df["subscribers_gained"], errors="coerce").fillna(0)
                - pd.to_numeric(df["subscribers_lost"], errors="coerce").fillna(0)
            )
        return df

    def links(self):
        return self.db.frame("""
            SELECT r.id,r.source_platform,r.source_id,r.target_platform,r.target_id,
                   r.relationship_type,r.source_start_seconds,r.source_end_seconds,
                   r.confidence,r.notes,r.created_at,
                   y.title AS target_title,y.views,y.watch_time_hours,y.subscribers_gained,
                   y.duration_seconds
            FROM content_relationships r
            LEFT JOIN youtube_content y ON y.content_id=r.target_id
            ORDER BY r.created_at DESC
        """)

    def create_link(
        self, stream_id, content_id, relationship_type="Derived from",
        start_seconds=None, end_seconds=None, notes=None
    ):
        return self.db.execute("""
            INSERT INTO content_relationships(
                source_platform,source_id,target_platform,target_id,relationship_type,
                source_start_seconds,source_end_seconds,confidence,notes,created_at
            ) VALUES('Twitch',?,'YouTube',?,?,?,?,1.0,?,?)
            ON CONFLICT(source_platform,source_id,target_platform,target_id,relationship_type)
            DO UPDATE SET source_start_seconds=excluded.source_start_seconds,
                          source_end_seconds=excluded.source_end_seconds,
                          notes=excluded.notes
        """, (
            stream_id, content_id, relationship_type, start_seconds, end_seconds,
            notes, datetime.now().isoformat()
        ))

    def delete_link(self, link_id):
        self.db.execute("DELETE FROM content_relationships WHERE id=?", (int(link_id),))

    def update_attribution(
        self, stream_id, content_id, editing_hours=0, direct_cost=0,
        attributed_revenue=0, attributed_subscribers=0, attributed_views=0, notes=None
    ):
        self.db.execute("""
            INSERT INTO stream_content_metrics(
                stream_id,content_id,editing_hours,direct_cost,attributed_revenue,
                attributed_subscribers,attributed_views,notes,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(stream_id,content_id) DO UPDATE SET
                editing_hours=excluded.editing_hours,
                direct_cost=excluded.direct_cost,
                attributed_revenue=excluded.attributed_revenue,
                attributed_subscribers=excluded.attributed_subscribers,
                attributed_views=excluded.attributed_views,
                notes=excluded.notes,
                updated_at=excluded.updated_at
        """, (
            stream_id,content_id,float(editing_hours),float(direct_cost),
            float(attributed_revenue),float(attributed_subscribers),
            float(attributed_views),notes,datetime.now().isoformat()
        ))

    def chain_summary(self):
        streams = self.twitch_streams()
        links = self.links()
        metrics = self.db.frame("SELECT * FROM stream_content_metrics")
        if streams.empty:
            return streams
        if links.empty:
            out = streams.copy()
            out["linked_content"] = 0
            out["youtube_views"] = 0
            out["youtube_watch_hours"] = 0
            out["youtube_subscribers"] = 0
            out["editing_hours"] = 0
            out["attributed_revenue"] = 0
            out["direct_cost"] = 0
            out["combined_revenue"] = out["total_revenue"]
            out["content_roi"] = np.nan
            return out

        grouped = links.groupby("source_id", as_index=False).agg(
            linked_content=("target_id","nunique"),
            youtube_views=("views","sum"),
            youtube_watch_hours=("watch_time_hours","sum"),
            youtube_subscribers=("subscribers_gained","sum"),
        )
        out = streams.merge(grouped, left_on="stream_id", right_on="source_id", how="left")
        if not metrics.empty:
            mg = metrics.groupby("stream_id", as_index=False).agg(
                editing_hours=("editing_hours","sum"),
                attributed_revenue=("attributed_revenue","sum"),
                direct_cost=("direct_cost","sum"),
                attributed_views_manual=("attributed_views","sum"),
                attributed_subscribers_manual=("attributed_subscribers","sum"),
            )
            out = out.merge(mg, on="stream_id", how="left")
        for c in [
            "linked_content","youtube_views","youtube_watch_hours","youtube_subscribers",
            "editing_hours","attributed_revenue","direct_cost",
            "attributed_views_manual","attributed_subscribers_manual"
        ]:
            if c not in out:
                out[c] = 0
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)

        out["combined_revenue"] = out["total_revenue"] + out["attributed_revenue"]
        out["combined_watch_hours"] = out["watch_hours"] + out["youtube_watch_hours"]
        out["revenue_per_stream_hour"] = np.where(
            out["duration_hours"] > 0, out["combined_revenue"]/out["duration_hours"], 0
        )
        out["revenue_per_edit_hour"] = np.where(
            out["editing_hours"] > 0, out["attributed_revenue"]/out["editing_hours"], np.nan
        )
        out["content_roi"] = np.where(
            out["direct_cost"] > 0,
            (out["attributed_revenue"]-out["direct_cost"])/out["direct_cost"]*100,
            np.where(out["attributed_revenue"] > 0, np.inf, np.nan)
        )
        return out.sort_values("date", ascending=False)

    def repurposing_scores(self):
        df = self.chain_summary()
        if df.empty:
            return df

        def norm(series):
            s = pd.to_numeric(series, errors="coerce").fillna(0)
            if s.max() == s.min():
                return pd.Series(np.zeros(len(s)), index=s.index)
            return (s-s.min())/(s.max()-s.min())

        df["performance_score"] = (
            norm(df["average_viewers"])*0.20 +
            norm(df["max_viewers"])*0.15 +
            norm(df["unique_viewers"])*0.15 +
            norm(df["follows"])*0.20 +
            norm(df["chat_messages"])*0.15 +
            norm(df["watch_hours"])*0.15
        ) * 100
        df["underused_bonus"] = np.where(df["linked_content"] == 0, 15, 0)
        df["repurposing_score"] = (df["performance_score"] + df["underused_bonus"]).clip(0,100)
        df["recommendation"] = np.select(
            [
                (df["repurposing_score"] >= 80) & (df["linked_content"] == 0),
                (df["repurposing_score"] >= 65) & (df["linked_content"] <= 1),
                df["repurposing_score"] >= 45,
            ],
            [
                "Create a full video and 2–3 Shorts",
                "Create one highlight and 1–2 Shorts",
                "Review for one Short or clip",
            ],
            default="Low repurposing priority"
        )
        return df[[
            "stream_id","date","average_viewers","max_viewers","unique_viewers",
            "follows","chat_messages","watch_hours","linked_content",
            "youtube_views","repurposing_score","recommendation"
        ]].sort_values("repurposing_score", ascending=False)

    def overview(self):
        chains = self.chain_summary()
        links = self.links()
        if chains.empty:
            return {}
        return {
            "streams": len(chains),
            "linked_streams": int((chains["linked_content"] > 0).sum()),
            "linked_uploads": int(links["target_id"].nunique()) if not links.empty else 0,
            "youtube_views_from_links": float(chains["youtube_views"].sum()),
            "youtube_watch_hours_from_links": float(chains["youtube_watch_hours"].sum()),
            "combined_revenue": float(chains["combined_revenue"].sum()),
            "editing_hours": float(chains["editing_hours"].sum()),
        }

    def calendar_items(self, start=None, end=None):
        df = self.db.frame("SELECT * FROM content_calendar ORDER BY scheduled_start")
        if not df.empty:
            df["scheduled_start"] = pd.to_datetime(df["scheduled_start"], errors="coerce")
            df["scheduled_end"] = pd.to_datetime(df["scheduled_end"], errors="coerce")
            if start:
                df = df[df["scheduled_start"] >= pd.Timestamp(start)]
            if end:
                df = df[df["scheduled_start"] <= pd.Timestamp(end)]
        return df

    def add_calendar_item(
        self,item_type,title,platform,scheduled_start,scheduled_end=None,status="Planned",
        linked_pipeline_id=None,linked_stream_id=None,linked_content_id=None,
        recurrence=None,priority="Normal",notes=None
    ):
        now = datetime.now().isoformat()
        return self.db.execute("""
            INSERT INTO content_calendar(
                item_type,title,platform,scheduled_start,scheduled_end,status,
                linked_pipeline_id,linked_stream_id,linked_content_id,recurrence,
                priority,notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            item_type,title,platform,str(scheduled_start),
            str(scheduled_end) if scheduled_end else None,status,
            linked_pipeline_id,linked_stream_id,linked_content_id,recurrence,
            priority,notes,now,now
        ))

    def update_calendar_status(self,item_id,status):
        self.db.execute("""
            UPDATE content_calendar SET status=?,updated_at=?
            WHERE id=?
        """,(status,datetime.now().isoformat(),int(item_id)))

    def delete_calendar_item(self,item_id):
        self.db.execute("DELETE FROM content_calendar WHERE id=?",(int(item_id),))
