from creator_intelligence.core.contracts import ModuleMetadata, NavigationItem, ServiceBinding
from creator_intelligence.services.asset_management import AssetManagementService
from creator_intelligence.services.content_library import ContentLibraryService
from creator_intelligence.services.creator_dashboard import CreatorDashboardService
from creator_intelligence.services.cross_platform import CrossPlatformService
from creator_intelligence.services.folder_watcher import FolderWatcherService
from creator_intelligence.services.google_drive import GoogleDriveService
from creator_intelligence.services.pipeline_intelligence import PipelineIntelligenceService


def _dashboard_page(registry):
    from creator_intelligence.ui.pages.creator_dashboard import CreatorDashboardPage

    return CreatorDashboardPage(registry.resolve("creator_dashboard"))


def _asset_library_page(registry):
    from creator_intelligence.ui.pages.asset_library import AssetLibraryPage

    return AssetLibraryPage(registry.resolve("asset_management"))


def _folder_watcher_page(registry):
    from creator_intelligence.ui.pages.folder_watcher import FolderWatcherPage

    return FolderWatcherPage(registry.resolve("folder_watcher"))


def _google_drive_page(registry):
    from creator_intelligence.ui.pages.google_drive import GoogleDrivePage

    return GoogleDrivePage(registry.resolve("google_drive"))


def _cross_platform_page(registry):
    from creator_intelligence.ui.pages.cross_platform import CrossPlatformPage

    return CrossPlatformPage(registry.resolve("cross_platform"))


def _pipeline_page(registry):
    from creator_intelligence.ui.pages.pipeline import PipelinePage

    return PipelinePage(registry.resolve("pipeline"))


class ContentModule:
    metadata = ModuleMetadata(
        module_id="content",
        name="Content Operations",
        version="1.5.0",
        category="content",
        description="Dashboard, asset discovery, Google Drive connection, content linking, and pipeline.",
        dependencies=("storage", "analytics"),
    )

    def register(self, registry):
        registry.register_service(
            ServiceBinding(
                "content_library",
                lambda ctx: ContentLibraryService(ctx.db),
                module_id=self.metadata.module_id,
            )
        )
        registry.register_service(
            ServiceBinding(
                "asset_management",
                lambda ctx: AssetManagementService(ctx.db),
                module_id=self.metadata.module_id,
            )
        )
        registry.register_service(
            ServiceBinding(
                "folder_watcher",
                lambda ctx: FolderWatcherService(ctx.db),
                module_id=self.metadata.module_id,
            )
        )
        registry.register_service(
            ServiceBinding(
                "google_drive",
                lambda ctx: GoogleDriveService(ctx.db),
                module_id=self.metadata.module_id,
            )
        )
        registry.register_service(
            ServiceBinding(
                "creator_dashboard",
                lambda ctx: CreatorDashboardService(ctx.db),
                module_id=self.metadata.module_id,
            )
        )
        registry.register_service(
            ServiceBinding(
                "cross_platform",
                lambda ctx: CrossPlatformService(ctx.db),
                module_id=self.metadata.module_id,
            )
        )
        registry.register_service(
            ServiceBinding(
                "pipeline",
                lambda ctx: PipelineIntelligenceService(ctx.db),
                module_id=self.metadata.module_id,
            )
        )
        registry.register_navigation(
            NavigationItem(
                "Dashboard",
                lambda: _dashboard_page(registry),
                order=0,
                module_id=self.metadata.module_id,
            )
        )
        registry.register_navigation(
            NavigationItem(
                "Asset Library",
                lambda: _asset_library_page(registry),
                order=10,
                module_id=self.metadata.module_id,
            )
        )
        registry.register_navigation(
            NavigationItem(
                "Folder Watcher",
                lambda: _folder_watcher_page(registry),
                order=20,
                module_id=self.metadata.module_id,
            )
        )
        registry.register_navigation(
            NavigationItem(
                "Google Drive",
                lambda: _google_drive_page(registry),
                order=30,
                module_id=self.metadata.module_id,
            )
        )
        registry.register_navigation(
            NavigationItem(
                "Cross-platform",
                lambda: _cross_platform_page(registry),
                order=40,
                module_id=self.metadata.module_id,
            )
        )
        registry.register_navigation(
            NavigationItem(
                "Content Pipeline",
                lambda: _pipeline_page(registry),
                order=60,
                module_id=self.metadata.module_id,
            )
        )


def create_module():
    return ContentModule()
