from creator_intelligence.core.contracts import ModuleMetadata, ServiceBinding, NavigationItem
from creator_intelligence.services.cross_platform import CrossPlatformService
from creator_intelligence.services.pipeline_intelligence import PipelineIntelligenceService

def _cross_platform_page(registry):
    from creator_intelligence.ui.pages.cross_platform import CrossPlatformPage
    return CrossPlatformPage(registry.resolve("cross_platform"))

def _pipeline_page(registry):
    from creator_intelligence.ui.pages.pipeline import PipelinePage
    return PipelinePage(registry.resolve("pipeline"))

class ContentModule:
    metadata = ModuleMetadata(
        module_id="content",
        name="Content Operations",
        version="1.0.0",
        category="content",
        description="Cross-platform linking, attribution, repurposing, pipeline, and calendar.",
        dependencies=("storage","analytics"),
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            "cross_platform", lambda ctx: CrossPlatformService(ctx.db),
            module_id=self.metadata.module_id,
        ))
        registry.register_service(ServiceBinding(
            "pipeline", lambda ctx: PipelineIntelligenceService(ctx.db),
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "Cross-platform", lambda: _cross_platform_page(registry), order=40,
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "Content Pipeline", lambda: _pipeline_page(registry), order=60,
            module_id=self.metadata.module_id,
        ))

def create_module():
    return ContentModule()
