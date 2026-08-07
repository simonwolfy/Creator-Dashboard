from creator_intelligence.core.contracts import ModuleMetadata, NavigationItem, ServiceBinding
from creator_intelligence.services.creator_dna import CreatorDNAService


def _page(registry):
    from creator_intelligence.ui.pages.creator_dna import CreatorDNAPage
    return CreatorDNAPage(registry.resolve("creator_dna"))


class CreatorDNAModule:
    metadata = ModuleMetadata(
        module_id="creator_dna",
        name="Creator Intelligence",
        version="1.0.0",
        category="intelligence",
        description=(
            "Local creator profile, packaging patterns, learning events, backlog, "
            "and prioritized next-action recommendations."
        ),
        dependencies=("storage", "transcripts"),
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            "creator_dna",
            lambda ctx: CreatorDNAService(ctx.db),
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "Creator Intelligence",
            lambda: _page(registry),
            order=18,
            module_id=self.metadata.module_id,
        ))


def create_module():
    return CreatorDNAModule()
