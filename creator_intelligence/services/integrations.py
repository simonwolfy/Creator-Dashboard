from __future__ import annotations
from datetime import datetime
import json
from creator_intelligence.core.credential_vault import CredentialVault

class IntegrationManager:
    ADAPTERS = {
        "obs": {"name":"OBS WebSocket","status":"Not configured"},
        "streamelements": {"name":"StreamElements","status":"Not configured"},
        "streamerbot": {"name":"Streamer.bot","status":"Not configured"},
        "discord": {"name":"Discord","status":"Not configured"},
        "tiktok": {"name":"TikTok","status":"Not installed"},
        "instagram": {"name":"Instagram","status":"Not installed"},
    }

    def __init__(self, db, credential_vault=None):
        self.db = db
        self.vault = credential_vault or CredentialVault.for_database(db)
        self._ensure_schema()
        self._migrate_credentials()

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

    def _migrate_credentials(self):
        self.db.execute("PRAGMA secure_delete=ON")
        rows=self.db.frame("SELECT integration_id,config_json FROM integration_settings")
        changed=False
        for _,row in rows.iterrows():
            try:config=json.loads(row["config_json"] or "{}")
            except Exception:config={}
            provider=str(row["integration_id"]).removesuffix("_title_sync")
            public=self.vault.protect(provider,config)
            if public!=config:
                self.db.execute("UPDATE integration_settings SET config_json=?,updated_at=? WHERE integration_id=?",
                                (json.dumps(public),datetime.now().isoformat(),row["integration_id"]));changed=True
        if changed:
            self.db.execute("VACUUM")
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def save_configuration(self, integration_id, config, enabled=False):
        provider=str(integration_id).removesuffix("_title_sync")
        public=self.vault.protect(provider,config)
        self.db.execute("""INSERT INTO integration_settings(
            integration_id,enabled,config_json,updated_at
        ) VALUES(?,?,?,?)
        ON CONFLICT(integration_id) DO UPDATE SET
            enabled=excluded.enabled,
            config_json=excluded.config_json,
            updated_at=excluded.updated_at
        """,(
            integration_id,int(bool(enabled)),json.dumps(public),
            datetime.now().isoformat()
        ))

    def disconnect(self,integration_id):
        self.vault.delete(str(integration_id).removesuffix("_title_sync"))
        self.db.execute("UPDATE integration_settings SET enabled=0,last_error=NULL,updated_at=? WHERE integration_id=?",
                        (datetime.now().isoformat(),integration_id))
