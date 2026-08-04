from creator_intelligence.core.contracts import (
    ModuleMetadata, ServiceBinding, NavigationItem
)
from creator_intelligence.services.local_whisper_production import (
    LocalWhisperProductionService,
)


def _page(registry):
    from creator_intelligence.ui.pages.creator_packaging_page import (
        CreatorPackagingPage,
    )
    return CreatorPackagingPage(registry.resolve("transcripts"))


class TranscriptModule:
    metadata = ModuleMetadata(
        module_id="transcripts",
        name="Transcript Engine",
        version="1.8.0",
        category="media",
        description=(
            "GPU-accelerated transcription, transcript editing, clip-specific "
            "creator packaging intelligence, duplicate-resistant titles, "
            "platform-ready metadata, production handoff, chapters, search, "
            "statistics, and professional exports."
        ),
        dependencies=("storage", "video_processing"),
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            "transcripts",
            lambda ctx: LocalWhisperProductionService(
                ctx.db,
                registry.resolve("video_processing"),
                registry.resolve("notifications"),
            ),
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "Transcripts",
            lambda: _page(registry),
            order=14,
            module_id=self.metadata.module_id,
        ))


def create_module():
    return TranscriptModule()
