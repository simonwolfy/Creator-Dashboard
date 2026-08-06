from pathlib import Path

from creator_intelligence.core.application import CreatorIntelligenceApplication
from creator_intelligence.core.versioning import APPLICATION_VERSION, WORKSPACE_SCHEMA_VERSION
from creator_intelligence.core.workspace import WorkspaceManager
from creator_intelligence.services.packaging import (
    PackagingExperimentService,
    PackagingReviewService,
)


def test_versions_have_one_canonical_source():
    assert CreatorIntelligenceApplication.VERSION == APPLICATION_VERSION
    assert WorkspaceManager.METADATA_VERSION == WORKSPACE_SCHEMA_VERSION


def test_packaging_facade_exposes_supported_services():
    assert PackagingReviewService.__name__ == "PackagingReviewService"
    assert PackagingExperimentService.__name__ == "PackagingExperimentService"


def test_architecture_document_defines_feature_ownership():
    text = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    for heading in ("## Transcript", "## Packaging", "## Creator DNA", "## Production"):
        assert heading in text
