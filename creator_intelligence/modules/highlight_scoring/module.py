from creator_intelligence.core.contracts import ModuleMetadata,ServiceBinding,NavigationItem
from creator_intelligence.services.highlight_scoring import HighlightScoringService
def _page(registry):
    from creator_intelligence.ui.pages.highlight_scoring import HighlightScoringPage
    return HighlightScoringPage(registry.resolve('highlight_scoring'))
class HighlightScoringModule:
    metadata=ModuleMetadata(module_id='highlight_scoring',name='Highlight Scoring Engine',version='1.0.0',category='media',description='Multi-signal highlight ranking, categories, clip boundaries, and production handoff.',dependencies=('storage','scene_intelligence','transcripts','production','creator_planner'))
    def register(self,registry):
        registry.register_service(ServiceBinding('highlight_scoring',lambda ctx:HighlightScoringService(ctx.db,registry.resolve('scene_intelligence'),registry.resolve('transcripts'),registry.resolve('live_stream'),registry.resolve('production'),registry.resolve('creator_planner'),registry.resolve('notifications')),module_id=self.metadata.module_id))
        registry.register_navigation(NavigationItem('Highlight Scoring',lambda:_page(registry),order=16,module_id=self.metadata.module_id))
def create_module():return HighlightScoringModule()
