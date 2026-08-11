from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from creator_intelligence.ui.widgets import (
    ConnectionStatusPanel, FlowLayout, StatusBanner, set_button_enabled,
)


class GoogleDrivePage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.validation_timer = QTimer(self)
        self.validation_timer.setInterval(60 * 60 * 1000)
        self.validation_timer.timeout.connect(self.validate_silently)
        self.validation_timer.start()
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(30 * 60 * 1000)
        self.sync_timer.timeout.connect(self.sync_silently)
        self.sync_timer.start()
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Google Drive")
        title.setObjectName("pageTitle")
        refresh = QPushButton("Refresh page")
        refresh.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        layout.addLayout(header)

        self.connection_panel = ConnectionStatusPanel("Google Drive")
        layout.addWidget(self.connection_panel)
        self.banner = StatusBanner("Connection checks run automatically while this page is open.")
        layout.addWidget(self.banner)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        self.status_value = QLabel()
        self.account_value = QLabel()
        self.client_path = QLineEdit()
        self.client_path.setReadOnly(True)
        self.client_path.setPlaceholderText("No OAuth client-secrets file selected")

        self.choose_button = QPushButton("Browse for client-secrets JSON...")
        self.choose_button.clicked.connect(self.choose_client_file)

        self.last_tested_value = QLabel()
        self.last_synced_value = QLabel()
        self.error_value = QLabel()
        self.error_value.setWordWrap(True)

        form.addRow("Status", self.status_value)
        form.addRow("Account", self.account_value)
        form.addRow("OAuth client file", self.client_path)
        form.addRow("", self.choose_button)
        form.addRow("Last tested", self.last_tested_value)
        form.addRow("Last synced", self.last_synced_value)
        form.addRow("Last error", self.error_value)
        layout.addLayout(form)

        actions_widget = QWidget()
        actions = FlowLayout(actions_widget)
        self.connect_button = QPushButton("Connect Google Drive")
        self.connect_button.clicked.connect(self.connect_drive)
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self.test_connection)
        self.sync_button = QPushButton("Sync Drive metadata")
        self.sync_button.clicked.connect(self.sync_now)
        self.disconnect_button = QPushButton("Disconnect and revoke access")
        self.disconnect_button.clicked.connect(self.disconnect)
        actions.addWidget(self.connect_button)
        actions.addWidget(self.test_button)
        actions.addWidget(self.sync_button)
        actions.addWidget(self.disconnect_button)
        layout.addWidget(actions_widget)

        note = QLabel(
            "Choose a Google OAuth desktop client-secrets JSON file first. "
            "Connect becomes available after the file is accepted. Tokens are stored in the Windows credential vault, "
            "not in the Creator Intelligence database. Creator Intelligence requests metadata-only access and cannot "
            "download contents or change Drive files."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.refresh()
        QTimer.singleShot(1500, self.validate_silently)

    def choose_client_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Google OAuth client-secrets file",
            "",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            self.service.configure(path)
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid OAuth file", str(exc))

    def connect_drive(self) -> None:
        try:
            self.service.connect()
            try:
                result = self.service.sync_now()
            except Exception as sync_exc:
                self.banner.set_status(
                    f"Drive connected, but the initial folder summary needs attention: {sync_exc}", "warning"
                )
            else:
                self.banner.set_status(f"Initial Drive sync complete. {result['summary']}.", "info")
            self.refresh()
            QMessageBox.information(self, "Google Drive", "Google Drive connected successfully.")
        except Exception as exc:
            self.refresh()
            QMessageBox.critical(self, "Unable to connect", str(exc))

    def test_connection(self) -> None:
        try:
            self.service.test_connection()
            self.refresh()
            self.banner.set_status("Google Drive connection is healthy.", "info")
            QMessageBox.information(self, "Google Drive", "Connection test succeeded.")
        except Exception as exc:
            self.refresh()
            QMessageBox.critical(self, "Connection test failed", str(exc))

    def disconnect(self) -> None:
        if QMessageBox.question(
            self, "Disconnect Google Drive",
            "Revoke Google access and clear the locally stored credentials?",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            status = self.service.revoke_and_disconnect()
            self.refresh()
            self.banner.set_status(
                status.last_error or "Google Drive disconnected and local credentials cleared.",
                "warning" if status.last_error else "info",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Unable to disconnect", str(exc))

    def sync_now(self) -> None:
        try:
            result = self.service.sync_now()
            self.refresh()
            self.banner.set_status(f"Drive sync complete. {result['summary']}.", "info")
        except Exception as exc:
            self.refresh()
            self.banner.set_status(f"Drive sync failed: {exc}", "warning")
            QMessageBox.critical(self, "Drive sync failed", str(exc))

    def validate_silently(self) -> None:
        if not self.service.status().connected:
            return
        try:
            self.service.test_connection()
        except Exception:
            pass
        self.refresh()

    def sync_silently(self) -> None:
        if not self.service.status().connected:
            return
        try:
            result = self.service.sync_now()
        except Exception as exc:
            self.banner.set_status(f"Background Drive sync failed: {exc}", "warning")
            self.refresh()
            return
        self.banner.set_status(f"Background Drive sync complete. {result['summary']}.", "info")
        self.refresh()

    def refresh(self) -> None:
        status = self.service.status()
        lifecycle = self.service.connection_status()
        self.connection_panel.set_status(lifecycle)
        self.status_value.setText(status.status)
        account = status.account_email or "Not connected"
        if status.display_name:
            account = f"{status.display_name} ({account})"
        self.account_value.setText(account)
        self.client_path.setText(status.client_secrets_path or "")
        self.last_tested_value.setText(status.last_tested_at or "Never")
        sync_text = status.last_synced_at or "Never"
        if status.last_sync_summary:
            sync_text = f"{sync_text} · {status.last_sync_summary}"
        self.last_synced_value.setText(sync_text)
        self.error_value.setText(status.last_error or "None")
        self.choose_button.setEnabled(True)
        set_button_enabled(
            self.connect_button, status.configured,
            "Choose a Google Desktop OAuth JSON file first.",
        )
        set_button_enabled(
            self.test_button, lifecycle.get("can_disconnect", False),
            "Connect Google Drive before testing it.",
        )
        set_button_enabled(
            self.sync_button, lifecycle.get("can_sync", False),
            "Connect Google Drive before synchronizing metadata.",
        )
        set_button_enabled(
            self.disconnect_button, lifecycle.get("can_disconnect", False),
            "There are no saved Google Drive credentials to clear.",
        )
