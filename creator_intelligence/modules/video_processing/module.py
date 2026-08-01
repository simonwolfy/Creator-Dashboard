from creator_intelligence.core.contracts import ModuleMetadata,ServiceBinding,NavigationItem
from creator_intelligence.services.video_processing import VideoProcessingService
def _page(registry):
    from creator_intelligence.ui.pages.video_processing import VideoProcessingPage
    return VideoProcessingPage(registry.resolve('video_processing'))
class VideoProcessingModule:
    metadata=ModuleMetadata('video_processing','Video Processing Engine','1.0.0','media','Local FFmpeg VOD processing.',('storage','creator_planner'))
    def register(self,registry):
        registry.register_service(ServiceBinding('video_processing',lambda ctx:VideoProcessingService(ctx.db,registry.resolve('creator_planner'),registry.resolve('notifications')),module_id='video_processing'))
        registry.register_navigation(NavigationItem('Video Processing',lambda:_page(registry),order=13,module_id='video_processing'))
def create_module():return VideoProcessingModule()
