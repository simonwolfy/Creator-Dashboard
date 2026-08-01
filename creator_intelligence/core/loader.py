from __future__ import annotations
import importlib
import json
from pathlib import Path
from creator_intelligence.core.contracts import PluginLoadError

DEFAULT_MODULES = [
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
    "creator_intelligence.modules.publishing.module",
    "creator_intelligence.modules.creator_planner.module",
    "creator_intelligence.modules.video_processing.module",
    "creator_intelligence.modules.transcripts.module",
    "creator_intelligence.modules.scene_intelligence.module",
    "creator_intelligence.modules.highlight_scoring.module",
    "creator_intelligence.modules.content_recommendations.module",
    "creator_intelligence.modules.opportunity_workload.module",
    "creator_intelligence.modules.highlight_learning.module",
    "creator_intelligence.modules.editor_workspace.module",
    "creator_intelligence.modules.review_revision.module",
]

class ModuleLoader:
    def __init__(self, registry, config_path: Path | None = None):
        self.registry = registry
        self.config_path = config_path

    def configured_modules(self):
        if not self.config_path or not self.config_path.exists():
            return DEFAULT_MODULES
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            configured = [x["path"] for x in config.get("modules", []) if x.get("enabled", True)]
            extras = config.get("enabled_modules", [])
            return list(dict.fromkeys(configured + extras))
        except Exception:
            return DEFAULT_MODULES

    def load_all(self):
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
                self.registry.failures.append({
                    "module_id": module_path,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        return loaded

    def _validate_dependencies(self, module):
        missing = [
            dependency for dependency in module.metadata.dependencies
            if dependency not in self.registry.modules
        ]
        if missing:
            raise PluginLoadError(
                f"{module.metadata.module_id} requires unloaded modules: {', '.join(missing)}"
            )
