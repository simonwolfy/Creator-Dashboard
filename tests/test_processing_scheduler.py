from __future__ import annotations

import threading
import time

import pandas as pd

from creator_intelligence.services.processing_scheduler import ProcessingSchedulerService


class FakeProcessing:
    ffmpeg_path = None

    def __init__(self):
        self._jobs = {
            1: {"id": 1, "media_asset_id": 1, "job_type": "Generate proxy", "status": "Queued", "priority": 40},
            2: {"id": 2, "media_asset_id": 2, "job_type": "Generate thumbnails", "status": "Queued", "priority": 50},
            3: {"id": 3, "media_asset_id": 1, "job_type": "Extract audio", "status": "Queued", "priority": 60},
        }
        self.started = []
        self.release = threading.Event()

    def jobs(self, status=None):
        rows = list(self._jobs.values())
        if status and status != "All":
            rows = [row for row in rows if row["status"] == status]
        return pd.DataFrame(rows)

    def job(self, job_id):
        return dict(self._jobs[int(job_id)])

    def run_job(self, job_id):
        job_id = int(job_id)
        self._jobs[job_id]["status"] = "Running"
        self.started.append(job_id)
        self.release.wait(1)
        self._jobs[job_id]["status"] = "Completed"

    def cancel_job(self, job_id):
        self._jobs[int(job_id)]["status"] = "Cancelled"


def test_scheduler_dispatches_multiple_assets_but_not_same_asset():
    processing = FakeProcessing()
    scheduler = ProcessingSchedulerService(processing)
    scheduler._profile = scheduler._profile.__class__(24, "RTX 3080", True, 4, 1)
    scheduler.configure(4, 1)

    dispatched = scheduler.run_once()
    assert dispatched == [1, 2]
    assert 3 not in dispatched

    processing.release.set()
    time.sleep(0.05)
    scheduler.stop()


def test_scheduler_respects_gpu_worker_limit():
    processing = FakeProcessing()
    processing._jobs[2]["job_type"] = "Generate proxy"
    scheduler = ProcessingSchedulerService(processing)
    scheduler.configure(4, 1)

    dispatched = scheduler.run_once()
    assert len(dispatched) == 1

    processing.release.set()
    time.sleep(0.05)
    scheduler.stop()


def test_scheduler_snapshot_reports_queue_state():
    processing = FakeProcessing()
    scheduler = ProcessingSchedulerService(processing)
    snapshot = scheduler.snapshot()

    assert snapshot["counts"]["Queued"] == 3
    assert snapshot["active_workers"] == 0
    assert snapshot["scheduler_running"] is False
    scheduler.stop()
