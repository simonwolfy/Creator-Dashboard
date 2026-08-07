from creator_intelligence.core.contracts import ModuleMetadata, ServiceBinding, NavigationItem
from creator_intelligence.services.analytics import AnalyticsService
from creator_intelligence.services.twitch_intelligence import TwitchIntelligenceService
from creator_intelligence.services.youtube_intelligence import YouTubeIntelligenceService
from creator_intelligence.services.social_platforms import SocialPlatformService

def _home_page(registry):
    from creator_intelligence.ui.pages.home import HomePage
    return HomePage(registry.resolve("analytics"), registry.resolve("recommendations"))

def _twitch_page(registry):
    from creator_intelligence.ui.pages.twitch import TwitchPage
    return TwitchPage(registry.resolve("twitch_intelligence"), registry.context.db)

def _youtube_page(registry):
    from creator_intelligence.ui.pages.youtube import YouTubePage
    return YouTubePage(registry.resolve("youtube_intelligence"))

def _social_page(registry, platform):
    from creator_intelligence.ui.pages.social_platform import SocialPlatformPage
    return SocialPlatformPage(registry.resolve("social_platforms"), platform)

class AnalyticsModule:
    metadata = ModuleMetadata(
        module_id="analytics",
        name="Analytics",
        version="1.0.0",
        category="analytics",
        description="Twitch, YouTube, and executive analytics.",
        dependencies=("storage",),
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            "analytics", lambda ctx: AnalyticsService(ctx.db),
            module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "twitch_intelligence", lambda ctx: TwitchIntelligenceService(ctx.db),
            module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "youtube_intelligence", lambda ctx: YouTubeIntelligenceService(ctx.db),
            module_id=self.metadata.module_id
        ))
        registry.register_service(ServiceBinding(
            "social_platforms", lambda ctx: SocialPlatformService(ctx.db),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Home", lambda: _home_page(registry), order=10,
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "Twitch", lambda: _twitch_page(registry), order=20,
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "YouTube", lambda: _youtube_page(registry), order=30,
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "Instagram", lambda: _social_page(registry, "instagram"), order=35,
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "TikTok", lambda: _social_page(registry, "tiktok"), order=40,
            module_id=self.metadata.module_id,
        ))

def create_module():
    return AnalyticsModule()
