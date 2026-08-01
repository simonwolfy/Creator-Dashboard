from creator_intelligence.core.contracts import (
    ModuleMetadata,ServiceBinding,NavigationItem
)
from creator_intelligence.services.live_stream import LiveStreamService
from creator_intelligence.services.live_integrations import (
    TwitchLiveAdapter,OBSLiveAdapter
)

def _page(registry):
    from creator_intelligence.ui.pages.live_stream import LiveStreamPage
    return LiveStreamPage(registry.resolve("live_stream"))

class LiveModule:
    metadata=ModuleMetadata(
        module_id="live",
        name="Live Stream Intelligence",
        version="1.0.0",
        category="analytics",
        description="Live sessions, metric snapshots, projections, milestones, stream markers, and integration adapters.",
        dependencies=("storage","imports"),
    )

    def register(self,registry):
        registry.register_service(ServiceBinding(
            "live_stream",
            lambda ctx:LiveStreamService(
                ctx.db,
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "twitch_live_adapter",
            lambda ctx:TwitchLiveAdapter(registry.resolve("live_stream")),
            module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "obs_live_adapter",
            lambda ctx:OBSLiveAdapter(registry.resolve("live_stream")),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Live Stream",lambda:_page(registry),
            order=8,module_id=self.metadata.module_id
        ))

def create_module():
    return LiveModule()
