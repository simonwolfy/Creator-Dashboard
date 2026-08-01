from creator_intelligence.core.contracts import (
    ModuleMetadata,ServiceBinding,ImporterBinding,NavigationItem
)
from creator_intelligence.services.import_center import ImportCenterService
from creator_intelligence.services.notifications import NotificationService
from creator_intelligence.services.background_watcher import BackgroundWatcherService

def _import_page(registry):
    from creator_intelligence.ui.pages.import_center import ImportCenterPage
    return ImportCenterPage(registry.resolve("import_center"))

def _watcher_page(registry):
    from creator_intelligence.ui.pages.watcher import WatcherPage
    return WatcherPage(registry.resolve("background_watcher"))

def _notifications_page(registry):
    from creator_intelligence.ui.pages.notifications import NotificationsPage
    return NotificationsPage(registry.resolve("notifications"))

class ImportsModule:
    metadata=ModuleMetadata(
        module_id="imports",
        name="Import Automation and Notifications",
        version="3.0.0",
        category="imports",
        description="Staging, watched folders, background scans, operational alerts, and notification history.",
        dependencies=("storage",),
    )

    def register(self,registry):
        registry.register_service(ServiceBinding(
            "notifications",
            lambda ctx:NotificationService(ctx.db),
            module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "import_center",
            lambda ctx:ImportCenterService(ctx.db,registry),
            module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "background_watcher",
            lambda ctx:BackgroundWatcherService(
                ctx.db,
                registry.resolve("import_center"),
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))

        for importer_id,label in [
            ("twitch_daily","Twitch daily analytics"),
            ("youtube_content","YouTube content analytics"),
            ("twitch_raids","Twitch raid history"),
        ]:
            registry.register_importer(ImporterBinding(
                importer_id=importer_id,
                label=label,
                detector=lambda path,target=importer_id:
                    registry.resolve("import_center").detect(path).export_type==target,
                importer_factory=lambda ctx:registry.resolve("import_center"),
                module_id=self.metadata.module_id
            ))

        registry.register_navigation(NavigationItem(
            "Import Center",lambda:_import_page(registry),
            order=5,module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Import Watcher",lambda:_watcher_page(registry),
            order=6,module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Notifications",lambda:_notifications_page(registry),
            order=7,module_id=self.metadata.module_id
        ))

        registry.register_hook(
            "application_started",
            lambda ctx: registry.resolve("background_watcher").start()
        )
        registry.register_hook(
            "application_closing",
            lambda ctx: registry.resolve("background_watcher").stop()
        )

def create_module():
    return ImportsModule()
