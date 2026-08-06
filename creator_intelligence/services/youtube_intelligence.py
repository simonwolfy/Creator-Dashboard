from __future__ import annotations
import json
import pandas as pd
import numpy as np
from creator_intelligence.services.social_platforms import SocialPlatformService

class YouTubeIntelligenceService:
    def __init__(self, db):
        self.db = db
        self.social = SocialPlatformService(db)

    def content(self, format_filter=None):
        df = self.db.frame("""
            SELECT y.*, m.game_topic, m.series, m.episode, m.collaborator,
                   m.thumbnail_style, m.hook_style, m.tags, m.notes
            FROM youtube_content y
            LEFT JOIN content_metadata m
              ON m.content_id=y.content_id AND m.platform='YouTube'
        """)
        if df.empty:
            return df
        df["publish_date"] = pd.to_datetime(df["publish_time"], errors="coerce")
        numeric = [
            "duration_seconds","views","engaged_views","watch_time_hours",
            "avg_percentage_viewed","stayed_to_watch","impressions","ctr",
            "subscribers_gained","subscribers_lost","likes","dislikes","comments","shares"
        ]
        for c in numeric:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        df["format"] = np.where(df["duration_seconds"] <= 180, "Short", "Video")
        df["net_subscribers"] = df["subscribers_gained"] - df["subscribers_lost"]
        df["engagements"] = df["likes"] + df["comments"] + df["shares"]
        df["engagement_rate"] = np.where(df["views"] > 0, df["engagements"]/df["views"]*100, 0)
        df["subscriber_conversion"] = np.where(df["views"] > 0, df["net_subscribers"]/df["views"]*1000, 0)
        df["watch_minutes_per_view"] = np.where(df["views"] > 0, df["watch_time_hours"]*60/df["views"], 0)
        df["weekday"] = df["publish_date"].dt.day_name()
        df["publish_hour"] = df["publish_date"].dt.hour
        df["title_length"] = df["title"].fillna("").str.len()
        if format_filter and format_filter != "All":
            df = df[df["format"] == format_filter]
        return df

    def summary(self, format_filter=None):
        df = self.content(format_filter)
        if df.empty:
            return {}
        return {
            "uploads": len(df),
            "views": df["views"].sum(),
            "watch_hours": df["watch_time_hours"].sum(),
            "net_subscribers": df["net_subscribers"].sum(),
            "impressions": df["impressions"].sum(),
            "weighted_ctr": (df["ctr"]*df["impressions"]).sum()/df["impressions"].sum() if df["impressions"].sum() else 0,
            "engagement_rate": df["engagements"].sum()/df["views"].sum()*100 if df["views"].sum() else 0,
            "average_percentage_viewed": df["avg_percentage_viewed"].mean(),
        }

    def format_comparison(self):
        df = self.content()
        if df.empty:
            return df
        return df.groupby("format", as_index=False).agg(
            uploads=("content_id","count"),
            views=("views","sum"),
            median_views=("views","median"),
            watch_hours=("watch_time_hours","sum"),
            net_subscribers=("net_subscribers","sum"),
            engagement_rate=("engagement_rate","mean"),
            subscriber_conversion=("subscriber_conversion","mean"),
            avg_percentage_viewed=("avg_percentage_viewed","mean"),
            ctr=("ctr","mean"),
        )

    def weekday(self, format_filter=None):
        df = self.content(format_filter)
        if df.empty:
            return df
        order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        out = df.groupby("weekday", as_index=False).agg(
            uploads=("content_id","count"),
            views=("views","sum"),
            median_views=("views","median"),
            watch_hours=("watch_time_hours","sum"),
            net_subscribers=("net_subscribers","sum"),
            avg_ctr=("ctr","mean"),
            avg_percentage_viewed=("avg_percentage_viewed","mean"),
        )
        out["weekday"] = pd.Categorical(out["weekday"], order, ordered=True)
        return out.sort_values("weekday")

    def title_analysis(self):
        df = self.content()
        if df.empty:
            return df
        bins = [0,30,45,60,75,1000]
        labels = ["<30","30–44","45–59","60–74","75+"]
        df["title_band"] = pd.cut(df["title_length"], bins=bins, labels=labels, right=False)
        return df.groupby("title_band", observed=False, as_index=False).agg(
            uploads=("content_id","count"),
            median_views=("views","median"),
            average_views=("views","mean"),
            ctr=("ctr","mean"),
            net_subscribers=("net_subscribers","sum"),
        )

    def topic_analysis(self):
        df = self.content()
        if df.empty:
            return df
        df["game_topic"] = df["game_topic"].fillna("Untagged")
        return df.groupby("game_topic", as_index=False).agg(
            uploads=("content_id","count"),
            views=("views","sum"),
            median_views=("views","median"),
            watch_hours=("watch_time_hours","sum"),
            net_subscribers=("net_subscribers","sum"),
            engagement_rate=("engagement_rate","mean"),
            ctr=("ctr","mean"),
        ).sort_values("views", ascending=False)

    def audience(self):
        df = self.db.frame("SELECT * FROM youtube_audience_daily ORDER BY date")
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df

    def _payload_table(self, table, key_cols):
        df = self.db.frame(f"SELECT * FROM {table}")
        rows = []
        for _, row in df.iterrows():
            base = {k: row[k] for k in key_cols}
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                base.update(payload)
            rows.append(base)
        return pd.DataFrame(rows)

    def geography(self):
        return self._payload_table("youtube_geography", ["geography"])

    def cities(self):
        return self._payload_table("youtube_cities", ["city_id","city_name"])

    def age(self):
        return self._payload_table("youtube_age", ["age_group"])

    def save_metadata(self, content_id, values):
        self.db.execute("""
            INSERT INTO content_metadata(
                content_id,platform,game_topic,series,episode,collaborator,
                thumbnail_style,hook_style,tags,notes,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(content_id) DO UPDATE SET
                platform=excluded.platform,
                game_topic=excluded.game_topic,
                series=excluded.series,
                episode=excluded.episode,
                collaborator=excluded.collaborator,
                thumbnail_style=excluded.thumbnail_style,
                hook_style=excluded.hook_style,
                tags=excluded.tags,
                notes=excluded.notes,
                updated_at=excluded.updated_at
        """, (
            content_id,"YouTube",values.get("game_topic"),values.get("series"),
            values.get("episode"),values.get("collaborator"),values.get("thumbnail_style"),
            values.get("hook_style"),values.get("tags"),values.get("notes")
        ))
