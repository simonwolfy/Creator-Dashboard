from creator_intelligence.core.contracts import ModuleMetadata,ServiceBinding,NavigationItem
from creator_intelligence.services.production_management import ProductionManagementService

def _page(registry):
    from creator_intelligence.ui.pages.production import ProductionPage
    return ProductionPage(registry.resolve("production"))

class ProductionModule:
    metadata=ModuleMetadata(
        module_id="production",name="Production Management",
        version="1.0.0",category="content",
        description="Editor assignments, assets, deliveries, review notes, revisions, and workload.",
        dependencies=("storage","content")
    )
    def register(self,registry):
        registry.register_service(ServiceBinding(
            "production",
            lambda ctx: ProductionManagementService(
                ctx.db,registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Production",lambda:_page(registry),order=10,
            module_id=self.metadata.module_id
        ))
def create_module():
    return ProductionModule()
