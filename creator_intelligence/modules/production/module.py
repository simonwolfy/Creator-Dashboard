from creator_intelligence.core.contracts import ModuleMetadata,ServiceBinding,NavigationItem
from creator_intelligence.services.production_pipeline import ProductionPipelineService


def _page(registry):
    from creator_intelligence.ui.pages.production_pipeline import ProductionPipelinePage
    return ProductionPipelinePage(registry.resolve("production"))


class ProductionModule:
    metadata=ModuleMetadata(
        module_id="production",name="Production Management",
        version="1.1.0",category="content",
        description=(
            "Projects, editor assignments, transcript clip queue, export presets, "
            "editor notes, deliveries, reviews, revisions, and workload."
        ),
        dependencies=("storage","content")
    )

    def register(self,registry):
        registry.register_service(ServiceBinding(
            "production",
            lambda ctx: ProductionPipelineService(
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
