from creator_intelligence.core.contracts import (
    ModuleMetadata,ServiceBinding,NavigationItem
)
from creator_intelligence.services.highlights import HighlightDetectionService

def _page(registry):
    from creator_intelligence.ui.pages.highlights import HighlightsPage
    return HighlightsPage(registry.resolve("highlights"))

class HighlightsModule:
    metadata = ModuleMetadata(
        module_id="highlights",
        name="Highlight Detection",
        version="1.0.0",
        category="content",
        description="Signal grouping, candidate scoring, clip boundaries, review, and pipeline export.",
        dependencies=("storage","live","content","imports"),
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            "highlights",
            lambda ctx: HighlightDetectionService(
                ctx.db,
                registry.resolve("live_stream"),
                registry.resolve("pipeline"),
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Highlights",lambda:_page(registry),
            order=9,module_id=self.metadata.module_id
        ))

def create_module():
    return HighlightsModule()
