from creator_intelligence.core.contracts import ModuleMetadata, ServiceBinding
from creator_intelligence.services.integrations import IntegrationManager

class IntegrationsModule:
    metadata = ModuleMetadata(
        module_id="integrations",
        name="Integrations",
        version="1.0.0",
        category="integrations",
        description="OBS, StreamElements, Streamer.bot, Discord, and future platform adapters.",
        dependencies=("storage",),
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            "integrations", lambda ctx: IntegrationManager(ctx.db),
            module_id=self.metadata.module_id,
        ))

def create_module():
    return IntegrationsModule()
