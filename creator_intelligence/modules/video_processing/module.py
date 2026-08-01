from creator_intelligence.core.contracts import ModuleMetadata, NavigationItem, ServiceBinding
from creator_intelligence.services.ffmpeg_manager import FFmpegManagerService
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


def _tool_paths(registry):
    status = registry.resolve("ffmpeg_manager").status()
    return status.ffmpeg_path, status.ffprobe_path


class VideoProcessingModule:
    metadata = ModuleMetadata(
        "video_processing",
        "Video Processing Engine",
        "1.2.0",
        "media",
        "FFmpeg management, local media processing, and canonical managed-asset metadata extraction.",
        ("storage", "creator_planner"),
    )

    def register(self, registry):
        registry.register_service(
            ServiceBinding(
                "ffmpeg_manager",
                lambda ctx: FFmpegManagerService(ctx.db),
                module_id="video_processing",
            )
        )
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
                lambda ctx: VideoMetadataService(
                    ctx.db,
                    ffprobe_path=_tool_paths(registry)[1],
                ),
                module_id="video_processing",
            )
        )
        registry.register_navigation(
            NavigationItem(
                "FFmpeg Manager",
                lambda: _ffmpeg_page(registry),
                order=12,
                module_id="video_processing",
            )
        )
        registry.register_navigation(
            NavigationItem(
                "Video Processing",
                lambda: _processing_page(registry),
                order=13,
                module_id="video_processing",
            )
        )
        registry.register_navigation(
            NavigationItem(
                "Video Metadata",
                lambda: _metadata_page(registry),
                order=14,
                module_id="video_processing",
            )
        )


def create_module():
    return VideoProcessingModule()
