from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from creator_intelligence.core.credential_vault import MemoryCredentialBackend
from creator_intelligence.services.clip_visual_intelligence import ClipVisualIntelligenceService


class DB:
    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(str(path))
        self.credential_backend = MemoryCredentialBackend()

    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, tuple(params))
        self.connection.commit()
        return cursor.lastrowid

    def frame(self, sql, params=()):
        return pd.read_sql_query(sql, self.connection, params=tuple(params))


class Transcripts:
    def __init__(self, source: Path):
        self.source = source
        self.video_processing = SimpleNamespace(ffmpeg_path="ffmpeg")
        self.saved = []

    def transcript(self, transcript_id):
        return {"id": transcript_id, "source_path": str(self.source)}

    def save_clip_visual_context(self, clip_id, **values):
        self.saved.append((clip_id, values))


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.payload


def build(tmp_path):
    db = DB(tmp_path / "visual.db")
    db.execute("""CREATE TABLE transcript_clip_candidates(
        id INTEGER PRIMARY KEY,transcript_id INTEGER,start_seconds REAL,end_seconds REAL)""")
    db.execute("""CREATE TABLE publishing_packages(
        id TEXT PRIMARY KEY,clip_candidate_id INTEGER)""")
    db.execute("INSERT INTO transcript_clip_candidates VALUES(5,1,10,20)")
    db.execute("INSERT INTO publishing_packages VALUES('package-1',5)")
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    transcripts = Transcripts(source)
    requests = []

    def runner(command, **_kwargs):
        Path(command[-1]).write_bytes(b"jpeg")
        return SimpleNamespace(returncode=0, stderr="")

    def opener(request, timeout):
        requests.append((request, timeout, json.loads(request.data)))
        result = {"visual_summary": "The player picks up a purple octopus plushie.",
                  "on_screen_text": "Press E to pick up plushie", "detected_game": "",
                  "confidence": .94}
        return Response({"output_text": json.dumps(result)})

    service = ClipVisualIntelligenceService(db, transcripts, opener=opener, runner=runner)
    return db, transcripts, service, requests


def test_automatic_visual_analysis_extracts_three_frames_and_saves_evidence(tmp_path):
    db, transcripts, service, requests = build(tmp_path)
    service.save_configuration(api_key="secret-key", model="gpt-5.4-mini")

    result = service.analyze_package("package-1")

    assert result["frame_count"] == 3
    assert result["confidence"] == .94
    assert transcripts.saved[0][0] == 5
    assert "octopus plushie" in transcripts.saved[0][1]["visual_summary"]
    request, timeout, payload = requests[0]
    assert request.headers["Authorization"] == "Bearer secret-key"
    assert timeout == 90
    assert payload["store"] is False
    assert len(payload["input"][0]["content"]) == 4
    assert payload["text"]["format"]["type"] == "json_schema"
    run = db.frame("SELECT * FROM clip_visual_analysis_runs").iloc[0]
    assert run["status"] == "Completed"
    assert int(run["frame_count"]) == 3


def test_visual_analysis_requires_secure_api_key(tmp_path):
    _db, _transcripts, service, _requests = build(tmp_path)

    with pytest.raises(ValueError, match="API key"):
        service.analyze_package("package-1")
