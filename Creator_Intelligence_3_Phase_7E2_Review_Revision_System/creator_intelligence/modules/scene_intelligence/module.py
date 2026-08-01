from creator_intelligence.core.contracts import (
    ModuleMetadata,ServiceBinding,NavigationItem
)
from creator_intelligence.services.scene_intelligence import SceneIntelligenceService

def _page(registry):
    from creator_intelligence.ui.pages.scene_intelligence import SceneIntelligencePage
    return SceneIntelligencePage(registry.resolve("scene_intelligence"))

class SceneIntelligenceModule:
    metadata=ModuleMetadata(
        module_id="scene_intelligence",
        name="Scene and Chapter Intelligence",
        version="1.0.0",
        category="media",
        description="Topic segmentation, silence analysis, low-value detection, and unified VOD timelines.",
        dependencies=("storage","video_processing","transcripts")
    )

    def register(self,registry):
        registry.register_service(ServiceBinding(
            "scene_intelligence",
            lambda ctx:SceneIntelligenceService(
                ctx.db,
                registry.resolve("transcripts"),
                registry.resolve("video_processing"),
                registry.resolve("live_stream"),
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Scene Intelligence",lambda:_page(registry),
            order=15,module_id=self.metadata.module_id
        ))

def create_module():
    return SceneIntelligenceModule()
