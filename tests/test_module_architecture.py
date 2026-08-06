import json
from pathlib import Path

import pytest

from creator_intelligence.core.context import ApplicationContext
from creator_intelligence.core.contracts import PluginLoadError, ServiceBinding
from creator_intelligence.core.loader import (
    DEFAULT_MODULES,
    REQUIRED_MODULE_IDS,
    ModuleLoader,
    ModuleManifest,
)
from creator_intelligence.core.registry import ModuleRegistry


class FakeDB:
    path = Path("fake.db")

def test_registry_resolves_singletons():
    context = ApplicationContext(db=FakeDB())
    registry = ModuleRegistry(context)
    calls = {"count": 0}

    def factory(ctx):
        calls["count"] += 1
        return object()

    registry.register_service(ServiceBinding("x", factory))
    assert registry.resolve("x") is registry.resolve("x")
    assert calls["count"] == 1

def test_navigation_ordering():
    from creator_intelligence.core.contracts import NavigationItem
    context = ApplicationContext(db=FakeDB())
    registry = ModuleRegistry(context)
    registry.register_navigation(NavigationItem("Late", lambda: None, order=20))
    registry.register_navigation(NavigationItem("Early", lambda: None, order=10))
    assert [x.label for x in registry.build_navigation()] == ["Early", "Late"]


def test_canonical_manifest_contains_exact_required_modules():
    manifest = ModuleManifest.load(Path("config/modules.json"))
    assert manifest.paths == DEFAULT_MODULES
    assert {path.split(".")[-2] for path in manifest.paths} == REQUIRED_MODULE_IDS
    assert "creator_intelligence.modules.creator_dna.module" in manifest.paths


def test_malformed_manifest_fails_instead_of_silently_falling_back(tmp_path):
    path = tmp_path / "modules.json"
    path.write_text(json.dumps({"schema_version": 99, "modules": []}), encoding="utf-8")
    with pytest.raises(PluginLoadError, match="Unsupported module manifest schema"):
        ModuleManifest.load(path)


def test_required_module_assertion_reports_missing_module():
    context = ApplicationContext(db=FakeDB())
    registry = ModuleRegistry(context)
    loader = ModuleLoader(registry)
    with pytest.raises(PluginLoadError, match="missing:"):
        loader.assert_required_modules()
