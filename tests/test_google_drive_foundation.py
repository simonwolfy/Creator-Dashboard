from __future__ import annotations

import json
from pathlib import Path

from creator_intelligence.data.database import Database
from creator_intelligence.services.google_drive import GoogleDriveService


class MemoryCredentialStore:
    def __init__(self):
        self.value = None

    def save(self, value):
        self.value = value

    def load(self):
        return self.value

    def exists(self):
        return bool(self.value)

    def delete(self):
        self.value = None


class FakeCredentials:
    def to_json(self):
        return json.dumps({"token": "safe-test-token", "refresh_token": "refresh"})


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeAbout:
    def get(self, **_kwargs):
        return FakeRequest(
            {"user": {"emailAddress": "creator@example.com", "displayName": "Creator"}}
        )


class FakeDrive:
    def about(self):
        return FakeAbout()


def make_service(tmp_path: Path):
    db = Database(tmp_path / "creator.db")
    db.migrate()
    store = MemoryCredentialStore()
    service = GoogleDriveService(
        db,
        credential_store=store,
        oauth_factory=lambda _path, _scopes: FakeCredentials(),
        drive_factory=lambda _credentials: FakeDrive(),
    )
    return service, store, db


def write_client_file(tmp_path: Path) -> Path:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps({"installed": {"client_id": "test"}}), encoding="utf-8")
    return path


def test_migration_creates_connection_record(tmp_path):
    service, _store, db = make_service(tmp_path)
    assert db.scalar("SELECT COUNT(*) FROM google_drive_connections") == 1
    assert service.status().status == "Not configured"


def test_configure_validates_and_records_client_file(tmp_path):
    service, _store, _db = make_service(tmp_path)
    path = write_client_file(tmp_path)
    service.configure(str(path))
    status = service.status()
    assert status.configured is True
    assert status.client_secrets_path == str(path.resolve())
    assert status.status == "Configured"


def test_connect_stores_token_outside_database(tmp_path):
    service, store, db = make_service(tmp_path)
    service.configure(str(write_client_file(tmp_path)))
    status = service.connect()
    assert status.connected is True
    assert status.account_email == "creator@example.com"
    assert "safe-test-token" in store.value
    database_text = str(db.frame("SELECT * FROM google_drive_connections").to_dict())
    assert "safe-test-token" not in database_text


def test_disconnect_removes_secure_token(tmp_path):
    service, store, _db = make_service(tmp_path)
    service.configure(str(write_client_file(tmp_path)))
    service.connect()
    service.disconnect()
    assert store.value is None
    assert service.status().connected is False
    assert service.status().status == "Configured"


def test_invalid_client_file_is_rejected(tmp_path):
    service, _store, _db = make_service(tmp_path)
    path = tmp_path / "wrong.json"
    path.write_text("{}", encoding="utf-8")
    try:
        service.configure(str(path))
    except ValueError as exc:
        assert "OAuth client-secrets" in str(exc)
    else:
        raise AssertionError("Invalid client file should have been rejected")
