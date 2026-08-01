from creator_intelligence.core.contracts import ModuleMetadata, ServiceBinding

class StorageModule:
    metadata = ModuleMetadata(
        module_id="storage",
        name="Storage",
        version="1.0.0",
        category="storage",
        description="Database, repositories, migrations, backups, and file paths."
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            key="database",
            factory=lambda ctx: ctx.db,
            singleton=True,
            module_id=self.metadata.module_id,
        ))

def create_module():
    return StorageModule()
