from creator_intelligence.core.contracts import (
    ModuleMetadata, ServiceBinding, NavigationItem
)
from creator_intelligence.services.scene_intelligence import SceneIntelligenceService
from creator_intelligence.services.visual_scene_engine import VisualSceneEngineService


def _page(registry):
    from creator_intelligence.ui.pages.scene_intelligence import SceneIntelligencePage
    return SceneIntelligencePage(registry.resolve("scene_intelligence"))


def _visual_page(registry):
    from creator_intelligence.ui.pages.visual_scene_engine import VisualSceneEnginePage
    return VisualSceneEnginePage(registry.resolve("visual_scene_engine"))


class SceneIntelligenceModule:
    metadata = ModuleMetadata(
        module_id="scene_intelligence",
        name="Scene and Chapter Intelligence",
        version="1.1.0",
        category="media",
        description=(
            "Transcript topic segmentation, silence analysis, visual cut detection, "
            "low-value detection, and unified VOD timelines."
        ),
        dependencies=("storage", "video_processing", "transcripts")
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            "scene_intelligence",
            lambda ctx: SceneIntelligenceService(
                ctx.db,
                registry.resolve("transcripts"),
                registry.resolve("video_processing"),
                registry.resolve("live_stream"),
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "visual_scene_engine",
            lambda ctx: VisualSceneEngineService(
                ctx.db,
                registry.resolve("video_processing")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Scene Intelligence", lambda: _page(registry),
            order=17, module_id="scene_intelligence:chapters"
        ))
        registry.register_navigation(NavigationItem(
            "Visual Scene Detection", lambda: _visual_page(registry),
            order=18, module_id="scene_intelligence:visual-cuts"
        ))


def create_module():
    return SceneIntelligenceModule()
