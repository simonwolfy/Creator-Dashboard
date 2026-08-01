from pathlib import Path
import sqlite3
from creator_intelligence.core.context import ApplicationContext
from creator_intelligence.core.registry import ModuleRegistry
from creator_intelligence.core.loader import ModuleLoader
from creator_intelligence.core.contracts import ModuleMetadata, ServiceBinding

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
