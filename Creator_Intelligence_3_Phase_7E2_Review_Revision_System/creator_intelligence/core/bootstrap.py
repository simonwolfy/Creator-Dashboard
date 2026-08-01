from __future__ import annotations
import logging
from pathlib import Path
from creator_intelligence.core.context import ApplicationContext
from creator_intelligence.core.registry import ModuleRegistry
from creator_intelligence.core.loader import ModuleLoader

def bootstrap_application(db, settings=None):
    context = ApplicationContext(
        db=db,
        settings=settings,
        logger=logging.getLogger("creator_intelligence")
    )
    registry = ModuleRegistry(context)
    config_path = Path(__file__).resolve().parents[2] / "config" / "modules.json"
    loader = ModuleLoader(registry, config_path)
    loader.load_all()
    context.set("registry", registry)
    return context, registry
