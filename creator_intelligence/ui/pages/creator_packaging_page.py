from __future__ import annotations

import json
import pandas as pd
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from creator_intelligence.ui.pages.transcript_production import TranscriptProductionPage
from creator_intelligence.ui.pages.twitch import FrameModel


class CreatorPackagingPage(TranscriptProductionPage):
    """Transcript production page with platform-ready creator packaging."""

    def __init__(self, service):
        super().__init__(service)
        layout = self.clip_controls.layout()
        for label, handler in (("Add historical title", self.add_historical_title),
                               ("Import title CSV", self.import_title_csv),
                               ("Sync Twitch titles", lambda: self.sync_titles("twitch")),
                               ("Sync YouTube titles", lambda: self.sync_titles("youtube")),
                               ("View title profile", self.view_title_profile)):
            button = QPushButton(label, self.clip_controls)
            button.clicked.connect(handler)
            layout.insertWidget(max(0, layout.count() - 1), button)

    def add_historical_title(self) -> None:
        title, ok = QInputDialog.getText(self, "Add historical title", "Published clip title:")
        if ok and title.strip():
            kind, chosen = QInputDialog.getItem(
                self, "Example type", "How should this title influence the profile?",
                ["published", "approved", "rejected"], 0, False,
            )
            if not chosen:
                return
            self.service.record_published_title(title, example_type=kind)
            QMessageBox.information(self, "Title DNA", "Historical title saved and profile updated.")

    def import_title_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import historical titles", "", "CSV files (*.csv)")
        if not path:
            return
        try:
            result = self.service.import_published_titles(path)
        except Exception as exc:
            QMessageBox.critical(self, "Title import", str(exc))
            return
        QMessageBox.information(self, "Title import", f"Imported {result['imported']} title(s); skipped {result['skipped']}.")

    def view_title_profile(self) -> None:
        profile = self.service.title_style_profile()
        text = (
            f"Examples: {profile['example_count']} ({profile['positive_count']} positive, {profile['negative_count']} negative)\n"
            f"Average length: {profile['average_words']} words\n"
            f"Question titles: {profile['question_rate']:.0%}\n"
            f"First-person titles: {profile['first_person_rate']:.0%}\n"
            f"Exclamation titles: {profile['exclamation_rate']:.0%}\n\n"
            f"Preferred words: {', '.join(profile['preferred_words']) or 'Not enough data'}\n"
            f"Avoided words: {', '.join(profile['avoided_words']) or 'None learned'}"
        )
        QMessageBox.information(self, "Learned title profile", text)

    def sync_titles(self, platform: str) -> None:
        try:
            result = self.service.sync_title_history(platform)
        except Exception as exc:
            message = str(exc)
            if platform == "youtube" and "required" in message.lower():
                message += " Configure these in YouTube > API setup."
            QMessageBox.critical(self, f"{platform.title()} title sync", message)
            return
        QMessageBox.information(
            self, f"{platform.title()} title sync",
            f"Sync complete. Found {result['seen']} title(s); added {result['changed']}. "
            f"The learned title profile has been refreshed.",
        )

    def view_clip_intelligence(self) -> None:
        clip_ids = self._selected_clip_ids()
        if len(clip_ids) != 1:
            QMessageBox.information(
                self, "Creator packaging", "Select exactly one clip."
            )
            return
        clip_id = int(clip_ids[0])
        row = self.service.clip_packaging(clip_id)
        if not row.get("analyzed_at") or row.get("intelligence_version") != "creator-packaging-v5":
            self.service.analyze_clip_candidate(clip_id)
            row = self.service.clip_packaging(clip_id)

        def load_json(name, default):
            try:
                return json.loads(row.get(name) or json.dumps(default))
            except Exception:
                return default

        titles = load_json("title_alternatives_json", [])
        hashtags = load_json("suggested_hashtags_json", [])
        reasons = load_json("packaging_reasoning_json", [])
        packages = load_json("platform_packages_json", {})
        from creator_intelligence.services.publishing_outcomes import PublishingOutcomeService
        outcome_frame = PublishingOutcomeService(self.service.db).dashboard()
        event = load_json("packaging_context_json", {})
        confidence = event.get("confidence", {})
        trim_start = row.get("suggested_start_seconds") or row["start_seconds"]
        trim_end = row.get("suggested_end_seconds") or row["end_seconds"]

        title_lines = "\n".join(
            f"  {index + 1}. {title}" for index, title in enumerate(titles)
        )
        reason_lines = "\n".join(f"  • {reason}" for reason in reasons)
        package_lines = []
        outcome_lines = []
        for platform, package in packages.items():
            label = platform.replace("_", " ").title()
            evidence = package.get("historical_evidence") or []
            evidence_text = "; ".join(
                f"{item.get('title', 'Untitled')} ({int(item.get('views') or 0):,} views)"
                for item in evidence[:3]
            )
            package_lines.extend([
                f"{label}:",
                f"  Outcome package ID: {package.get('package_id', 'Not recorded')}",
                f"  Experiment ID: {package.get('experiment_id', 'Not created')}",
                f"  Profile confidence: {package.get('profile_confidence', 'Unknown')}",
                f"  Title: {package.get('title', '')}" if package.get("title") else "",
                f"  Caption: {package.get('caption') or package.get('description', '')}",
                f"  Hook: {package.get('hook', '')}",
                f"  Hashtags: {' '.join(package.get('hashtags', []))}",
                f"  Historical evidence: {evidence_text}" if evidence_text else "  Historical evidence: Not enough platform data",
                "",
            ])
            package_id = package.get("package_id")
            matched = outcome_frame[outcome_frame["id"] == package_id] if package_id and not outcome_frame.empty else outcome_frame.iloc[0:0]
            if not matched.empty:
                outcome = matched.iloc[0]
                actual = outcome.get("actual_score")
                outcome_lines.append(
                    f"{label}: {outcome.get('decision_status')} | "
                    f"match {float(outcome.get('match_confidence') or 0):.0%} | "
                    f"checkpoint {int(outcome.get('milestone_hours') or 0)}h | "
                    f"actual score {float(actual):.1f}" if actual == actual else
                    f"{label}: {outcome.get('decision_status')} | waiting for measured results"
                )

        message = (
            f"PACKAGING SCORES\n"
            f"Hook: {float(row.get('hook_score') or 0):.1f}   "
            f"Humor: {float(row.get('humor_score') or 0):.1f}   "
            f"Surprise: {float(row.get('surprise_score') or 0):.1f}\n"
            f"Emotion: {float(row.get('emotion_score') or 0):.1f}   "
            f"Quote: {float(row.get('quote_score') or 0):.1f}   "
            f"Viral: {float(row.get('viral_score') or 0):.1f}\n"
            f"Title score: {float(row.get('title_score') or 0):.1f}   "
            f"Replayability: {float(row.get('replayability_score') or 0):.1f}   "
            f"Shareability: {float(row.get('shareability_score') or 0):.1f}\n"
            f"Retention estimate: {float(row.get('retention_estimate') or 0):.1f}%   "
            f"Predicted performance: {row.get('performance_prediction') or 'Unknown'}\n"
            f"Likely audience: {row.get('likely_audience') or 'Unknown'}\n\n"
            f"SEMANTIC EVENT\n"
            f"Subject: {event.get('subject', 'Unknown')} ({float(confidence.get('subject', 0)):.0%})\n"
            f"Action: {event.get('action', 'Unknown')} ({float(confidence.get('action', 0)):.0%})\n"
            f"Outcome: {event.get('outcome', 'Unknown')} ({float(confidence.get('outcome', 0)):.0%})\n"
            f"Emotion: {event.get('emotion', 'Unknown')}\n"
            f"Overall confidence: {float(confidence.get('event', 0)):.0%}\n"
            f"Title source: {event.get('fallback_mode', 'event').title()}\n"
            f"Context segments: {event.get('context_segment_count', 1)}\n\n"
            f"SUGGESTED TRIM\n{self._clock(trim_start)}–{self._clock(trim_end)}\n\n"
            f"PRIMARY TITLE\n{row.get('suggested_title') or row.get('title') or ''}\n\n"
            f"TITLE ALTERNATIVES\n{title_lines}\n\n"
            f"HOOK LINE\n{row.get('hook_line') or ''}\n\n"
            f"SOCIAL CAPTION ({row.get('caption_style') or 'default'})\n"
            f"{row.get('suggested_caption') or ''}\n\n"
            f"HASHTAGS\n{' '.join(hashtags)}\n\n"
            f"WHY THIS CLIP WORKS\n{reason_lines}\n\n"
            f"PLATFORM PACKAGES\n"
            f"{chr(10).join(line for line in package_lines if line is not None)}\n"
            f"OUTCOME FEEDBACK\n"
            f"{chr(10).join(outcome_lines) or 'Publish and sync these packages to compare predictions with real results.'}"
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Creator packaging intelligence")
        dialog.setMinimumSize(760, 560)
        dialog.resize(900, 700)

        layout = QVBoxLayout(dialog)
        report = QTextEdit(dialog)
        report.setReadOnly(True)
        report.setPlainText(message)
        report.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(report)

        button_row = QHBoxLayout()
        copy_button = QPushButton("Copy all", dialog)
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(message)
        )
        button_row.addWidget(copy_button)
        button_row.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.clicked.connect(dialog.accept)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

        dialog.exec()

    def _refresh_clip_candidates(self, *_args, selected_id: int | None = None) -> None:
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            frame = pd.DataFrame()
        else:
            status = self.clip_filter.currentText() if hasattr(self, "clip_filter") else "All"
            frame = self.service.clip_candidates(int(transcript_id), status)
            if not frame.empty:
                frame = frame.copy()
                packaging_rows = []
                for clip_id in frame["id"].tolist():
                    packaging_rows.append(self.service.clip_packaging(int(clip_id)))
                packaging = pd.DataFrame(packaging_rows).set_index("id")
                for column in (
                    "title_score", "replayability_score", "shareability_score",
                    "retention_estimate", "performance_prediction", "hook_line",
                ):
                    if column in packaging.columns:
                        frame[column] = frame["id"].map(packaging[column])
                frame.insert(
                    0,
                    "time",
                    frame.apply(
                        lambda row: f"{self._clock(row['start_seconds'])}–{self._clock(row['end_seconds'])}",
                        axis=1,
                    ),
                )
                visible = [
                    "id", "time", "title", "viral_score", "title_score",
                    "retention_estimate", "performance_prediction", "hook_line",
                    "suggested_title", "review_status", "sent_to_production",
                    "production_status",
                ]
                frame = frame[[column for column in visible if column in frame.columns]]
        self.clip_candidates_table.setModel(FrameModel(frame))
        if selected_id is not None and not frame.empty and "id" in frame.columns:
            matches = frame.index[frame["id"] == int(selected_id)].tolist()
            if matches:
                self.clip_candidates_table.selectRow(int(matches[0]))
