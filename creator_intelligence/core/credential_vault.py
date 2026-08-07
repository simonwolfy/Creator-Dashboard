from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


SERVICE_NAME = "Creator Intelligence"
MASK = "••••••••"
SECRET_KEY_PARTS = ("token", "secret", "password", "api_key", "authorization_code")


class KeyringBackend:
    def _keyring(self):
        try: import keyring
        except ImportError as exc: raise RuntimeError("Install keyring to use secure credential storage.") from exc
        return keyring

    def get(self,key): return self._keyring().get_password(SERVICE_NAME,key)
    def set(self,key,value): self._keyring().set_password(SERVICE_NAME,key,value)
    def delete(self,key):
        keyring=self._keyring()
        try:keyring.delete_password(SERVICE_NAME,key)
        except keyring.errors.PasswordDeleteError:pass


class MemoryCredentialBackend:
    def __init__(self):self.values={}
    def get(self,key):return self.values.get(key)
    def set(self,key,value):self.values[key]=value
    def delete(self,key):self.values.pop(key,None)


class CredentialVault:
    """Workspace-scoped provider secrets stored through the operating-system vault."""
    def __init__(self,workspace_id,backend=None):
        self.workspace_id=str(workspace_id);self.backend=backend or KeyringBackend()

    @classmethod
    def for_database(cls,db,backend=None):
        backend=backend or getattr(db,"credential_backend",None)
        path=str(Path(getattr(db,"path","workspace")).resolve())
        scope=hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
        return cls(scope,backend)

    def _key(self,provider):return f"{self.workspace_id}:{str(provider).lower()}"

    def load(self,provider):
        raw=self.backend.get(self._key(provider))
        if not raw:return {}
        try:return json.loads(raw)
        except (TypeError,ValueError):return {}

    def save(self,provider,values):
        current=self.load(provider)
        for key,value in values.items():
            if value in (None,"",MASK):continue
            current[str(key)]=str(value)
        if current:self.backend.set(self._key(provider),json.dumps(current,sort_keys=True))
        return current

    def replace(self,provider,values):
        clean={str(key):str(value) for key,value in values.items() if value not in (None,"",MASK)}
        if clean:self.backend.set(self._key(provider),json.dumps(clean,sort_keys=True))
        else:self.delete(provider)

    def delete(self,provider):self.backend.delete(self._key(provider))
    def exists(self,provider):return bool(self.load(provider))

    def protect(self,provider,config):
        public,secrets={},{}
        for key,value in config.items():
            (secrets if self.is_secret_key(key) else public)[key]=value
        if secrets:self.save(provider,secrets)
        return public

    def reveal(self,provider,public=None):return {**(public or {}),**self.load(provider)}

    def masked(self,provider,public=None):
        return {**(public or {}),**{key:MASK for key,value in self.load(provider).items() if value}}

    def redact(self,value):
        text=str(value or "")
        for provider in ("youtube","instagram","tiktok","twitch","obs","google-drive","generic"):
            for secret in self.load(provider).values():
                if secret:text=text.replace(str(secret),"[REDACTED]")
        text=re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s]+",r"\1[REDACTED]",text)
        text=re.sub(r"(?i)(access_token|refresh_token|api_key|client_secret|password|code)=([^&\s]+)",r"\1=[REDACTED]",text)
        return text

    @staticmethod
    def is_secret_key(key):
        lowered=str(key).lower()
        if lowered in {"client_secrets_path","twitch_token_expires_at","token_expires_at"}:return False
        return any(part in lowered for part in SECRET_KEY_PARTS)


def database_secret_findings(db):
    """Return schema/value locations that still contain credential fields, never values."""
    findings=[]
    tables=db.frame("SELECT name FROM sqlite_master WHERE type='table'")
    for table in tables.get("name",[]):
        columns=db.frame(f"PRAGMA table_info('{str(table).replace(chr(39),chr(39)*2)}')")
        for column in columns.get("name",[]):
            if CredentialVault.is_secret_key(column):
                count=int(db.scalar(f"SELECT COUNT(*) FROM '{str(table).replace(chr(39),chr(39)*2)}' WHERE \"{column}\" IS NOT NULL AND CAST(\"{column}\" AS TEXT)<>''",default=0))
                if count:findings.append({"table":str(table),"column":str(column),"rows":count})
        if "config_json" in set(columns.get("name",[])):
            rows=db.frame(f"SELECT config_json FROM '{str(table).replace(chr(39),chr(39)*2)}'")
            for value in rows.get("config_json",[]):
                try:payload=json.loads(value or "{}")
                except Exception:continue
                keys=[key for key,val in payload.items() if val and CredentialVault.is_secret_key(key)]
                if keys:findings.append({"table":str(table),"column":"config_json","keys":sorted(keys)})
    return findings
