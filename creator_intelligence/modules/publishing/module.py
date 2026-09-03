from creator_intelligence.core.contracts import ModuleMetadata, NavigationItem, ServiceBinding
from creator_intelligence.services.packaging import PackagingReviewService
from creator_intelligence.services.publishing_planner import PublishingPlannerService


def _page(registry):
    from creator_intelligence.ui.pages.publishing import PublishingPage
    return PublishingPage(registry.resolve("publishing"))

def _review_page(registry):
    from creator_intelligence.ui.pages.packaging_review import PackagingReviewPage
    return PackagingReviewPage(registry.resolve("packaging_review"))

def _rollout_page(registry):
    from creator_intelligence.ui.pages.content_rollout import ContentRolloutPage
    return ContentRolloutPage(registry.resolve("content_rollout"))

class PublishingModule:
    metadata=ModuleMetadata(
        module_id="publishing",name="Publishing Planner",
        version="1.0.0",category="content",
        description="Publishing calendar, recurring slots, deadlines, readiness, and timing recommendations.",
        dependencies=("storage","content","production","transcripts")
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
        registry.register_service(ServiceBinding(
            "content_rollout",
            lambda ctx: __import__(
                "creator_intelligence.services.content_rollout",fromlist=["ContentRolloutService"]
            ).ContentRolloutService(
                ctx.db,registry.resolve("transcripts"),registry.resolve("publishing"),
                registry.resolve("google_drive")
            ),module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "packaging_review",
            lambda ctx: PackagingReviewService(
                ctx.db,registry.resolve("publishing"),registry.resolve("transcripts"),
                registry.resolve("google_drive")
            ),module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Publishing",lambda:_page(registry),order=11,
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Packaging Review",lambda:_review_page(registry),order=12,
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Content Intelligence",lambda:_rollout_page(registry),order=13,
            module_id=self.metadata.module_id
        ))
def create_module():
    return PublishingModule()
