from __future__ import annotations
from datetime import datetime
import json

class IntegrationManager:
    ADAPTERS = {
        "obs": {"name":"OBS WebSocket","status":"Not configured"},
        "streamelements": {"name":"StreamElements","status":"Not configured"},
        "streamerbot": {"name":"Streamer.bot","status":"Not configured"},
        "discord": {"name":"Discord","status":"Not configured"},
        "tiktok": {"name":"TikTok","status":"Not installed"},
        "instagram": {"name":"Instagram","status":"Not installed"},
    }

    def __init__(self, db):
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS integration_settings(
            integration_id TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            config_json TEXT NOT NULL DEFAULT '{}',
            last_connected_at TEXT,
            last_error TEXT,
            updated_at TEXT NOT NULL
        )""")

    def list_integrations(self):
        rows = self.db.frame("SELECT * FROM integration_settings")
        state = {r["integration_id"]: r for _,r in rows.iterrows()} if not rows.empty else {}
        result = []
        for integration_id, meta in self.ADAPTERS.items():
            saved = state.get(integration_id)
            result.append({
                "integration_id": integration_id,
                "name": meta["name"],
                "enabled": bool(saved["enabled"]) if saved is not None else False,
                "status": "Enabled" if saved is not None and saved["enabled"] else meta["status"],
                "last_connected_at": saved["last_connected_at"] if saved is not None else None,
                "last_error": saved["last_error"] if saved is not None else None,
            })
        return result

    def save_configuration(self, integration_id, config, enabled=False):
        self.db.execute("""INSERT INTO integration_settings(
            integration_id,enabled,config_json,updated_at
        ) VALUES(?,?,?,?)
        ON CONFLICT(integration_id) DO UPDATE SET
            enabled=excluded.enabled,
            config_json=excluded.config_json,
            updated_at=excluded.updated_at
        """,(
            integration_id,int(bool(enabled)),json.dumps(config),
            datetime.now().isoformat()
        ))
