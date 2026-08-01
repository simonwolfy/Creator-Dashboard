from creator_intelligence.core.contracts import ModuleMetadata,ServiceBinding,NavigationItem
from creator_intelligence.services.content_recommendations import ContentRecommendationService
def _page(registry):
    from creator_intelligence.ui.pages.content_recommendations import ContentRecommendationsPage
    return ContentRecommendationsPage(registry.resolve('content_recommendations'))
class ContentRecommendationsModule:
    metadata=ModuleMetadata(module_id='content_recommendations',name='Content Recommendation Engine',version='1.0.0',category='media',description='Short selection, episode outlines, workload estimates, and editor packets.',dependencies=('storage','highlight_scoring','production'))
    def register(self,registry):
        registry.register_service(ServiceBinding('content_recommendations',lambda ctx:ContentRecommendationService(ctx.db,registry.resolve('highlight_scoring'),registry.resolve('production'),registry.resolve('creator_planner'),registry.resolve('notifications')),module_id=self.metadata.module_id))
        registry.register_navigation(NavigationItem('Content Recommendations',lambda:_page(registry),order=17,module_id=self.metadata.module_id))
def create_module(): return ContentRecommendationsModule()
