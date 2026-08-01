from creator_intelligence.core.contracts import ModuleMetadata,ServiceBinding,NavigationItem
from creator_intelligence.services.opportunity_workload import OpportunityWorkloadService
def _page(registry):
    from creator_intelligence.ui.pages.opportunity_workload import OpportunityWorkloadPage
    return OpportunityWorkloadPage(registry.resolve('opportunity_workload'))
class OpportunityWorkloadModule:
    metadata=ModuleMetadata(module_id='opportunity_workload',name='Opportunity and Workload Intelligence',version='1.0.0',category='media',description='VOD opportunity scores, editor capacity forecasts, and assignment priorities.',dependencies=('storage','content_recommendations','production'))
    def register(self,registry):
        registry.register_service(ServiceBinding('opportunity_workload',lambda ctx:OpportunityWorkloadService(ctx.db,registry.resolve('content_recommendations'),registry.resolve('production'),registry.resolve('creator_planner'),registry.resolve('notifications')),module_id=self.metadata.module_id))
        registry.register_navigation(NavigationItem('Opportunity & Workload',lambda:_page(registry),order=18,module_id=self.metadata.module_id))
def create_module():return OpportunityWorkloadModule()
