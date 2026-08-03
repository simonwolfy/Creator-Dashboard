from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.ui.pages.transcript_editor import (
    EXPORT_FORMATS,
    TranscriptEditorPage,
)


class MetricCard(QFrame):
    """Compact read-only statistic card used by the transcript editor."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("metricCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(118)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(1)

        self.value_label = QLabel("—")
        self.value_label.setObjectName("metricValue")
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        layout.addWidget(self.value_label)
        layout.addWidget(title_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class PolishedTranscriptEditorPage(TranscriptEditorPage):
    """Commercial-style layout layered over the complete transcript editor."""

    def __init__(self, service):
        super().__init__(service)
        self._editor_buttons: dict[str, QPushButton] = {}

        # Hide the original dense editor rows while retaining their behavior.
        hidden_labels = {
            "Edit text", "Assign speaker", "Split segment", "Merge segments",
            "Delete segment", "Mark reviewed", "Needs revision", "Mark unreviewed",
            "Rename chapter", "Split chapter", "Merge chapters", "Delete chapter",
            "Create chapter", "Export selected transcript",
        }
        for button in self.findChildren(QPushButton):
            if button.text() in hidden_labels:
                button.hide()
        self.stats_label.hide()
        self.export_format.hide()

        root = self.layout()
        insert_at = root.indexOf(self.tabs)

        self.selected_title = QLabel("No transcript selected")
        self.selected_title.setObjectName("selectedTranscriptTitle")
        self.selected_metadata = QLabel("Select a transcript to begin editing.")
        self.selected_metadata.setWordWrap(True)
        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(self.selected_title)
        header.addWidget(self.selected_metadata)
        root.insertLayout(insert_at, header)
        insert_at += 1

        self.metric_cards = {
            "Words": MetricCard("Words"),
            "Segments": MetricCard("Segments"),
            "Chapters": MetricCard("Chapters"),
            "Speakers": MetricCard("Speakers"),
            "WPM": MetricCard("Words / minute"),
            "Silence": MetricCard("Silence"),
            "Pause": MetricCard("Longest pause"),
            "Confidence": MetricCard("Confidence"),
        }
        metrics = QHBoxLayout()
        metrics.setSpacing(7)
        for card in self.metric_cards.values():
            metrics.addWidget(card)
        metrics.addStretch()
        root.insertLayout(insert_at, metrics)
        insert_at += 1

        ribbon = QGridLayout()
        ribbon.setHorizontalSpacing(8)
        ribbon.setVerticalSpacing(6)
        ribbon.addWidget(self._segment_group(), 0, 0)
        ribbon.addWidget(self._review_group(), 0, 1)
        ribbon.addWidget(self._chapter_group(), 0, 2)
        ribbon.addWidget(self._export_group(), 0, 3)
        ribbon.setColumnStretch(0, 2)
        ribbon.setColumnStretch(1, 1)
        ribbon.setColumnStretch(2, 2)
        ribbon.setColumnStretch(3, 1)
        root.insertLayout(insert_at, ribbon)

        self.transcripts_table.selectionModel().selectionChanged.connect(
            lambda *_: self._update_polished_state()
        )
        self.segments_table.selectionModel().selectionChanged.connect(
            lambda *_: self._update_action_states()
        )
        self.chapters_table.selectionModel().selectionChanged.connect(
            lambda *_: self._update_action_states()
        )
        self.tabs.currentChanged.connect(lambda *_: self._update_action_states())

        self._install_style()
        self._update_polished_state()

    def _make_button(self, label: str, handler, key: str) -> QPushButton:
        button = QPushButton(label)
        button.clicked.connect(handler)
        self._editor_buttons[key] = button
        return button

    def _segment_group(self) -> QGroupBox:
        group = QGroupBox("Segment editing")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.addWidget(self._make_button("Edit", self.edit_segment, "edit"))
        layout.addWidget(self._make_button("Split", self.split_segment, "split_segment"))
        layout.addWidget(self._make_button("Merge", self.merge_segments, "merge_segment"))
        layout.addWidget(self._make_button("Delete", self.delete_segment, "delete_segment"))
        layout.addWidget(self._make_button("Assign speaker", self.assign_speaker, "speaker"))
        return group

    def _review_group(self) -> QGroupBox:
        group = QGroupBox("Review")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.addWidget(self._make_button(
            "Reviewed", lambda: self.set_review_status("Reviewed"), "reviewed"
        ))
        layout.addWidget(self._make_button(
            "Needs revision", lambda: self.set_review_status("Needs revision"), "revision"
        ))
        layout.addWidget(self._make_button(
            "Reset", lambda: self.set_review_status("Unreviewed"), "unreviewed"
        ))
        return group

    def _chapter_group(self) -> QGroupBox:
        group = QGroupBox("Chapters")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.addWidget(self._make_button("Rename", self.rename_chapter, "rename_chapter"))
        layout.addWidget(self._make_button("Split", self.split_chapter, "split_chapter"))
        layout.addWidget(self._make_button("Merge", self.merge_chapters, "merge_chapter"))
        layout.addWidget(self._make_button("Delete", self.delete_chapter, "delete_chapter"))
        layout.addWidget(self._make_button("Create", self.create_chapter, "create_chapter"))
        return group

    def _export_group(self) -> QGroupBox:
        group = QGroupBox("Export")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(8, 7, 8, 7)
        self.polished_export_format = QComboBox()
        self.polished_export_format.addItems(EXPORT_FORMATS.keys())
        self.polished_export_format.currentTextChanged.connect(
            self._sync_export_selection
        )
        layout.addWidget(self.polished_export_format)
        layout.addWidget(self._make_button(
            "Export", self.export_selected_format, "export"
        ))
        return group

    def _sync_export_selection(self, label: str) -> None:
        index = self.export_format.findText(label)
        if index >= 0:
            self.export_format.setCurrentIndex(index)

    def refresh_details(self):
        super().refresh_details()
        if hasattr(self, "metric_cards"):
            self._update_polished_state()

    def _update_polished_state(self) -> None:
        transcript_id = self.selected_transcript_id()
        if not transcript_id:
            self.selected_title.setText("No transcript selected")
            self.selected_metadata.setText("Select a transcript to begin editing.")
            for card in self.metric_cards.values():
                card.set_value("—")
            self._update_action_states()
            return

        try:
            transcript = self.service.transcript(transcript_id)
            stats = self.service.transcript_statistics(transcript_id)
        except Exception as exc:
            self.selected_title.setText("Transcript unavailable")
            self.selected_metadata.setText(str(exc))
            self._update_action_states()
            return

        title = str(transcript.get("title") or f"Transcript {transcript_id}")
        duration = self._clock(stats.get("duration_seconds") or 0)
        language = str(transcript.get("language") or "Unknown").upper()
        model = str(transcript.get("model_name") or "Unknown")
        engine = str(transcript.get("engine") or "Unknown")
        self.selected_title.setText(title)
        self.selected_metadata.setText(
            f"Duration {duration}   •   Language {language}   •   "
            f"Engine {engine}   •   Model {model}"
        )

        confidence = stats.get("average_confidence")
        confidence_text = "—" if confidence is None else f"{float(confidence) * 100:.1f}%"
        values = {
            "Words": f"{int(stats.get('word_count') or 0):,}",
            "Segments": f"{int(stats.get('segment_count') or 0):,}",
            "Chapters": f"{int(stats.get('chapter_count') or 0):,}",
            "Speakers": f"{int(stats.get('speaker_count') or 0):,}",
            "WPM": f"{float(stats.get('words_per_minute') or 0):.1f}",
            "Silence": f"{float(stats.get('silence_percent') or 0):.1f}%",
            "Pause": f"{float(stats.get('longest_pause_seconds') or 0):.1f}s",
            "Confidence": confidence_text,
        }
        for key, value in values.items():
            self.metric_cards[key].set_value(value)
        self._update_action_states()

    def _update_action_states(self) -> None:
        if not hasattr(self, "_editor_buttons"):
            return
        transcript_selected = self.selected_transcript_id() is not None
        segment_count = len(self._selected_segments())
        chapter_count = len(self._selected_chapters())

        states = {
            "edit": segment_count == 1,
            "split_segment": segment_count == 1,
            "merge_segment": segment_count == 2,
            "delete_segment": segment_count >= 1,
            "speaker": segment_count >= 1,
            "reviewed": segment_count >= 1,
            "revision": segment_count >= 1,
            "unreviewed": segment_count >= 1,
            "rename_chapter": chapter_count == 1,
            "split_chapter": chapter_count == 1,
            "merge_chapter": chapter_count == 2,
            "delete_chapter": chapter_count >= 1,
            "create_chapter": transcript_selected,
            "export": transcript_selected,
        }
        for key, enabled in states.items():
            button = self._editor_buttons.get(key)
            if button is not None:
                button.setEnabled(enabled)

    def _install_style(self) -> None:
        self.setStyleSheet(self.styleSheet() + """
            QLabel#selectedTranscriptTitle {
                font-size: 17px;
                font-weight: 700;
                padding-top: 3px;
            }
            QFrame#metricCard {
                background: rgba(255, 255, 255, 0.035);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
            }
            QLabel#metricValue {
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#metricTitle {
                color: #aeb6c8;
                font-size: 11px;
            }
            QGroupBox {
                font-weight: 600;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
        """)
