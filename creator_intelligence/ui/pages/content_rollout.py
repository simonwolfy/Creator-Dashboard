from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTableView, QVBoxLayout, QWidget,
)

from creator_intelligence.ui.pages.twitch import FrameModel


class ContentRolloutPage(QWidget):
    """Folder-to-review operations and rollout quality dashboard."""

    def __init__(self, service):
        super().__init__()
        self.service = service
        root = QVBoxLayout(self)
        title = QLabel("Content Intelligence Rollout")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        actions = QHBoxLayout()
        for label, handler in (
            ("Queue local folder", self.queue_folder), ("Queue mapped Drive videos", self.queue_drive),
            ("Run next", self.run_next),
            ("Retry selected", self.retry), ("Cancel selected", self.cancel),
            ("Mark reviewed", self.mark_reviewed), ("Check release gates", self.release_gates),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch()
        root.addLayout(actions)
        self.jobs = QTableView()
        self.jobs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.jobs.setSelectionMode(QAbstractItemView.SingleSelection)
        root.addWidget(self.jobs, 1)
        self.refresh()

    def selected_job_id(self):
        index = self.jobs.currentIndex()
        if not index.isValid():
            return None
        return int(self.jobs.model().frame.iloc[index.row()]["id"])

    def refresh(self):
        metrics = self.service.dashboard()
        def percent(value):
            return "Not measured" if value is None else f"{float(value):.0%}"
        self.summary.setText(
            f"Jobs: {metrics['jobs']} • Queued: {metrics['queued_jobs']} • "
            f"Needs review: {metrics['needs_review']} • Failed: {metrics['failed_jobs']} • "
            f"Approval rate: {percent(metrics['approval_rate'])} • "
            f"Edit rate: {percent(metrics['edit_rate'])} • "
            f"Average analysis: {metrics['average_processing_seconds'] or 0:.1f}s • "
            f"Average review: {metrics['average_review_seconds'] or 0:.1f}s • "
            f"Outcome snapshots: {metrics['outcome_snapshots']} • "
            f"Provider cost: ${metrics['estimated_provider_cost']:.4f} • "
            f"Conflicts: {metrics['conflicts']}"
        )
        frame = self.service.jobs()
        visible = ["id", "status", "progress_percent", "source_path", "attempt_count",
                   "clip_candidate_id", "error", "updated_at"]
        self.jobs.setModel(FrameModel(frame[[name for name in visible if name in frame.columns]]))

    def queue_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose edited-video folder")
        if not folder:
            return
        result = self.service.queue_folder(folder)
        QMessageBox.information(
            self, "Folder queued",
            f"Queued {len(result['queued'])}; already known {len(result['duplicates'])}; "
            f"unsupported files {len(result['unsupported'])}.",
        )
        self.refresh()

    def run_next(self):
        result = self.service.run_next()
        if result is None:
            QMessageBox.information(self, "Content intelligence", "No queued analysis jobs remain.")
        elif result["status"] == "Failed":
            QMessageBox.warning(self, "Analysis failed", str(result.get("error") or "Unknown error"))
        self.refresh()

    def queue_drive(self):
        try:
            result = self.service.queue_drive_files()
        except Exception as exc:
            QMessageBox.warning(self, "Drive queue unavailable", str(exc))
            return
        QMessageBox.information(
            self, "Drive videos queued",
            f"Queued {len(result['queued'])}; already known {len(result['duplicates'])}; "
            f"unsupported files {len(result['unsupported'])}. Drive videos remain cloud-only "
            "until their analysis job runs.",
        )
        self.refresh()

    def retry(self):
        job_id = self.selected_job_id()
        if job_id is not None:
            try:
                self.service.retry(job_id)
            except Exception as exc:
                QMessageBox.warning(self, "Cannot retry", str(exc))
            self.refresh()

    def cancel(self):
        job_id = self.selected_job_id()
        if job_id is not None:
            self.service.cancel(job_id)
            self.refresh()

    def mark_reviewed(self):
        job_id = self.selected_job_id()
        if job_id is not None:
            try:
                self.service.mark_completed(job_id)
            except Exception as exc:
                QMessageBox.warning(self, "Review incomplete", str(exc))
            self.refresh()

    def release_gates(self):
        frame = self.service.evaluate_release_gates("5.0.0-alpha.3")
        lines = [f"{row['gate_key']}: {row['status']} — {row['detail']}"
                 for row in frame.to_dict("records")]
        QMessageBox.information(self, "5.0.0-alpha.3 release gates", "\n".join(lines))
