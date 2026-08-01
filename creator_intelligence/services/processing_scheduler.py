from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import os
import subprocess
import threading
import time
from typing import Any, Callable


GPU_JOB_TYPES = {"Generate proxy"}
CPU_JOB_TYPES = {"Probe metadata", "Extract audio", "Generate thumbnails"}


@dataclass(frozen=True)
class HardwareProfile:
    logical_cpus: int
    gpu_name: str | None
    nvenc_available: bool
    recommended_workers: int
    recommended_gpu_workers: int


class ProcessingSchedulerService:
    """Runs queued media jobs concurrently while keeping GPU encodes bounded."""

    def __init__(self, processing_service):
        self.processing = processing_service
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._futures: dict[int, Future] = {}
        self._listeners: list[Callable[[], None]] = []
        self._profile = self.detect_hardware()
        self.max_workers = self._profile.recommended_workers
        self.max_gpu_workers = self._profile.recommended_gpu_workers
        self.poll_seconds = 0.5
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="creator-media",
        )

    def detect_hardware(self) -> HardwareProfile:
        logical = max(1, int(os.cpu_count() or 1))
        gpu_name = None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                gpu_name = next(
                    (line.strip() for line in result.stdout.splitlines() if line.strip()),
                    None,
                )
        except (OSError, subprocess.SubprocessError):
            pass

        nvenc = False
        ffmpeg = self.processing.ffmpeg_path
        if ffmpeg:
            try:
                result = subprocess.run(
                    [ffmpeg, "-hide_banner", "-encoders"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                encoders = f"{result.stdout}\n{result.stderr}".lower()
                nvenc = "h264_nvenc" in encoders
            except (OSError, subprocess.SubprocessError):
                pass

        # Keep the desktop responsive: metadata/audio/thumbnails can overlap,
        # while proxy encodes remain limited to one GPU worker by default.
        workers = 4 if logical >= 16 else 3 if logical >= 8 else 2
        gpu_workers = 1 if nvenc else 0
        return HardwareProfile(logical, gpu_name, nvenc, workers, gpu_workers)

    @property
    def hardware_profile(self) -> HardwareProfile:
        return self._profile

    @property
    def running(self) -> bool:
        return bool(self._scheduler_thread and self._scheduler_thread.is_alive())

    def configure(self, max_workers: int, max_gpu_workers: int) -> None:
        if self.running:
            raise RuntimeError("Stop the scheduler before changing worker limits.")
        max_workers = max(1, min(int(max_workers), 16))
        max_gpu_workers = max(0, min(int(max_gpu_workers), max_workers))
        self.max_workers = max_workers
        self.max_gpu_workers = max_gpu_workers
        self._executor.shutdown(wait=False, cancel_futures=False)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="creator-media",
        )

    def add_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._scheduler_thread = threading.Thread(
            target=self._loop,
            name="creator-processing-scheduler",
            daemon=True,
        )
        self._scheduler_thread.start()

    def stop(self, cancel_running: bool = False) -> None:
        self._stop.set()
        if cancel_running:
            for job_id in list(self._futures):
                self.processing.cancel_job(job_id)
        thread = self._scheduler_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3)
        self._scheduler_thread = None
        self._notify()

    def run_once(self) -> list[int]:
        """Dispatch as many eligible queued jobs as available worker slots allow."""
        self._reap()
        capacity = max(0, self.max_workers - len(self._futures))
        if capacity == 0:
            return []

        frame = self.processing.jobs("Queued")
        if frame.empty:
            return []

        running_gpu = sum(
            1
            for job_id in self._futures
            if self.processing.job(job_id).get("job_type") in GPU_JOB_TYPES
        )
        selected: list[int] = []
        active_assets = {
            int(self.processing.job(job_id)["media_asset_id"])
            for job_id in self._futures
        }

        for row in frame.to_dict("records"):
            if len(selected) >= capacity:
                break
            job_id = int(row["id"])
            asset_id = int(row["media_asset_id"])
            job_type = str(row["job_type"])

            # Avoid reading the same source with multiple FFmpeg jobs at once.
            if asset_id in active_assets:
                continue
            if job_type in GPU_JOB_TYPES:
                if self.max_gpu_workers <= 0 or running_gpu >= self.max_gpu_workers:
                    continue
                running_gpu += 1

            future = self._executor.submit(self._run_job, job_id)
            self._futures[job_id] = future
            active_assets.add(asset_id)
            selected.append(job_id)

        if selected:
            self._notify()
        return selected

    def snapshot(self) -> dict[str, Any]:
        self._reap()
        jobs = self.processing.jobs()
        counts = {
            status: int((jobs["status"] == status).sum()) if not jobs.empty else 0
            for status in ("Queued", "Running", "Completed", "Failed", "Cancelled")
        }
        return {
            "scheduler_running": self.running,
            "workers": self.max_workers,
            "gpu_workers": self.max_gpu_workers,
            "active_workers": len(self._futures),
            "counts": counts,
            "hardware": self._profile,
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.poll_seconds)
        self._reap()

    def _run_job(self, job_id: int) -> None:
        try:
            self.processing.run_job(job_id)
        except Exception:
            # VideoProcessingService records the durable failure details.
            pass
        finally:
            self._notify()

    def _reap(self) -> None:
        with self._lock:
            finished = [job_id for job_id, future in self._futures.items() if future.done()]
            for job_id in finished:
                self._futures.pop(job_id, None)

    def _notify(self) -> None:
        for callback in tuple(self._listeners):
            try:
                callback()
            except Exception:
                pass
