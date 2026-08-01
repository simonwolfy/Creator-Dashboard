from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

@dataclass(frozen=True)
class ModuleMetadata:
    module_id: str
    name: str
    version: str
    category: str
    description: str = ""
    dependencies: tuple[str, ...] = ()
    enabled_by_default: bool = True

@dataclass
class NavigationItem:
    label: str
    factory: Callable[[], Any]
    order: int = 100
    icon: str | None = None
    module_id: str | None = None

@dataclass
class ServiceBinding:
    key: str
    factory: Callable[["ApplicationContext"], Any]
    singleton: bool = True
    module_id: str | None = None

@dataclass
class ImporterBinding:
    importer_id: str
    label: str
    detector: Callable[[str], bool]
    importer_factory: Callable[["ApplicationContext"], Any]
    module_id: str | None = None

class ApplicationModule(Protocol):
    metadata: ModuleMetadata

    def register(self, registry: "ModuleRegistry") -> None:
        ...

class PluginLoadError(RuntimeError):
    pass
