from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ApplicationContext:
    db: Any
    settings: Any = None
    logger: Any = None
    services: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        if key in self.services:
            return self.services[key]
        raise KeyError(f"Service not registered: {key}")

    def set(self, key: str, value: Any) -> None:
        self.services[key] = value
