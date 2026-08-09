from __future__ import annotations

from types import SimpleNamespace

from creator_intelligence.services.local_whisper_transcripts import (
    LocalWhisperTranscriptService,
)


class FakeDB:
    path = "creator.db"

    def execute(self, *args, **kwargs):
        return 1


def service_without_init():
    service = LocalWhisperTranscriptService.__new__(LocalWhisperTranscriptService)
    service.db = FakeDB()
    service.video_processing = None
    service.notifications = None
    return service


def test_embedded_engine_is_preferred(monkeypatch):
    service = service_without_init()
    monkeypatch.setattr(
        "creator_intelligence.services.local_whisper_transcripts.importlib.import_module",
        lambda name: SimpleNamespace(WhisperModel=object)
        if name == "faster_whisper"
        else None,
    )

    status = service.engine_status()

    assert status.available is True
    assert status.engine == "embedded-faster-whisper"
    assert "GPU acceleration" in status.message


def test_embedded_engine_falls_back_when_runtime_cannot_load(monkeypatch):
    service = service_without_init()

    def unavailable(_name):
        raise OSError("missing packaged runtime")

    monkeypatch.setattr(
        "creator_intelligence.services.local_whisper_transcripts.importlib.import_module",
        unavailable,
    )

    status = service.engine_status()

    assert status.engine != "embedded-faster-whisper"


def test_job_settings_accept_json_and_invalid_values():
    service = service_without_init()

    assert service._job_settings({"settings_json": '{"device":"cuda","beam_size":3}'}) == {
        "device": "cuda",
        "beam_size": 3,
    }
    assert service._job_settings({"settings_json": "not-json"}) == {}
    assert service._job_settings({"settings_json": None}) == {}


def test_auto_model_falls_back_to_cpu(monkeypatch):
    service = service_without_init()
    calls = []

    class FakeModel:
        def __init__(self, model_name, device, compute_type):
            calls.append((model_name, device, compute_type))
            if device == "cuda":
                raise RuntimeError("CUDA unavailable")

    fake_module = SimpleNamespace(WhisperModel=FakeModel)
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", fake_module)

    model = service._load_model("base", "auto", "auto")

    assert isinstance(model, FakeModel)
    assert calls == [
        ("base", "cuda", "float16"),
        ("base", "cpu", "int8"),
    ]
