from __future__ import annotations
from collections import defaultdict
from dataclasses import asdict
from typing import Any
from creator_intelligence.core.contracts import (
    ModuleMetadata, NavigationItem, ServiceBinding, ImporterBinding, PluginLoadError
)

class ModuleRegistry:
    def __init__(self, context):
        self.context = context
        self.modules: dict[str, ModuleMetadata] = {}
        self.navigation: list[NavigationItem] = []
        self.services: dict[str, ServiceBinding] = {}
        self.importers: dict[str, ImporterBinding] = {}
        self.hooks: dict[str, list] = defaultdict(list)
        self.failures: list[dict[str, str]] = []

    def register_module(self, metadata: ModuleMetadata) -> None:
        if metadata.module_id in self.modules:
            raise PluginLoadError(f"Duplicate module id: {metadata.module_id}")
        self.modules[metadata.module_id] = metadata

    def register_navigation(self, item: NavigationItem) -> None:
        self.navigation.append(item)

    def register_service(self, binding: ServiceBinding) -> None:
        if binding.key in self.services:
            raise PluginLoadError(f"Duplicate service key: {binding.key}")
        self.services[binding.key] = binding

    def register_importer(self, binding: ImporterBinding) -> None:
        if binding.importer_id in self.importers:
            raise PluginLoadError(f"Duplicate importer id: {binding.importer_id}")
        self.importers[binding.importer_id] = binding

    def register_hook(self, event: str, callback) -> None:
        self.hooks[event].append(callback)

    def emit(self, event: str, **payload) -> list[Any]:
        results = []
        for callback in self.hooks.get(event, []):
            results.append(callback(self.context, **payload))
        return results

    def resolve(self, key: str):
        if key in self.context.services:
            return self.context.services[key]
        binding = self.services.get(key)
        if not binding:
            raise KeyError(f"Unknown service: {key}")
        value = binding.factory(self.context)
        if binding.singleton:
            self.context.services[key] = value
        return value

    def build_navigation(self):
        return sorted(self.navigation, key=lambda item: (item.order, item.label.lower()))

    def module_status(self):
        return [
            {
                **asdict(meta),
                "loaded": True,
                "failure": None,
            }
            for meta in self.modules.values()
        ] + [
            {
                "module_id": failure.get("module_id", "unknown"),
                "name": failure.get("module_id", "unknown"),
                "version": "",
                "category": "",
                "description": "",
                "dependencies": (),
                "enabled_by_default": False,
                "loaded": False,
                "failure": failure.get("error"),
            }
            for failure in self.failures
        ]
