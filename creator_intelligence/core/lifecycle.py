from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Any
import logging


class LifecycleState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class LifecycleStepResult:
    name: str
    ok: bool
    started_at: str
    completed_at: str
    detail: str = ""


@dataclass
class LifecycleReport:
    state: LifecycleState
    steps: list[LifecycleStepResult] = field(default_factory=list)

    @property
    def failures(self) -> list[LifecycleStepResult]:
        return [step for step in self.steps if not step.ok]


class ApplicationLifecycle:
    """Runs deterministic startup and shutdown pipelines.

    Steps are executed in registration order during startup and in reverse
    order during shutdown. A failed required startup step stops the pipeline.
    """

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("creator_intelligence.lifecycle")
        self.state = LifecycleState.CREATED
        self._startup_steps: list[tuple[str, Callable[[], Any], bool]] = []
        self._shutdown_steps: list[tuple[str, Callable[[], Any]]] = []
        self.report = LifecycleReport(self.state)

    def add_startup_step(
        self,
        name: str,
        callback: Callable[[], Any],
        *,
        required: bool = True,
    ) -> None:
        self._startup_steps.append((name, callback, required))

    def add_shutdown_step(self, name: str, callback: Callable[[], Any]) -> None:
        self._shutdown_steps.append((name, callback))

    def start(self) -> LifecycleReport:
        if self.state not in {LifecycleState.CREATED, LifecycleState.STOPPED}:
            raise RuntimeError(f"Cannot start application from state {self.state.value}.")

        self.state = LifecycleState.STARTING
        self.report = LifecycleReport(self.state)
        for name, callback, required in self._startup_steps:
            result = self._run_step(name, callback)
            self.report.steps.append(result)
            if not result.ok and required:
                self.state = LifecycleState.FAILED
                self.report.state = self.state
                raise RuntimeError(f"Required startup step failed: {name}: {result.detail}")

        self.state = LifecycleState.READY
        self.report.state = self.state
        return self.report

    def stop(self) -> LifecycleReport:
        if self.state == LifecycleState.STOPPED:
            return self.report

        self.state = LifecycleState.STOPPING
        shutdown_results: list[LifecycleStepResult] = []
        for name, callback in reversed(self._shutdown_steps):
            shutdown_results.append(self._run_step(name, callback))

        self.report.steps.extend(shutdown_results)
        self.state = LifecycleState.STOPPED
        self.report.state = self.state
        return self.report

    def _run_step(self, name: str, callback: Callable[[], Any]) -> LifecycleStepResult:
        started = datetime.now().isoformat()
        self.logger.info("Lifecycle step started: %s", name)
        try:
            value = callback()
            detail = "" if value is None else str(value)
            ok = True
            self.logger.info("Lifecycle step completed: %s", name)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            ok = False
            self.logger.exception("Lifecycle step failed: %s", name)
        return LifecycleStepResult(
            name=name,
            ok=ok,
            started_at=started,
            completed_at=datetime.now().isoformat(),
            detail=detail,
        )
