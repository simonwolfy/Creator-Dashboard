from creator_intelligence.core.contracts import (
    ModuleMetadata,ServiceBinding,NavigationItem
)
from creator_intelligence.services.transcripts import TranscriptService

def _page(registry):
    from creator_intelligence.ui.pages.transcripts import TranscriptsPage
    return TranscriptsPage(registry.resolve("transcripts"))

class TranscriptModule:
    metadata=ModuleMetadata(
        module_id="transcripts",
        name="Transcript Engine",
        version="1.0.0",
        category="media",
        description="Timestamped transcription, transcript import, search, and chapter generation.",
        dependencies=("storage","video_processing")
    )

    def register(self,registry):
        registry.register_service(ServiceBinding(
            "transcripts",
            lambda ctx:TranscriptService(
                ctx.db,
                registry.resolve("video_processing"),
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Transcripts",lambda:_page(registry),
            order=14,module_id=self.metadata.module_id
        ))

def create_module():
    return TranscriptModule()
