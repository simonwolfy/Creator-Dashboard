from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.widgets import MetricCard


LABELS = {
    "youtube": {"api_key": "YouTube Data API key", "channel_id": "Channel ID"},
    "instagram": {"app_id": "Meta app ID", "app_secret": "App secret",
                  "access_token": "Long-lived access token", "account_id": "Instagram business account ID"},
    "tiktok": {"client_key": "TikTok client key", "client_secret": "Client secret",
               "access_token": "Access token", "user_id": "TikTok user/open ID"},
}


class SocialPlatformPage(QWidget):
    def __init__(self, service, platform: str):
        super().__init__()
        self.service = service
        self.platform = platform
        layout = QVBoxLayout(self)
        title = QLabel(f"{platform.title()} Intelligence")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        cards = QHBoxLayout()
        self.cards = {}
        for key, label in (("posts", "Posts"), ("views", "Views"), ("likes", "Likes"),
                           ("comments", "Comments"), ("watch_time", "Watch time"),
                           ("engagement_rate", "Engagement rate")):
            self.cards[key] = MetricCard(label)
            cards.addWidget(self.cards[key])
        layout.addLayout(cards)

        connection = QGroupBox("API connection")
        form = QFormLayout(connection)
        self.enabled = QCheckBox("Enable title and performance sync")
        form.addRow(self.enabled)
        self.fields = {}
        for key, label in LABELS[platform].items():
            field = QLineEdit()
            if "secret" in key or "token" in key or "api_key" in key:
                field.setEchoMode(QLineEdit.EchoMode.Password)
            self.fields[key] = field
            form.addRow(label, field)
        buttons = QHBoxLayout()
        save = QPushButton("Save API setup")
        save.clicked.connect(self.save)
        refresh = QPushButton("Refresh stats")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(save)
        buttons.addWidget(refresh)
        buttons.addStretch()
        form.addRow(buttons)
        self.status = QLabel()
        self.status.setWordWrap(True)
        form.addRow("Status", self.status)
        layout.addWidget(connection)

        self.table = QTableView()
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)
        self.load()
        self.refresh()

    def load(self):
        config = self.service.configuration(self.platform)
        self.enabled.setChecked(bool(config.get("enabled")))
        for key, field in self.fields.items():
            field.setText(str(config.get(key) or ""))

    def save(self):
        self.service.save_configuration(
            self.platform, {key: field.text() for key, field in self.fields.items()},
            self.enabled.isChecked(),
        )
        self.refresh()
        QMessageBox.information(self, "API setup", f"{self.platform.title()} API settings saved.")

    def refresh(self):
        summary = self.service.summary(self.platform)
        for key, card in self.cards.items():
            value = summary[key]
            if key == "engagement_rate":
                value = f"{value:,.2f}%"
            elif key == "watch_time":
                value = f"{value:,.1f}"
            else:
                value = f"{value:,}"
            card.update_value(value)
        status = self.service.connection_status(self.platform)
        if status["configured"]:
            message = f"Configured · Sync: {status['sync_status']}"
        else:
            names = [LABELS[self.platform].get(field, field) for field in status["missing"]]
            message = "Missing: " + ", ".join(names)
        if status.get("last_synced_at"):
            message += f" · Last sync: {status['last_synced_at']}"
        if status.get("last_error"):
            message += f" · Error: {status['last_error']}"
        self.status.setText(message)
        self.table.setModel(FrameModel(self.service.content(self.platform)))
