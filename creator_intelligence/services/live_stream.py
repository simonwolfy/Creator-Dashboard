from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
import json
import math
import random
import sqlite3
import uuid
from creator_intelligence.core.credential_vault import CredentialVault

@dataclass
class LiveSnapshot:
    captured_at: str
    viewers: int
    followers_total: int | None = None
    subscribers_total: int | None = None
    revenue_total: float | None = None
    chat_messages_minute: int | None = None
    unique_chatters_5m: int | None = None
    current_game: str | None = None
    current_title: str | None = None
    obs_scene: str | None = None
    recording_active: bool | None = None

class LiveStreamService:
    def __init__(self, db, notifications=None, credential_vault=None):
        self.db = db
        self.notifications = notifications
        self.vault = credential_vault or CredentialVault.for_database(db)
        self._ensure_schema()
        self._migrate_credentials()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS live_sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT NOT NULL UNIQUE,
                platform TEXT NOT NULL DEFAULT 'Twitch',
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'Live',
                title TEXT,
                game TEXT,
                broadcaster_id TEXT,
                twitch_stream_id TEXT,
                obs_profile TEXT,
                obs_collection TEXT,
                starting_followers INTEGER,
                ending_followers INTEGER,
                starting_subscribers INTEGER,
                ending_subscribers INTEGER,
                starting_revenue REAL DEFAULT 0,
                ending_revenue REAL DEFAULT 0,
                predicted_average_viewers REAL,
                predicted_peak_viewers REAL,
                projected_average_viewers REAL,
                projected_peak_viewers REAL,
                actual_average_viewers REAL,
                actual_peak_viewers INTEGER,
                performance_score REAL,
                tracking_gap_seconds INTEGER DEFAULT 0,
                source_mode TEXT DEFAULT 'simulation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS live_metric_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                elapsed_seconds INTEGER NOT NULL,
                viewers INTEGER DEFAULT 0,
                rolling_average_5m REAL,
                session_average REAL,
                projected_average REAL,
                projected_peak REAL,
                viewer_velocity_1m REAL,
                viewer_velocity_5m REAL,
                followers_total INTEGER,
                followers_gained INTEGER DEFAULT 0,
                subscribers_total INTEGER,
                subscribers_gained INTEGER DEFAULT 0,
                revenue_total REAL DEFAULT 0,
                revenue_per_hour REAL DEFAULT 0,
                chat_messages_minute INTEGER DEFAULT 0,
                unique_chatters_5m INTEGER DEFAULT 0,
                retention_estimate REAL,
                current_game TEXT,
                current_title TEXT,
                obs_scene TEXT,
                recording_active INTEGER DEFAULT 0,
                source_payload_json TEXT,
                UNIQUE(session_id,captured_at),
                FOREIGN KEY(session_id) REFERENCES live_sessions(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_live_snapshots_session
               ON live_metric_snapshots(session_id,captured_at)""",
            """CREATE TABLE IF NOT EXISTS live_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                elapsed_seconds INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT DEFAULT 'Info',
                title TEXT NOT NULL,
                description TEXT,
                source TEXT,
                external_id TEXT,
                payload_json TEXT,
                UNIQUE(session_id,source,external_id),
                FOREIGN KEY(session_id) REFERENCES live_sessions(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_live_events_session
               ON live_events(session_id,occurred_at)""",
            """CREATE TABLE IF NOT EXISTS stream_markers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                elapsed_seconds INTEGER NOT NULL,
                marker_type TEXT NOT NULL,
                label TEXT NOT NULL,
                strength_score REAL DEFAULT 0,
                confidence REAL DEFAULT 0,
                suggested_content_type TEXT,
                supporting_metrics_json TEXT,
                source_event_id INTEGER,
                review_status TEXT DEFAULT 'Unreviewed',
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES live_sessions(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_stream_markers_session
               ON stream_markers(session_id,elapsed_seconds)""",
            """CREATE TABLE IF NOT EXISTS live_integration_settings(
                id INTEGER PRIMARY KEY CHECK(id=1),
                twitch_enabled INTEGER DEFAULT 0,
                twitch_client_id TEXT,
                twitch_broadcaster_id TEXT,
                twitch_access_token TEXT,
                twitch_refresh_token TEXT,
                twitch_token_expires_at TEXT,
                obs_enabled INTEGER DEFAULT 0,
                obs_host TEXT DEFAULT '127.0.0.1',
                obs_port INTEGER DEFAULT 4455,
                obs_password TEXT,
                polling_interval_seconds INTEGER DEFAULT 60,
                store_raw_chat INTEGER DEFAULT 0,
                simulation_mode INTEGER DEFAULT 1,
                auto_start_session INTEGER DEFAULT 1,
                viewer_spike_stddev REAL DEFAULT 2.0,
                chat_spike_multiplier REAL DEFAULT 2.5,
                follow_spike_count INTEGER DEFAULT 3,
                follow_spike_window_minutes INTEGER DEFAULT 5,
                raid_marker_min_viewers INTEGER DEFAULT 10,
                updated_at TEXT
            )""",
            """INSERT OR IGNORE INTO live_integration_settings(
                id,updated_at
            ) VALUES(1,datetime('now'))""",
        ]
        for sql in statements:
            self.db.execute(sql)

    def _migrate_credentials(self):
        self.db.execute("PRAGMA secure_delete=ON")
        frame=self.db.frame("SELECT twitch_access_token,twitch_refresh_token,obs_password FROM live_integration_settings WHERE id=1")
        if frame.empty:return
        row=frame.iloc[0]
        had_secrets=any(row.get(key) for key in ("twitch_access_token","twitch_refresh_token","obs_password"))
        self.vault.save("twitch",{"twitch_access_token":row.get("twitch_access_token"),"twitch_refresh_token":row.get("twitch_refresh_token")})
        self.vault.save("obs",{"obs_password":row.get("obs_password")})
        self.db.execute("UPDATE live_integration_settings SET twitch_access_token=NULL,twitch_refresh_token=NULL,obs_password=NULL WHERE id=1")
        if had_secrets:
            self.db.execute("VACUUM")
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def settings(self, reveal=True):
        frame = self.db.frame("SELECT * FROM live_integration_settings WHERE id=1")
        result=frame.iloc[0].to_dict()
        result=(self.vault.reveal("twitch",result) if reveal else self.vault.masked("twitch",result))
        return self.vault.reveal("obs",result) if reveal else self.vault.masked("obs",result)

    def display_settings(self):return self.settings(reveal=False)

    def update_settings(self, **kwargs):
        allowed = {
            "twitch_enabled","twitch_client_id","twitch_broadcaster_id",
            "twitch_access_token","twitch_refresh_token","twitch_token_expires_at",
            "obs_enabled","obs_host","obs_port","obs_password",
            "polling_interval_seconds","store_raw_chat","simulation_mode",
            "auto_start_session","viewer_spike_stddev","chat_spike_multiplier",
            "follow_spike_count","follow_spike_window_minutes",
            "raid_marker_min_viewers"
        }
        filtered = {k:v for k,v in kwargs.items() if k in allowed}
        twitch_secrets={k:filtered.pop(k) for k in list(filtered) if k in {"twitch_access_token","twitch_refresh_token"}}
        obs_secrets={k:filtered.pop(k) for k in list(filtered) if k=="obs_password"}
        self.vault.save("twitch",twitch_secrets);self.vault.save("obs",obs_secrets)
        if not filtered:
            return
        filtered["updated_at"] = datetime.now().isoformat()
        columns = list(filtered)
        sql = "UPDATE live_integration_settings SET " + ",".join(
            f"{column}=?" for column in columns
        ) + " WHERE id=1"
        self.db.execute(sql, [filtered[column] for column in columns])

    def disconnect_integration(self,provider):
        provider=str(provider).lower()
        if provider not in {"twitch","obs"}:raise ValueError(provider)
        self.vault.delete(provider)
        field="twitch_enabled" if provider=="twitch" else "obs_enabled"
        self.db.execute(f"UPDATE live_integration_settings SET {field}=0,updated_at=? WHERE id=1",(datetime.now().isoformat(),))

    def active_session(self):
        frame = self.db.frame(
            """SELECT * FROM live_sessions
               WHERE status='Live' ORDER BY id DESC LIMIT 1"""
        )
        return frame.iloc[0].to_dict() if not frame.empty else None

    def start_session(
        self, title=None, game=None, predicted_average_viewers=None,
        predicted_peak_viewers=None, starting_followers=None,
        starting_subscribers=None, starting_revenue=0.0,
        source_mode="simulation", twitch_stream_id=None
    ):
        existing = self.active_session()
        if existing:
            return existing
        now = datetime.now().isoformat()
        session_key = str(uuid.uuid4())
        self.db.execute(
            """INSERT INTO live_sessions(
                session_key,started_at,status,title,game,twitch_stream_id,
                starting_followers,starting_subscribers,starting_revenue,
                predicted_average_viewers,predicted_peak_viewers,
                source_mode,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_key,now,"Live",title,game,twitch_stream_id,
                starting_followers,starting_subscribers,starting_revenue,
                predicted_average_viewers,predicted_peak_viewers,
                source_mode,now,now
            )
        )
        session = self.active_session()
        self.add_event(
            session["id"],"stream_started","Stream started",
            f"Live session started in {source_mode} mode.","System"
        )
        if self.notifications:
            self.notifications.create(
                "System","Success","Live tracking started",
                f'Live session "{title or "Untitled stream"}" is now being tracked.',
                "live_session",session["id"]
            )
        return session

    def end_session(self, session_id=None):
        session = self._get_session(session_id)
        snapshots = self.snapshots(session["id"])
        now = datetime.now().isoformat()
        actual_average = float(snapshots["viewers"].mean()) if not snapshots.empty else 0
        actual_peak = int(snapshots["viewers"].max()) if not snapshots.empty else 0
        latest = snapshots.iloc[-1].to_dict() if not snapshots.empty else {}
        score = self.performance_score(session["id"])
        self.db.execute(
            """UPDATE live_sessions SET ended_at=?,status='Complete',
               ending_followers=?,ending_subscribers=?,ending_revenue=?,
               actual_average_viewers=?,actual_peak_viewers=?,
               performance_score=?,updated_at=? WHERE id=?""",
            (
                now,latest.get("followers_total"),latest.get("subscribers_total"),
                latest.get("revenue_total"),actual_average,actual_peak,
                score,now,session["id"]
            )
        )
        self.add_event(
            session["id"],"stream_ended","Stream ended",
            f"Final average viewers: {actual_average:.1f}; peak: {actual_peak}.",
            "System"
        )
        if self.notifications:
            self.notifications.create(
                "System","Success","Live session completed",
                f"Average viewers: {actual_average:.1f}; peak viewers: {actual_peak}; performance score: {score:.0f}.",
                "live_session",session["id"]
            )
        return self._get_session(session["id"])

    def _get_session(self, session_id=None):
        if session_id is None:
            session = self.active_session()
            if not session:
                raise ValueError("No active live session.")
            return session
        frame = self.db.frame("SELECT * FROM live_sessions WHERE id=?", (int(session_id),))
        if frame.empty:
            raise KeyError(session_id)
        return frame.iloc[0].to_dict()

    def elapsed_seconds(self, session, at=None):
        started = datetime.fromisoformat(session["started_at"])
        current = at or datetime.now()
        return max(0, int((current - started).total_seconds()))

    def add_event(
        self, session_id, event_type, title, description=None,
        source="Manual", external_id=None, payload=None,
        occurred_at=None, severity="Info"
    ):
        session = self._get_session(session_id)
        occurred = occurred_at or datetime.now()
        if isinstance(occurred, str):
            occurred_dt = datetime.fromisoformat(occurred)
            occurred_text = occurred
        else:
            occurred_dt = occurred
            occurred_text = occurred.isoformat()
        elapsed = self.elapsed_seconds(session, occurred_dt)
        self.db.execute(
            """INSERT OR IGNORE INTO live_events(
                session_id,occurred_at,elapsed_seconds,event_type,severity,
                title,description,source,external_id,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                session["id"],occurred_text,elapsed,event_type,severity,
                title,description,source,external_id,
                json.dumps(payload or {},default=str)
            )
        )
        frame = self.db.frame(
            """SELECT * FROM live_events WHERE session_id=?
               ORDER BY id DESC LIMIT 1""",(session["id"],)
        )
        return frame.iloc[0].to_dict() if not frame.empty else None

    def add_raid(self, viewers, source_channel, external_id=None):
        session = self._get_session()
        event = self.add_event(
            session["id"],"raid","Raid received",
            f"{source_channel} raided with {int(viewers)} viewers.",
            "Twitch",external_id,
            {"viewer_count":int(viewers),"source_channel":source_channel},
            severity="Success"
        )
        settings = self.settings()
        if int(viewers) >= int(settings["raid_marker_min_viewers"] or 10):
            strength = min(100, 55 + math.log10(max(viewers,1))*20)
            self.create_marker(
                session["id"],"Raid",
                f"Raid from {source_channel}",
                strength_score=strength,confidence=0.99,
                suggested_content_type="Highlight or Short",
                supporting_metrics={"raid_viewers":int(viewers)},
                source_event_id=event["id"] if event else None
            )
        return event

    def add_follow(self, user_name=None, external_id=None):
        session = self._get_session()
        event = self.add_event(
            session["id"],"follow","New follower",
            f"{user_name or 'A viewer'} followed the channel.",
            "Twitch",external_id,{"user_name":user_name}
        )
        self._detect_follow_spike(session["id"])
        return event

    def add_game_change(self, game, title=None):
        session = self._get_session()
        old_game = session.get("game")
        self.db.execute(
            """UPDATE live_sessions SET game=?,title=COALESCE(?,title),
               updated_at=? WHERE id=?""",
            (game,title,datetime.now().isoformat(),session["id"])
        )
        event = self.add_event(
            session["id"],"game_change","Game changed",
            f"{old_game or 'Unknown'} → {game}.","Twitch",
            payload={"old_game":old_game,"new_game":game,"title":title}
        )
        self.create_marker(
            session["id"],"Game change",f"Started playing {game}",
            strength_score=35,confidence=1.0,
            suggested_content_type="Chapter boundary",
            supporting_metrics={"old_game":old_game,"new_game":game},
            source_event_id=event["id"] if event else None
        )
        return event

    def add_scene_change(self, scene):
        session = self._get_session()
        return self.add_event(
            session["id"],"scene_change","OBS scene changed",
            f"Program scene changed to {scene}.","OBS",
            payload={"scene":scene}
        )

    def add_manual_marker(self, label="Manual moment", notes=None):
        session = self._get_session()
        event = self.add_event(
            session["id"],"manual_marker",label,notes or "Manual stream marker.",
            "Manual"
        )
        return self.create_marker(
            session["id"],"Manual",label,
            strength_score=70,confidence=1.0,
            suggested_content_type="Review manually",
            supporting_metrics={},
            source_event_id=event["id"] if event else None,
            notes=notes
        )

    def create_marker(
        self, session_id, marker_type, label, strength_score=0,
        confidence=0, suggested_content_type=None,
        supporting_metrics=None, source_event_id=None, notes=None,
        occurred_at=None
    ):
        session = self._get_session(session_id)
        occurred = occurred_at or datetime.now()
        occurred_dt = datetime.fromisoformat(occurred) if isinstance(occurred,str) else occurred
        elapsed = self.elapsed_seconds(session,occurred_dt)
        now = datetime.now().isoformat()
        marker_id = int(self.db.execute(
            """INSERT INTO stream_markers(
                session_id,occurred_at,elapsed_seconds,marker_type,label,
                strength_score,confidence,suggested_content_type,
                supporting_metrics_json,source_event_id,notes,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session["id"],occurred_dt.isoformat(),elapsed,marker_type,label,
                float(strength_score),float(confidence),suggested_content_type,
                json.dumps(supporting_metrics or {},default=str),
                source_event_id,notes,now
            )
        ))
        if self.notifications and float(strength_score) >= 80:
            self.notifications.create(
                "System","Success","Strong highlight marker created",
                f"{label} scored {float(strength_score):.0f}/100.",
                "stream_marker",marker_id
            )
        return self.db.frame(
            "SELECT * FROM stream_markers ORDER BY id DESC LIMIT 1"
        ).iloc[0].to_dict()

    def record_snapshot(self, snapshot: LiveSnapshot | dict[str,Any], session_id=None):
        session = self._get_session(session_id)
        if isinstance(snapshot, dict):
            snapshot = LiveSnapshot(**snapshot)
        captured = datetime.fromisoformat(snapshot.captured_at)
        elapsed = self.elapsed_seconds(session,captured)
        prior = self.snapshots(session["id"])
        viewers = int(snapshot.viewers or 0)

        session_average = (
            (prior["viewers"].sum() + viewers) / (len(prior)+1)
            if not prior.empty else float(viewers)
        )
        rolling = self._rolling_average(prior, captured, minutes=5, include=viewers)
        velocity_1m = self._velocity(prior,captured,viewers,minutes=1)
        velocity_5m = self._velocity(prior,captured,viewers,minutes=5)
        projected_average = self._project_average(
            session_average,velocity_5m,elapsed,
            session.get("predicted_average_viewers")
        )
        projected_peak = max(
            viewers,
            float(prior["viewers"].max()) if not prior.empty else viewers,
            projected_average + max(0,velocity_5m)*2
        )
        start_followers = session.get("starting_followers")
        follows_gained = (
            max(0,int(snapshot.followers_total)-int(start_followers))
            if snapshot.followers_total is not None and start_followers is not None
            else 0
        )
        start_subs = session.get("starting_subscribers")
        subs_gained = (
            max(0,int(snapshot.subscribers_total)-int(start_subs))
            if snapshot.subscribers_total is not None and start_subs is not None
            else 0
        )
        revenue_total = float(snapshot.revenue_total or 0)
        revenue_per_hour = (
            revenue_total / max(elapsed/3600, 1/60)
            if elapsed > 0 else 0
        )
        retention = self._retention_estimate(session_average,projected_average,velocity_5m)

        payload = {
            "viewers": viewers,
            "followers_total": snapshot.followers_total,
            "subscribers_total": snapshot.subscribers_total,
            "revenue_total": snapshot.revenue_total,
            "chat_messages_minute": snapshot.chat_messages_minute,
            "unique_chatters_5m": snapshot.unique_chatters_5m,
            "current_game": snapshot.current_game,
            "current_title": snapshot.current_title,
            "obs_scene": snapshot.obs_scene,
            "recording_active": snapshot.recording_active,
        }
        self.db.execute(
            """INSERT OR REPLACE INTO live_metric_snapshots(
                session_id,captured_at,elapsed_seconds,viewers,
                rolling_average_5m,session_average,projected_average,
                projected_peak,viewer_velocity_1m,viewer_velocity_5m,
                followers_total,followers_gained,subscribers_total,
                subscribers_gained,revenue_total,revenue_per_hour,
                chat_messages_minute,unique_chatters_5m,retention_estimate,
                current_game,current_title,obs_scene,recording_active,
                source_payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session["id"],snapshot.captured_at,elapsed,viewers,
                rolling,session_average,projected_average,projected_peak,
                velocity_1m,velocity_5m,snapshot.followers_total,follows_gained,
                snapshot.subscribers_total,subs_gained,revenue_total,
                revenue_per_hour,int(snapshot.chat_messages_minute or 0),
                int(snapshot.unique_chatters_5m or 0),retention,
                snapshot.current_game,snapshot.current_title,snapshot.obs_scene,
                int(bool(snapshot.recording_active)),
                json.dumps(payload,default=str)
            )
        )
        self.db.execute(
            """UPDATE live_sessions SET projected_average_viewers=?,
               projected_peak_viewers=?,updated_at=? WHERE id=?""",
            (
                projected_average,projected_peak,
                datetime.now().isoformat(),session["id"]
            )
        )
        self._detect_snapshot_markers(session["id"])
        return self.latest_snapshot(session["id"])

    def _rolling_average(self, prior, captured, minutes, include):
        if prior.empty:
            return float(include)
        threshold = captured - timedelta(minutes=minutes)
        frame = prior.copy()
        frame["captured_dt"] = frame["captured_at"].apply(datetime.fromisoformat)
        values = frame.loc[frame["captured_dt"]>=threshold,"viewers"].tolist()
        values.append(include)
        return sum(values)/len(values)

    def _velocity(self, prior, captured, current, minutes):
        if prior.empty:
            return 0.0
        target = captured - timedelta(minutes=minutes)
        frame = prior.copy()
        frame["captured_dt"] = frame["captured_at"].apply(datetime.fromisoformat)
        eligible = frame[frame["captured_dt"]<=target]
        reference = eligible.iloc[-1] if not eligible.empty else frame.iloc[0]
        delta_minutes = max(
            (captured-reference["captured_dt"]).total_seconds()/60, 1/60
        )
        return (current-float(reference["viewers"]))/delta_minutes

    def _project_average(self,current_average,velocity_5m,elapsed,predicted):
        stabilization = min(1.0,max(0.15,elapsed/7200))
        live_projection = max(0,current_average + velocity_5m*2.5)
        if predicted is None:
            return live_projection
        return float(predicted)*(1-stabilization) + live_projection*stabilization

    def _retention_estimate(self,current_average,projected_average,velocity):
        if current_average <= 0:
            return 0
        momentum = max(-0.25,min(0.25,velocity/max(current_average,1)))
        estimate = (projected_average/max(current_average,1))*0.75 + 0.25 + momentum
        return max(0,min(1.5,estimate))

    def _detect_snapshot_markers(self, session_id):
        frame = self.snapshots(session_id)
        if len(frame) < 4:
            return
        latest = frame.iloc[-1]
        history = frame.iloc[:-1]
        settings = self.settings()

        mean = float(history["viewers"].mean())
        std = float(history["viewers"].std(ddof=0) or 0)
        threshold = mean + float(settings["viewer_spike_stddev"] or 2.0)*std
        if std > 0 and float(latest["viewers"]) >= threshold:
            recent = self.db.frame(
                """SELECT COUNT(*) AS count FROM stream_markers
                   WHERE session_id=? AND marker_type='Viewer spike'
                   AND elapsed_seconds>=?""",
                (session_id,max(0,int(latest["elapsed_seconds"])-300))
            )
            if int(recent.iloc[0]["count"]) == 0:
                strength = min(
                    100,60 + ((float(latest["viewers"])-mean)/max(std,1))*10
                )
                self.create_marker(
                    session_id,"Viewer spike","Viewer spike detected",
                    strength_score=strength,confidence=0.9,
                    suggested_content_type="Short or highlight",
                    supporting_metrics={
                        "current_viewers":int(latest["viewers"]),
                        "historical_mean":round(mean,2),
                        "standard_deviation":round(std,2),
                        "threshold":round(threshold,2)
                    },
                    occurred_at=latest["captured_at"]
                )

        chat_history = history["chat_messages_minute"]
        baseline = float(chat_history.tail(15).mean()) if not chat_history.empty else 0
        multiplier = float(settings["chat_spike_multiplier"] or 2.5)
        current_chat = float(latest["chat_messages_minute"] or 0)
        if baseline >= 1 and current_chat >= baseline*multiplier:
            recent = self.db.frame(
                """SELECT COUNT(*) AS count FROM stream_markers
                   WHERE session_id=? AND marker_type='Chat spike'
                   AND elapsed_seconds>=?""",
                (session_id,max(0,int(latest["elapsed_seconds"])-300))
            )
            if int(recent.iloc[0]["count"]) == 0:
                strength = min(100,55+(current_chat/baseline)*12)
                self.create_marker(
                    session_id,"Chat spike","Chat activity spike",
                    strength_score=strength,confidence=0.88,
                    suggested_content_type="Short, clip, or highlight",
                    supporting_metrics={
                        "messages_per_minute":int(current_chat),
                        "baseline":round(baseline,2),
                        "multiplier":round(current_chat/baseline,2)
                    },
                    occurred_at=latest["captured_at"]
                )

        previous_peak = int(history["viewers"].max())
        if int(latest["viewers"]) > previous_peak:
            self.add_event(
                session_id,"new_peak","New viewer peak",
                f'Viewer count reached {int(latest["viewers"])}.',
                "Analytics",
                external_id=f'peak:{int(latest["viewers"])}',
                occurred_at=latest["captured_at"],
                severity="Success"
            )

    def _detect_follow_spike(self, session_id):
        settings = self.settings()
        window = int(settings["follow_spike_window_minutes"] or 5)
        threshold = int(settings["follow_spike_count"] or 3)
        session = self._get_session(session_id)
        elapsed = self.elapsed_seconds(session)
        frame = self.db.frame(
            """SELECT COUNT(*) AS count FROM live_events
               WHERE session_id=? AND event_type='follow'
               AND elapsed_seconds>=?""",
            (session_id,max(0,elapsed-window*60))
        )
        count = int(frame.iloc[0]["count"])
        if count >= threshold:
            recent = self.db.frame(
                """SELECT COUNT(*) AS count FROM stream_markers
                   WHERE session_id=? AND marker_type='Follow spike'
                   AND elapsed_seconds>=?""",
                (session_id,max(0,elapsed-window*60))
            )
            if int(recent.iloc[0]["count"]) == 0:
                self.create_marker(
                    session_id,"Follow spike","Follower spike detected",
                    strength_score=min(100,60+count*8),confidence=0.95,
                    suggested_content_type="Review surrounding moment",
                    supporting_metrics={
                        "follows":count,
                        "window_minutes":window
                    }
                )

    def snapshots(self, session_id):
        return self.db.frame(
            """SELECT * FROM live_metric_snapshots
               WHERE session_id=? ORDER BY captured_at""",(int(session_id),)
        )

    def latest_snapshot(self, session_id=None):
        session = self._get_session(session_id)
        frame = self.db.frame(
            """SELECT * FROM live_metric_snapshots
               WHERE session_id=? ORDER BY captured_at DESC LIMIT 1""",
            (session["id"],)
        )
        return frame.iloc[0].to_dict() if not frame.empty else None

    def events(self, session_id=None):
        session = self._get_session(session_id)
        return self.db.frame(
            """SELECT * FROM live_events
               WHERE session_id=? ORDER BY occurred_at""",(session["id"],)
        )

    def markers(self, session_id=None):
        session = self._get_session(session_id)
        return self.db.frame(
            """SELECT * FROM stream_markers
               WHERE session_id=? ORDER BY occurred_at""",(session["id"],)
        )

    def timeline(self, session_id=None):
        session = self._get_session(session_id)
        events = self.db.frame(
            """SELECT occurred_at,elapsed_seconds,'Event' AS item_kind,
               event_type AS item_type,title,description,
               NULL AS strength_score,NULL AS confidence
               FROM live_events WHERE session_id=?""",(session["id"],)
        )
        markers = self.db.frame(
            """SELECT occurred_at,elapsed_seconds,'Marker' AS item_kind,
               marker_type AS item_type,label AS title,notes AS description,
               strength_score,confidence
               FROM stream_markers WHERE session_id=?""",(session["id"],)
        )
        if events.empty:
            combined = markers
        elif markers.empty:
            combined = events
        else:
            import pandas as pd
            combined = pd.concat([events,markers],ignore_index=True)
        if not combined.empty:
            combined = combined.sort_values(["occurred_at","item_kind"])
        return combined

    def dashboard(self, session_id=None):
        session = self._get_session(session_id)
        latest = self.latest_snapshot(session["id"])
        snapshots = self.snapshots(session["id"])
        if not latest:
            return {
                "session":session,"current_viewers":0,"average_viewers":0,
                "peak_viewers":0,"viewer_velocity_5m":0,
                "followers_gained":0,"subscribers_gained":0,
                "revenue_total":0,"revenue_per_hour":0,
                "chat_messages_minute":0,"retention_estimate":0,
                "projected_average":session.get("predicted_average_viewers") or 0,
                "projected_peak":session.get("predicted_peak_viewers") or 0,
                "performance_score":0
            }
        return {
            "session":session,
            "current_viewers":int(latest["viewers"]),
            "average_viewers":float(latest["session_average"] or 0),
            "peak_viewers":int(snapshots["viewers"].max()),
            "viewer_velocity_1m":float(latest["viewer_velocity_1m"] or 0),
            "viewer_velocity_5m":float(latest["viewer_velocity_5m"] or 0),
            "followers_gained":int(latest["followers_gained"] or 0),
            "subscribers_gained":int(latest["subscribers_gained"] or 0),
            "revenue_total":float(latest["revenue_total"] or 0),
            "revenue_per_hour":float(latest["revenue_per_hour"] or 0),
            "chat_messages_minute":int(latest["chat_messages_minute"] or 0),
            "retention_estimate":float(latest["retention_estimate"] or 0),
            "projected_average":float(latest["projected_average"] or 0),
            "projected_peak":float(latest["projected_peak"] or 0),
            "performance_score":self.performance_score(session["id"]),
        }

    def performance_score(self, session_id=None):
        session = self._get_session(session_id)
        latest = self.latest_snapshot(session["id"])
        if not latest:
            return 0.0
        predicted = float(session.get("predicted_average_viewers") or latest["session_average"] or 1)
        viewer_score = min(130,float(latest["projected_average"] or 0)/max(predicted,1)*100)
        retention_score = min(130,float(latest["retention_estimate"] or 0)*100)
        chat_score = min(130,float(latest["chat_messages_minute"] or 0)/20*100)
        follower_score = min(130,float(latest["followers_gained"] or 0)/5*100)
        revenue_score = min(130,float(latest["revenue_per_hour"] or 0)/25*100)
        score = (
            viewer_score*0.35 + retention_score*0.20 +
            chat_score*0.20 + follower_score*0.15 +
            revenue_score*0.10
        )
        return max(0,min(100,score))

class LiveSimulationAdapter:
    def __init__(self, service: LiveStreamService, seed=42):
        self.service=service
        self.random=random.Random(seed)
        self.viewer_level=24
        self.followers=4800
        self.subscribers=45
        self.revenue=0.0
        self.chat=8
        self.tick_count=0

    def start(self,title="Simulation Stream",game="Minecraft"):
        return self.service.start_session(
            title=title,game=game,predicted_average_viewers=28,
            predicted_peak_viewers=45,starting_followers=self.followers,
            starting_subscribers=self.subscribers,
            starting_revenue=self.revenue,source_mode="simulation"
        )

    def tick(self, at=None):
        session=self.service.active_session() or self.start()
        self.tick_count += 1
        drift=self.random.choice([-2,-1,0,1,1,2,3])
        if self.tick_count in {8,18}:
            drift += self.random.randint(12,22)
            self.chat += self.random.randint(25,45)
        else:
            self.chat=max(1,int(self.chat+self.random.choice([-3,-1,0,1,2,3])))
        self.viewer_level=max(1,self.viewer_level+drift)
        if self.random.random()<0.22:
            self.followers += 1
            self.service.add_follow(f"sim_viewer_{self.tick_count}",f"follow-{self.tick_count}")
        if self.random.random()<0.08:
            self.subscribers += 1
        if self.random.random()<0.18:
            self.revenue += round(self.random.uniform(1,8),2)
        captured=(at or datetime.now()).isoformat()
        snapshot=LiveSnapshot(
            captured_at=captured,viewers=self.viewer_level,
            followers_total=self.followers,subscribers_total=self.subscribers,
            revenue_total=self.revenue,chat_messages_minute=self.chat,
            unique_chatters_5m=max(1,int(self.chat*0.7)),
            current_game=session.get("game"),current_title=session.get("title"),
            obs_scene="Gameplay",recording_active=True
        )
        return self.service.record_snapshot(snapshot,session["id"])
