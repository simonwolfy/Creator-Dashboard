from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,QInputDialog,
    QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.widgets import MetricCard


LABELS = {
    "youtube": {"api_key": "YouTube Data API key", "channel_id": "Channel ID"},
    "instagram": {"app_id": "Meta app ID", "app_secret": "App secret",
                  "access_token": "Long-lived access token", "account_id": "Instagram business account ID",
                  "redirect_uri": "OAuth redirect URI"},
    "tiktok": {"client_key": "TikTok client key", "client_secret": "Client secret",
               "access_token": "Access token", "refresh_token": "Refresh token",
               "user_id": "TikTok user/open ID", "redirect_uri": "OAuth redirect URI"},
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
                           ("comments", "Comments"), ("shares", "Shares"),
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
        authorize = QPushButton("Copy OAuth authorization URL")
        authorize.clicked.connect(self.copy_authorization_url)
        exchange = QPushButton("Exchange authorization code")
        exchange.clicked.connect(self.exchange_code)
        token_refresh = QPushButton("Refresh access token")
        token_refresh.clicked.connect(self.refresh_token)
        sync = QPushButton("Sync now")
        sync.clicked.connect(self.sync_now)
        refresh = QPushButton("Refresh stats")
        refresh.clicked.connect(self.refresh)
        disconnect = QPushButton("Disconnect / revoke and clear credentials")
        disconnect.clicked.connect(self.disconnect)
        buttons.addWidget(save)
        buttons.addWidget(authorize)
        buttons.addWidget(exchange)
        buttons.addWidget(token_refresh)
        buttons.addWidget(sync)
        buttons.addWidget(refresh)
        buttons.addWidget(disconnect)
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
        config = self.service.display_configuration(self.platform)
        self.enabled.setChecked(bool(config.get("enabled")))
        for key, field in self.fields.items():
            field.setText(str(config.get(key) or ""))

    def save(self, silent=False):
        self.service.save_configuration(
            self.platform, {key: field.text() for key, field in self.fields.items()},
            self.enabled.isChecked(),
        )
        self.refresh()
        if not silent:
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

    def copy_authorization_url(self):
        self.save(silent=True)
        try:
            url = self.service.authorization_url(self.platform)
        except Exception as exc:
            QMessageBox.critical(self, "OAuth setup", str(exc)); return
        QApplication.clipboard().setText(url)
        QMessageBox.information(self, "OAuth setup", "Authorization URL copied. Open it in your browser, approve access, then paste the returned code here.")

    def exchange_code(self):
        code, ok = QInputDialog.getText(self, "OAuth authorization", "Authorization code:")
        if not ok or not code.strip(): return
        try:
            self.service.exchange_authorization_code(self.platform, code.strip())
        except Exception as exc:
            QMessageBox.critical(self, "OAuth authorization", str(exc)); return
        self.load(); self.refresh()
        QMessageBox.information(self, "OAuth authorization", "Access token saved.")

    def sync_now(self):
        self.save(silent=True)
        try:
            result = self.service.sync(self.platform)
        except Exception as exc:
            QMessageBox.critical(self, f"{self.platform.title()} sync", str(exc)); self.refresh(); return
        self.refresh()
        QMessageBox.information(self, f"{self.platform.title()} sync",
                                f"Found {result['seen']} post(s); updated {result['changed']}.")

    def refresh_token(self):
        self.save(silent=True)
        try:
            self.service.refresh_access_token(self.platform)
        except Exception as exc:
            QMessageBox.critical(self, "Token refresh", str(exc)); return
        self.load(); self.refresh()
        QMessageBox.information(self, "Token refresh", "Access token refreshed and saved.")

    def disconnect(self):
        if QMessageBox.question(self,"Disconnect account","Clear this platform's credentials from the operating-system vault?")!=QMessageBox.StandardButton.Yes:
            return
        try:self.service.revoke_and_disconnect(self.platform)
        except Exception as exc:QMessageBox.warning(self,"Could not revoke access",str(exc));return
        self.load();self.refresh()
