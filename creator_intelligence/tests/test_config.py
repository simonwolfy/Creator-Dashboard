from pathlib import Path
from tempfile import TemporaryDirectory
from creator_intelligence.core.config import ConfigService, AppConfig

def run():
    with TemporaryDirectory() as temp:
        service = ConfigService(Path(temp) / "settings.json")
        cfg = service.load()
        cfg.channel_name = "TestChannel"
        service.save(cfg)
        loaded = service.load()
        assert loaded.channel_name == "TestChannel"
    print("config tests passed")

if __name__ == "__main__":
    run()
