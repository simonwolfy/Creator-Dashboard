from creator_intelligence.core.contracts import (
    ModuleMetadata,ServiceBinding,NavigationItem
)
from creator_intelligence.services.highlight_learning import HighlightLearningService

def _page(registry):
    from creator_intelligence.ui.pages.highlight_learning import HighlightLearningPage
    return HighlightLearningPage(registry.resolve("highlight_learning"))

class HighlightLearningModule:
    metadata=ModuleMetadata(
        module_id="highlight_learning",
        name="Highlight Learning Engine",
        version="1.0.0",
        category="media",
        description="Personalized highlight scoring from review decisions and published performance.",
        dependencies=("storage","highlight_scoring")
    )

    def register(self,registry):
        registry.register_service(ServiceBinding(
            "highlight_learning",
            lambda ctx:HighlightLearningService(
                ctx.db,
                registry.resolve("highlight_scoring"),
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Highlight Learning",lambda:_page(registry),
            order=19,module_id=self.metadata.module_id
        ))

def create_module():
    return HighlightLearningModule()
