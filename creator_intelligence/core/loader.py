from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path

from creator_intelligence.core.contracts import PluginLoadError
from creator_intelligence.core.versioning import MODULE_MANIFEST_SCHEMA_VERSION

DEFAULT_MODULES = (
    "creator_intelligence.modules.storage.module",
    "creator_intelligence.modules.analytics.module",
    "creator_intelligence.modules.predictions.module",
    "creator_intelligence.modules.content.module",
    "creator_intelligence.modules.imports.module",
    "creator_intelligence.modules.integrations.module",
    "creator_intelligence.modules.system.module",
    "creator_intelligence.modules.live.module",
    "creator_intelligence.modules.highlights.module",
    "creator_intelligence.modules.production.module",
    "creator_intelligence.modules.video_processing.module",
    "creator_intelligence.modules.transcripts.module",
    "creator_intelligence.modules.publishing.module",
    "creator_intelligence.modules.creator_dna.module",
    "creator_intelligence.modules.creator_planner.module",
    "creator_intelligence.modules.scene_intelligence.module",
    "creator_intelligence.modules.highlight_scoring.module",
    "creator_intelligence.modules.content_recommendations.module",
    "creator_intelligence.modules.opportunity_workload.module",
    "creator_intelligence.modules.highlight_learning.module",
    "creator_intelligence.modules.editor_workspace.module",
    "creator_intelligence.modules.review_revision.module",
)
REQUIRED_MODULE_IDS = frozenset(path.split(".")[-2] for path in DEFAULT_MODULES)


@dataclass(frozen=True)
class ModuleManifest:
    schema_version: int
    paths: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> ModuleManifest:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginLoadError(f"Cannot read module manifest {path}: {exc}") from exc
        version = payload.get("schema_version")
        if version != MODULE_MANIFEST_SCHEMA_VERSION:
            raise PluginLoadError(
                f"Unsupported module manifest schema {version!r}; "
                f"expected {MODULE_MANIFEST_SCHEMA_VERSION}."
            )
        entries = payload.get("modules")
        if not isinstance(entries, list):
            raise PluginLoadError("Module manifest 'modules' must be a list.")
        paths = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise PluginLoadError(f"Module manifest entry {index} needs a string path.")
            if entry.get("enabled", True):
                paths.append(entry["path"])
        if len(paths) != len(set(paths)):
            raise PluginLoadError("Module manifest contains duplicate enabled paths.")
        return cls(version, tuple(paths))


class ModuleLoader:
    def __init__(self, registry, config_path: Path | None = None):
        self.registry = registry
        self.config_path = config_path

    def configured_modules(self) -> tuple[str, ...]:
        if not self.config_path or not self.config_path.exists():
            return DEFAULT_MODULES
        return ModuleManifest.load(self.config_path).paths

    def load_all(self) -> list[str]:
        loaded = []
        for module_path in self.configured_modules():
            try:
                py_module = importlib.import_module(module_path)
                module = py_module.create_module()
                self._validate_dependencies(module)
                self.registry.register_module(module.metadata)
                module.register(self.registry)
                loaded.append(module.metadata.module_id)
            except Exception as exc:
                self.registry.failures.append(
                    {"module_id": module_path, "error": f"{type(exc).__name__}: {exc}"}
                )
        return loaded

    def assert_required_modules(self) -> None:
        loaded = set(self.registry.modules)
        missing = sorted(REQUIRED_MODULE_IDS - loaded)
        unexpected = sorted(loaded - REQUIRED_MODULE_IDS)
        failures = [item["module_id"] for item in self.registry.failures]
        if missing or unexpected or failures:
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if unexpected:
                details.append(f"unexpected: {', '.join(unexpected)}")
            if failures:
                details.append(f"failed: {', '.join(failures)}")
            raise PluginLoadError("Startup module assertion failed (" + "; ".join(details) + ").")

    def _validate_dependencies(self, module) -> None:
        missing = [
            dependency
            for dependency in module.metadata.dependencies
            if dependency not in self.registry.modules
        ]
        if missing:
            raise PluginLoadError(
                f"{module.metadata.module_id} requires unloaded modules: {', '.join(missing)}"
            )
