from creator_intelligence.core.contracts import ModuleMetadata, NavigationItem, ServiceBinding
from creator_intelligence.services.ffmpeg_manager import FFmpegManagerService
from creator_intelligence.services.proxy_engine import ProxyEngineService
from creator_intelligence.services.thumbnail_engine import ThumbnailEngineService
from creator_intelligence.services.video_metadata import VideoMetadataService
from creator_intelligence.services.video_processing import VideoProcessingService


def _processing_page(registry):
    from creator_intelligence.ui.pages.video_processing import VideoProcessingPage
    return VideoProcessingPage(registry.resolve("video_processing"))


def _metadata_page(registry):
    from creator_intelligence.ui.pages.video_metadata import VideoMetadataPage
    return VideoMetadataPage(registry.resolve("video_metadata"))


def _ffmpeg_page(registry):
    from creator_intelligence.ui.pages.ffmpeg_manager import FFmpegManagerPage
    return FFmpegManagerPage(registry.resolve("ffmpeg_manager"))


def _proxy_page(registry):
    from creator_intelligence.ui.pages.proxy_engine import ProxyEnginePage
    return ProxyEnginePage(registry.resolve("proxy_engine"))


def _thumbnail_page(registry):
    from creator_intelligence.ui.pages.thumbnail_engine import ThumbnailEnginePage
    return ThumbnailEnginePage(registry.resolve("thumbnail_engine"))


def _tool_paths(registry):
    status = registry.resolve("ffmpeg_manager").status()
    return status.ffmpeg_path, status.ffprobe_path


class VideoProcessingModule:
    metadata = ModuleMetadata(
        "video_processing",
        "Video Processing Engine",
        "1.4.0",
        "media",
        "FFmpeg management, metadata extraction, disposable proxies, and thumbnail generation.",
        ("storage", "creator_planner"),
    )

    def register(self, registry):
        registry.register_service(ServiceBinding("ffmpeg_manager", lambda ctx: FFmpegManagerService(ctx.db), module_id="video_processing"))
        registry.register_service(
            ServiceBinding(
                "video_processing",
                lambda ctx: VideoProcessingService(
                    ctx.db,
                    registry.resolve("creator_planner"),
                    registry.resolve("notifications"),
                    ffmpeg_path=_tool_paths(registry)[0],
                    ffprobe_path=_tool_paths(registry)[1],
                ),
                module_id="video_processing",
            )
        )
        registry.register_service(
            ServiceBinding(
                "video_metadata",
                lambda ctx: VideoMetadataService(ctx.db, ffprobe_path=_tool_paths(registry)[1]),
                module_id="video_processing",
            )
        )
        registry.register_service(ServiceBinding("proxy_engine", lambda ctx: ProxyEngineService(registry.resolve("video_processing")), module_id="video_processing"))
        registry.register_service(ServiceBinding("thumbnail_engine", lambda ctx: ThumbnailEngineService(registry.resolve("video_processing")), module_id="video_processing"))

        for label, factory, order, key in (
            ("FFmpeg Manager", lambda: _ffmpeg_page(registry), 12, "video_processing:ffmpeg-manager"),
            ("Video Processing", lambda: _processing_page(registry), 13, "video_processing:processing"),
            ("Video Metadata", lambda: _metadata_page(registry), 14, "video_processing:metadata"),
            ("Proxy Engine", lambda: _proxy_page(registry), 15, "video_processing:proxy-engine"),
            ("Thumbnail Engine", lambda: _thumbnail_page(registry), 16, "video_processing:thumbnail-engine"),
        ):
            registry.register_navigation(NavigationItem(label, factory, order=order, module_id=key))


def create_module():
    return VideoProcessingModule()
