from creator_intelligence.core.contracts import ModuleMetadata,ServiceBinding,NavigationItem
from creator_intelligence.services.publishing_planner import PublishingPlannerService

def _page(registry):
    from creator_intelligence.ui.pages.publishing import PublishingPage
    return PublishingPage(registry.resolve("publishing"))

class PublishingModule:
    metadata=ModuleMetadata(
        module_id="publishing",name="Publishing Planner",
        version="1.0.0",category="content",
        description="Publishing calendar, recurring slots, deadlines, readiness, and timing recommendations.",
        dependencies=("storage","content","production")
    )
    def register(self,registry):
        registry.register_service(ServiceBinding(
            "publishing",
            lambda ctx: PublishingPlannerService(
                ctx.db,registry.resolve("production"),
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Publishing",lambda:_page(registry),order=11,
            module_id=self.metadata.module_id
        ))
def create_module():
    return PublishingModule()
