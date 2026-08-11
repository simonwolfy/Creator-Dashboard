from __future__ import annotations

import json
from pathlib import Path

import pytest

from creator_intelligence.core.config import ConfigService
from creator_intelligence.core.onboarding import (
    InstallationProfile,OnboardingService,default_profile_path,
)
from creator_intelligence.core.workspace import WorkspaceManager
from creator_intelligence.data.database import Database


def service(tmp_path,which=lambda _name:None):
    python=tmp_path/"python.exe";python.write_text("fixture",encoding="utf-8")
    return OnboardingService(tmp_path/"install"/"installation.json",which=which,python_executable=str(python))


def test_fresh_install_creates_isolated_empty_workspace_and_profile(tmp_path):
    onboarding=service(tmp_path);workspace=tmp_path/"Creator Workspace"
    assert onboarding.needs_onboarding() is True
    profile=onboarding.complete(
        workspace_root=workspace,workspace_name="Test Creator",channel_name="Test Channel",
        privacy_acknowledged=True,selected_platforms=["youtube","twitch"],connections_skipped=False)
    assert profile.onboarding_completed is True
    assert profile.workspace_root==str(workspace.resolve())
    assert profile.selected_platforms==["twitch","youtube"]
    assert workspace.joinpath("data","creator_intelligence.db").exists()
    assert Database(workspace/"data"/"creator_intelligence.db").integrity_check()=="ok"
    assert list((workspace/"exports").iterdir())==[]
    assert ConfigService(workspace/"config"/"settings.json").load().channel_name=="Test Channel"
    saved=json.loads(onboarding.profile_path.read_text(encoding="utf-8"))
    assert "token" not in json.dumps(saved).lower()
    assert onboarding.needs_onboarding() is False


def test_privacy_acknowledgement_is_required(tmp_path):
    onboarding=service(tmp_path)
    with pytest.raises(ValueError,match="privacy notice"):
        onboarding.complete(workspace_root=tmp_path/"workspace",workspace_name="Test",
                            channel_name="Channel",privacy_acknowledged=False)
    assert onboarding.profile_path.exists() is False


def test_dependency_diagnostics_separate_required_and_optional_tools(tmp_path):
    onboarding=service(tmp_path,which=lambda name:"C:/tools/ffmpeg.exe" if name=="ffmpeg" else None)
    checks={check.name:check for check in onboarding.diagnostics(tmp_path/"workspace")}
    assert checks["Python"].required and checks["Python"].ready
    assert checks["Workspace folder"].required and checks["Workspace folder"].ready
    assert checks["FFmpeg and FFprobe"].required is False
    assert checks["FFmpeg and FFprobe"].ready is False
    assert checks["Whisper base model"].required is False


def test_existing_workspace_migration_preserves_identity_and_database(tmp_path):
    workspace=WorkspaceManager(tmp_path/"existing","Legacy Workspace");paths=workspace.initialize()
    config_service=ConfigService(paths.config/"settings.json");config=config_service.load();config.channel_name="Legacy Channel";config_service.save(config)
    database=Database(paths.database);database.migrate();before=database.migration_history()
    onboarding=service(tmp_path)
    profile=onboarding.migrate_existing(paths.root)
    assert profile.workspace_name=="Legacy Workspace"
    assert profile.channel_name=="Legacy Channel"
    assert len(Database(paths.database).migration_history())==len(before)
    assert onboarding.needs_onboarding() is False


def test_reset_reopens_setup_without_deleting_workspace(tmp_path):
    onboarding=service(tmp_path);workspace=tmp_path/"workspace"
    onboarding.complete(workspace_root=workspace,workspace_name="Test",channel_name="Channel",privacy_acknowledged=True)
    database=workspace/"data"/"creator_intelligence.db";assert database.exists()
    onboarding.reset()
    assert onboarding.needs_onboarding() is True
    assert database.exists()


def test_corrupt_or_incomplete_profile_returns_to_onboarding(tmp_path):
    onboarding=service(tmp_path);onboarding.profile_path.parent.mkdir(parents=True)
    onboarding.profile_path.write_text("not-json",encoding="utf-8")
    assert onboarding.profile()==InstallationProfile()
    assert onboarding.needs_onboarding() is True


def test_default_profile_path_is_outside_repository_for_supplied_home(tmp_path):
    result=default_profile_path(environ={"XDG_CONFIG_HOME":str(tmp_path/"config")},home=tmp_path)
    assert result==tmp_path/"config"/"Creator Intelligence"/"installation.json"
