from creator_intelligence.core.contracts import ModuleMetadata,ServiceBinding,NavigationItem
from creator_intelligence.services.creator_planner import CreatorPlannerService

def _page(registry):
    from creator_intelligence.ui.pages.creator_planner import CreatorPlannerPage
    return CreatorPlannerPage(registry.resolve("creator_planner"))

class CreatorPlannerModule:
    metadata=ModuleMetadata(
        module_id="creator_planner",name="Creator Planner",
        version="1.0.0",category="content",
        description="VOD-first content source planning, deliverables, priorities, and source yield.",
        dependencies=("storage","highlights","production","publishing")
    )
    def register(self,registry):
        registry.register_service(ServiceBinding(
            "creator_planner",
            lambda ctx: CreatorPlannerService(
                ctx.db,
                registry.resolve("production"),
                registry.resolve("publishing"),
                registry.resolve("highlights"),
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Creator Planner",lambda:_page(registry),order=12,
            module_id=self.metadata.module_id
        ))
def create_module():
    return CreatorPlannerModule()
