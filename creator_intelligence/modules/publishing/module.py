from creator_intelligence.core.contracts import ModuleMetadata, NavigationItem, ServiceBinding
from creator_intelligence.services.edited_content_intake import EditedContentIntakeService
from creator_intelligence.services.packaging import PackagingReviewService
from creator_intelligence.services.publishing_planner import PublishingPlannerService
from creator_intelligence.services.platform_publishing import PlatformPublishingService


def _page(registry):
    from creator_intelligence.ui.pages.publishing import PublishingPage
    return PublishingPage(
        registry.resolve("publishing"),
        registry.resolve("edited_content_intake"),
        registry.resolve("platform_publishing"),
    )

def _review_page(registry):
    from creator_intelligence.ui.pages.packaging_review import PackagingReviewPage
    return PackagingReviewPage(registry.resolve("packaging_review"))

class PublishingModule:
    metadata=ModuleMetadata(
        module_id="publishing",name="Publishing Planner",
        version="1.1.0",category="content",
        description="Publishing calendar, edited-content intake, recurring slots, deadlines, readiness, and timing recommendations.",
        dependencies=("storage","content","production","transcripts","analytics")
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
            "platform_publishing",
            lambda ctx: PlatformPublishingService(
                ctx.db,
                registry.resolve("social_platforms"),
                registry.resolve("publishing"),
            ),
            module_id=self.metadata.module_id,
        ))
        registry.register_service(ServiceBinding(
            "edited_content_intake",
            lambda ctx: EditedContentIntakeService(
                ctx.db,
                registry.resolve("publishing"),
                registry.resolve("folder_watcher"),
                transcript_service=registry.resolve("transcripts"),
                video_processing_service=registry.resolve("video_processing"),
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "packaging_review",
            lambda ctx: PackagingReviewService(
                ctx.db,registry.resolve("publishing"),registry.resolve("transcripts")
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
def create_module():
    return PublishingModule()
