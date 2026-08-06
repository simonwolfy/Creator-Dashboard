from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    data: Path
    config: Path
    logs: Path
    cache: Path
    assets: Path
    exports: Path
    backups: Path
    temp: Path

    @property
    def database(self) -> Path:
        return self.data / "creator_intelligence.db"

    @property
    def metadata(self) -> Path:
        return self.root / "workspace.json"


class WorkspaceManager:
    """Creates and validates an isolated Creator Intelligence workspace."""

    METADATA_VERSION = 1

    def __init__(self, root: Path, name: str = "My Workspace"):
        root = Path(root).expanduser().resolve()
        self.name = name
        self.paths = WorkspacePaths(
            root=root,
            data=root / "data",
            config=root / "config",
            logs=root / "logs",
            cache=root / "cache",
            assets=root / "assets",
            exports=root / "exports",
            backups=root / "backups",
            temp=root / "temp",
        )

    def initialize(self) -> WorkspacePaths:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        for path in (
            self.paths.data,
            self.paths.config,
            self.paths.logs,
            self.paths.cache,
            self.paths.assets,
            self.paths.exports,
            self.paths.backups,
            self.paths.temp,
        ):
            path.mkdir(parents=True, exist_ok=True)

        if not self.paths.metadata.exists():
            self._write_metadata()
        else:
            self.validate()
        return self.paths

    def validate(self) -> dict:
        if not self.paths.metadata.exists():
            raise FileNotFoundError(f"Workspace metadata is missing: {self.paths.metadata}")
        data = json.loads(self.paths.metadata.read_text(encoding="utf-8"))
        version = int(data.get("version", 0))
        if version > self.METADATA_VERSION:
            raise RuntimeError(
                f"Workspace version {version} is newer than this application supports."
            )
        if not data.get("name"):
            raise ValueError("Workspace metadata does not contain a name.")
        return data

    def describe(self) -> dict:
        metadata = self.validate()
        return {
            **metadata,
            "root": str(self.paths.root),
            "database": str(self.paths.database),
        }

    def record_application_version(self, application_version: str) -> None:
        payload = self.validate()
        payload["application_version"] = application_version
        temporary = self.paths.metadata.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.paths.metadata)

    def _write_metadata(self) -> None:
        payload = {
            "version": self.METADATA_VERSION,
            "name": self.name,
            "application": "Creator Intelligence",
        }
        temporary = self.paths.metadata.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.paths.metadata)
