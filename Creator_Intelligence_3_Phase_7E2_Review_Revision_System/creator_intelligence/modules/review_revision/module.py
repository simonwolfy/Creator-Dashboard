from creator_intelligence.core.contracts import ModuleMetadata,ServiceBinding,NavigationItem
from creator_intelligence.services.review_revision import ReviewRevisionService

def _page(registry):
    from creator_intelligence.ui.pages.review_revision import ReviewRevisionPage
    return ReviewRevisionPage(registry.resolve('review_revision'))
class ReviewRevisionModule:
    metadata=ModuleMetadata(module_id='review_revision',name='Review & Revision',version='1.0.0',category='production',description='Version control, timestamp comments, revision requests, approval gates, and review analytics.',dependencies=('storage','production','editor_workspace'))
    def register(self,registry):
        registry.register_service(ServiceBinding('review_revision',lambda ctx:ReviewRevisionService(ctx.db,registry.resolve('production'),registry.resolve('editor_workspace'),registry.resolve('notifications')),module_id=self.metadata.module_id))
        registry.register_navigation(NavigationItem('Review & Revision',lambda:_page(registry),order=21,module_id=self.metadata.module_id))
def create_module(): return ReviewRevisionModule()
