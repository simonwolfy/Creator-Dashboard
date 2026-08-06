from __future__ import annotations

import json
import logging

from creator_intelligence.core.credential_vault import (
    MASK,CredentialVault,MemoryCredentialBackend,database_secret_findings,
)
from creator_intelligence.core.logging import SensitiveDataFilter
from creator_intelligence.data.database import Database
from creator_intelligence.services.backup import BackupService
from creator_intelligence.services.integrations import IntegrationManager
from creator_intelligence.services.live_stream import LiveStreamService
from creator_intelligence.services.social_platforms import SocialPlatformService


def vault(db):return CredentialVault.for_database(db,MemoryCredentialBackend())


def test_vault_masks_merges_redacts_and_deletes_without_revealing_values(tmp_path):
    db=Database(tmp_path/"creator.db");secure=vault(db)
    secure.save("youtube",{"api_key":"very-secret-key"})
    assert secure.load("youtube")=={"api_key":"very-secret-key"}
    assert secure.masked("youtube",{"channel_id":"channel"})=={"channel_id":"channel","api_key":MASK}
    secure.save("youtube",{"api_key":MASK})
    assert secure.load("youtube")["api_key"]=="very-secret-key"
    assert "very-secret-key" not in secure.redact("api_key=very-secret-key")
    secure.delete("youtube");assert not secure.exists("youtube")


def test_social_credentials_never_enter_database_or_backup(tmp_path):
    db=Database(tmp_path/"creator.db");secure=vault(db);service=SocialPlatformService(db,secure)
    service.save_configuration("tiktok",{
        "client_key":"public-key","client_secret":"client-secret-value",
        "access_token":"access-token-value","refresh_token":"refresh-token-value",
        "user_id":"user","redirect_uri":"https://localhost/callback"},True)
    stored=db.frame("SELECT config_json FROM integration_settings WHERE integration_id='tiktok_title_sync'").iloc[0]["config_json"]
    assert "client-secret-value" not in stored and "access-token-value" not in stored
    assert service.configuration("tiktok")["access_token"]=="access-token-value"
    assert service.display_configuration("tiktok")["access_token"]==MASK
    assert database_secret_findings(db)==[]
    backup=BackupService(db.path,tmp_path/"backups").create("security")
    raw=backup.read_bytes()
    for secret in (b"client-secret-value",b"access-token-value",b"refresh-token-value"):
        assert secret not in raw


def test_legacy_platform_json_is_migrated_and_securely_removed(tmp_path):
    db=Database(tmp_path/"legacy.db")
    db.execute("""CREATE TABLE integration_settings(integration_id TEXT PRIMARY KEY,enabled INTEGER,
        config_json TEXT,last_connected_at TEXT,last_error TEXT,updated_at TEXT)""")
    db.execute("INSERT INTO integration_settings VALUES('youtube_title_sync',1,?,NULL,NULL,'now')",
               (json.dumps({"api_key":"legacy-api-secret","channel_id":"channel"}),))
    secure=vault(db);service=SocialPlatformService(db,secure)
    assert service.configuration("youtube")["api_key"]=="legacy-api-secret"
    assert "legacy-api-secret" not in db.path.read_bytes().decode("latin1")
    assert database_secret_findings(db)==[]


def test_token_refresh_rotates_vault_value_without_returning_token(tmp_path,monkeypatch):
    db=Database(tmp_path/"refresh.db");secure=vault(db);service=SocialPlatformService(db,secure)
    service.save_configuration("tiktok",{"client_key":"key","client_secret":"secret",
        "access_token":"old-token","refresh_token":"old-refresh","user_id":"user","redirect_uri":"https://local"})
    monkeypatch.setattr(service,"_post_form",lambda *_args,**_kwargs:{"access_token":"new-token","refresh_token":"new-refresh","expires_in":3600})
    result=service.refresh_access_token("tiktok")
    assert result=={"refreshed":True,"expires_in":3600}
    assert secure.load("tiktok")["access_token"]=="new-token"
    assert "new-token" not in json.dumps(db.frame("SELECT * FROM integration_settings").to_dict("records"))


def test_tiktok_revoke_happens_before_local_credentials_are_cleared(tmp_path,monkeypatch):
    db=Database(tmp_path/"revoke.db");secure=vault(db);service=SocialPlatformService(db,secure)
    service.save_configuration("tiktok",{"client_key":"key","client_secret":"secret","access_token":"token",
        "refresh_token":"refresh","user_id":"user","redirect_uri":"https://local"})
    calls=[];monkeypatch.setattr(service,"_post_form",lambda url,values:calls.append((url,dict(values))) or {})
    status=service.revoke_and_disconnect("tiktok")
    assert calls[0][0].endswith("/v2/oauth/revoke/")
    assert calls[0][1]["token"]=="token"
    assert status["configured"] is False and not secure.exists("tiktok")


def test_live_twitch_and_obs_secrets_migrate_out_of_columns(tmp_path):
    db=Database(tmp_path/"live.db");secure=vault(db);service=LiveStreamService(db,credential_vault=secure)
    service.update_settings(twitch_enabled=1,twitch_client_id="client",twitch_broadcaster_id="broadcaster",
                            twitch_access_token="live-token",twitch_refresh_token="live-refresh",
                            obs_enabled=1,obs_password="obs-secret")
    row=db.frame("SELECT * FROM live_integration_settings").iloc[0]
    assert not row["twitch_access_token"] and not row["twitch_refresh_token"] and not row["obs_password"]
    assert service.settings()["twitch_access_token"]=="live-token"
    assert service.display_settings()["obs_password"]==MASK
    assert database_secret_findings(db)==[]
    service.disconnect_integration("twitch");assert not secure.load("twitch")


def test_generic_integrations_split_sensitive_fields(tmp_path):
    db=Database(tmp_path/"integrations.db");secure=vault(db);manager=IntegrationManager(db,secure)
    manager.save_configuration("discord",{"server":"example","password":"discord-secret"},True)
    stored=db.frame("SELECT config_json FROM integration_settings WHERE integration_id='discord'").iloc[0]["config_json"]
    assert json.loads(stored)=={"server":"example"}
    assert secure.load("discord")=={"password":"discord-secret"}


def test_logging_filter_removes_bearer_tokens_and_named_secrets():
    record=logging.LogRecord("test",logging.ERROR,"",0,
        "Authorization: Bearer raw-token api_key=super-secret password=hunter2",(),None)
    SensitiveDataFilter().filter(record);message=record.getMessage()
    assert "raw-token" not in message and "super-secret" not in message and "hunter2" not in message
    assert message.count("[REDACTED]")>=3
