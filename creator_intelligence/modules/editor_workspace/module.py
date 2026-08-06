from creator_intelligence.core.contracts import (
    ModuleMetadata,ServiceBinding,NavigationItem
)
from creator_intelligence.services.editor_workspace import EditorWorkspaceService


def _page(registry):
    from creator_intelligence.ui.pages.editor_workspace_integrated import (
        IntegratedEditorWorkspacePage,
    )
    return IntegratedEditorWorkspacePage(registry.resolve("editor_workspace"))


class EditorWorkspaceModule:
    metadata=ModuleMetadata(
        module_id="editor_workspace",
        name="Editor Workspace",
        version="1.1.0",
        category="production",
        description=(
            "Editor queue, AI briefs, creator-selected transcript clips, "
            "timestamps, notes, checklist, and project progress."
        ),
        dependencies=(
            "storage","production","highlight_scoring",
            "content_recommendations","transcripts","scene_intelligence"
        )
    )

    def register(self,registry):
        registry.register_service(ServiceBinding(
            "editor_workspace",
            lambda ctx:EditorWorkspaceService(
                ctx.db,
                registry.resolve("production"),
                registry.resolve("highlight_scoring"),
                registry.resolve("content_recommendations"),
                registry.resolve("transcripts"),
                registry.resolve("scene_intelligence"),
                registry.resolve("notifications")
            ),
            module_id=self.metadata.module_id
        ))
        registry.register_navigation(NavigationItem(
            "Editor Workspace",lambda:_page(registry),
            order=20,module_id=self.metadata.module_id
        ))


def create_module():
    return EditorWorkspaceModule()
