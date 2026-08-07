from __future__ import annotations

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


class GoogleDrivePage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Google Drive")
        title.setObjectName("pageTitle")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        layout.addLayout(header)

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
        self.error_value = QLabel()
        self.error_value.setWordWrap(True)

        form.addRow("Status", self.status_value)
        form.addRow("Account", self.account_value)
        form.addRow("OAuth client file", self.client_path)
        form.addRow("", self.choose_button)
        form.addRow("Last tested", self.last_tested_value)
        form.addRow("Last error", self.error_value)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.connect_button = QPushButton("Connect Google Drive")
        self.connect_button.clicked.connect(self.connect_drive)
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self.test_connection)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect)
        actions.addWidget(self.connect_button)
        actions.addWidget(self.test_button)
        actions.addWidget(self.disconnect_button)
        actions.addStretch()
        layout.addLayout(actions)

        note = QLabel(
            "Choose a Google OAuth desktop client-secrets JSON file first. "
            "Connect becomes available after the file is accepted. Tokens are stored in the Windows credential vault, "
            "not in the Creator Intelligence database."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.refresh()

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
            self.refresh()
            QMessageBox.information(self, "Google Drive", "Google Drive connected successfully.")
        except Exception as exc:
            self.refresh()
            QMessageBox.critical(self, "Unable to connect", str(exc))

    def test_connection(self) -> None:
        try:
            self.service.test_connection()
            self.refresh()
            QMessageBox.information(self, "Google Drive", "Connection test succeeded.")
        except Exception as exc:
            self.refresh()
            QMessageBox.critical(self, "Connection test failed", str(exc))

    def disconnect(self) -> None:
        try:
            self.service.disconnect()
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Unable to disconnect", str(exc))

    def refresh(self) -> None:
        status = self.service.status()
        self.status_value.setText(status.status)
        account = status.account_email or "Not connected"
        if status.display_name:
            account = f"{status.display_name} ({account})"
        self.account_value.setText(account)
        self.client_path.setText(status.client_secrets_path or "")
        self.last_tested_value.setText(status.last_tested_at or "Never")
        self.error_value.setText(status.last_error or "None")
        self.choose_button.setEnabled(True)
        self.connect_button.setEnabled(status.configured)
        self.test_button.setEnabled(status.connected)
        self.disconnect_button.setEnabled(status.connected)
