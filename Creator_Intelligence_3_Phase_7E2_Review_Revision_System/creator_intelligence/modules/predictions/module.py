from creator_intelligence.core.contracts import ModuleMetadata, ServiceBinding, NavigationItem
from creator_intelligence.services.predictions import PredictionService
from creator_intelligence.services.recommendations import RecommendationService

def _prediction_page(registry):
    from creator_intelligence.ui.pages.predictions import PredictionsPage
    return PredictionsPage(
        registry.resolve("predictions"),
        registry.resolve("recommendations")
    )

class PredictionsModule:
    metadata = ModuleMetadata(
        module_id="predictions",
        name="Predictions and Recommendations",
        version="1.0.0",
        category="ai",
        description="Prediction models, backtesting, and ranked recommendations.",
        dependencies=("storage","analytics"),
    )

    def register(self, registry):
        registry.register_service(ServiceBinding(
            "predictions",
            lambda ctx: PredictionService(ctx.db, registry.resolve("analytics")),
            module_id=self.metadata.module_id,
        ))
        registry.register_service(ServiceBinding(
            "recommendations",
            lambda ctx: RecommendationService(ctx.db, registry.resolve("predictions")),
            module_id=self.metadata.module_id,
        ))
        registry.register_navigation(NavigationItem(
            "Predictions", lambda: _prediction_page(registry), order=50,
            module_id=self.metadata.module_id,
        ))

def create_module():
    return PredictionsModule()
