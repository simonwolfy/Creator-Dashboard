from creator_intelligence.core.contracts import ModuleMetadata, ServiceBinding, NavigationItem
from creator_intelligence.services.data_quality import DataQualityService

def _goals_page(registry):
    from creator_intelligence.ui.pages.goals import GoalsPage
    return GoalsPage(registry.context.db)

def _quality_page(registry):
    from creator_intelligence.ui.pages.quality import QualityPage
    return QualityPage(registry.resolve("data_quality"))

def _modules_page(registry):
    from creator_intelligence.ui.pages.modules import ModulesPage
    return ModulesPage(registry)

def _settings_page(registry):
    from creator_intelligence.ui.pages.settings import SettingsPage
    return SettingsPage(registry.context.db,registry.context)

class SystemModule:
    metadata = ModuleMetadata(
        module_id="system",
        name="System",
        version="1.0.0",
        category="system",
        description="Goals, quality checks, settings, and module diagnostics.",
        dependencies=("storage",),
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            "data_quality", lambda ctx: DataQualityService(ctx.db),
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "Goals", lambda: _goals_page(registry),
            order=70, module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Data Quality", lambda: _quality_page(registry),
            order=80, module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Modules", lambda: _modules_page(registry),
            order=90, module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Settings", lambda: _settings_page(registry),
            order=100, module_id=self.metadata.module_id
        ))

def create_module():
    return SystemModule()
