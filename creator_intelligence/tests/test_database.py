from pathlib import Path
from tempfile import TemporaryDirectory
from creator_intelligence.data.database import Database

def run():
    with TemporaryDirectory() as temp:
        db = Database(Path(temp) / "test.db")
        db.migrate()
        assert db.table_exists("schema_migrations")
        assert db.table_exists("app_settings")
        assert db.integrity_check() == "ok"
    print("database tests passed")

if __name__ == "__main__":
    run()
