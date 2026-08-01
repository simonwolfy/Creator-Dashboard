from pathlib import Path

from creator_intelligence.core.lifecycle import ApplicationLifecycle, LifecycleState
from creator_intelligence.core.workspace import WorkspaceManager


def test_lifecycle_runs_startup_and_reverse_shutdown():
    events = []
    lifecycle = ApplicationLifecycle()
    lifecycle.add_startup_step("first", lambda: events.append("start:first"))
    lifecycle.add_startup_step("second", lambda: events.append("start:second"))
    lifecycle.add_shutdown_step("first", lambda: events.append("stop:first"))
    lifecycle.add_shutdown_step("second", lambda: events.append("stop:second"))

    report = lifecycle.start()
    assert report.state == LifecycleState.READY
    lifecycle.stop()

    assert events == [
        "start:first",
        "start:second",
        "stop:second",
        "stop:first",
    ]
    assert lifecycle.state == LifecycleState.STOPPED


def test_optional_startup_failure_does_not_abort():
    lifecycle = ApplicationLifecycle()
    lifecycle.add_startup_step(
        "optional",
        lambda: (_ for _ in ()).throw(RuntimeError("expected")),
        required=False,
    )
    lifecycle.add_startup_step("required", lambda: "ok")

    report = lifecycle.start()

    assert report.state == LifecycleState.READY
    assert len(report.failures) == 1
    assert report.failures[0].name == "optional"


def test_workspace_manager_creates_isolated_layout(tmp_path: Path):
    manager = WorkspaceManager(tmp_path / "workspace", name="Test Workspace")
    paths = manager.initialize()

    assert paths.database == paths.data / "creator_intelligence.db"
    assert paths.metadata.exists()
    assert paths.config.is_dir()
    assert paths.logs.is_dir()
    assert paths.cache.is_dir()
    assert manager.describe()["name"] == "Test Workspace"
