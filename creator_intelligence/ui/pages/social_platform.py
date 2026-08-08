from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.ui.oauth_connect import run_browser_oauth, show_connection_result
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.widgets import (
    ConnectionStatusPanel,
    FlowLayout,
    MetricCard,
    StatusBanner,
    set_button_enabled,
)


LABELS = {
    "youtube": {"api_key": "YouTube Data API key", "channel_id": "Channel ID"},
    "instagram": {
        "app_id": "Meta app ID",
        "app_secret": "App secret",
        "access_token": "Long-lived access token",
        "account_id": "Instagram professional account ID",
        "redirect_uri": "OAuth redirect URI",
    },
    "tiktok": {
        "client_key": "TikTok client key",
        "client_secret": "Client secret",
        "access_token": "Access token",
        "refresh_token": "Refresh token",
        "user_id": "TikTok user/open ID",
        "redirect_uri": "OAuth redirect URI",
    },
}


class SocialPlatformPage(QWidget):
    def __init__(self, service, platform: str):
        super().__init__()
        self.service = service
        self.platform = platform
        self.manual_flow = None
        self.validation_timer = QTimer(self)
        self.validation_timer.setInterval(60 * 60 * 1000)
        self.validation_timer.timeout.connect(self.validate_silently)
        self.validation_timer.start()
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(30 * 60 * 1000)
        self.sync_timer.timeout.connect(self.sync_silently)
        self.sync_timer.start()

        layout = QVBoxLayout(self)
        title = QLabel(f"{platform.title()} Intelligence")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        cards = QHBoxLayout()
        self.cards = {}
        for key, label in (
            ("posts", "Posts"),
            ("views", "Views"),
            ("likes", "Likes"),
            ("comments", "Comments"),
            ("shares", "Shares"),
            ("engagement_rate", "Engagement rate"),
        ):
            self.cards[key] = MetricCard(label)
            cards.addWidget(self.cards[key])
        layout.addLayout(cards)

        connection = QGroupBox("API connection")
        connection_layout = QVBoxLayout(connection)
        self.connection_panel = ConnectionStatusPanel(platform.title())
        connection_layout.addWidget(self.connection_panel)
        self.banner = StatusBanner("Connection checks run automatically while this page is open.")
        connection_layout.addWidget(self.banner)
        form = QFormLayout()
        connection_layout.addLayout(form)

        self.enabled = QCheckBox("Enable title and performance sync")
        form.addRow(self.enabled)
        self.fields = {}
        for key, label in LABELS[platform].items():
            field = QLineEdit()
            if "secret" in key or "token" in key or "api_key" in key:
                field.setEchoMode(QLineEdit.EchoMode.Password)
            if key in {"access_token", "refresh_token", "account_id", "user_id"}:
                field.setReadOnly(True)
                field.setPlaceholderText("Filled automatically after sign-in")
            self.fields[key] = field
            form.addRow(label, field)
        if "redirect_uri" in self.fields:
            default_port = 49153 if platform == "instagram" else 49152
            self.fields["redirect_uri"].setPlaceholderText(
                f"http://127.0.0.1:{default_port}/callback/"
            )

        controls_widget = QWidget()
        controls = FlowLayout(controls_widget)
        self.connect_button = QPushButton(f"Connect or reconnect {platform.title()}")
        self.connect_button.clicked.connect(self.connect_account)
        self.validate_button = QPushButton("Check connection")
        self.validate_button.clicked.connect(self.validate_connection)
        self.sync_button = QPushButton("Sync content and stats")
        self.sync_button.clicked.connect(self.sync_now)
        refresh = QPushButton("Refresh stats")
        refresh.clicked.connect(self.refresh)
        self.disconnect_button = QPushButton("Disconnect and clear credentials")
        self.disconnect_button.clicked.connect(self.disconnect)
        for button in (
            self.connect_button,
            self.validate_button,
            self.sync_button,
            refresh,
            self.disconnect_button,
        ):
            controls.addWidget(button)
        form.addRow(controls_widget)

        advanced = QGroupBox("Advanced manual setup")
        advanced_buttons = FlowLayout(advanced)
        save = QPushButton("Save API setup")
        save.clicked.connect(self.save)
        authorize = QPushButton("Copy OAuth authorization URL")
        authorize.clicked.connect(self.copy_authorization_url)
        exchange = QPushButton("Enter callback URL")
        exchange.clicked.connect(self.exchange_code)
        token_refresh = QPushButton("Refresh access token")
        token_refresh.clicked.connect(self.refresh_token)
        for button in (save, authorize, exchange, token_refresh):
            advanced_buttons.addWidget(button)
        form.addRow(advanced)

        self.status = QLabel()
        self.status.setWordWrap(True)
        form.addRow("Status", self.status)
        self.capabilities = QLabel()
        self.capabilities.setWordWrap(True)
        form.addRow("Available access", self.capabilities)
        policy = QLabel(
            "One active account per platform is stored in each workspace. Reconnecting replaces "
            "the previous account. Tokens stay in the operating-system credential vault."
        )
        policy.setWordWrap(True)
        form.addRow("Account policy", policy)
        layout.addWidget(connection)

        self.table = QTableView()
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)
        self.load()
        self.refresh()
        QTimer.singleShot(1500, self.validate_silently)

    def load(self):
        config = self.service.display_configuration(self.platform)
        self.enabled.setChecked(bool(config.get("enabled")))
        for key, field in self.fields.items():
            field.setText(str(config.get(key) or ""))

    def save(self, silent=False):
        self.service.save_configuration(
            self.platform,
            {key: field.text() for key, field in self.fields.items()},
            self.enabled.isChecked(),
        )
        self.refresh()
        if not silent:
            QMessageBox.information(
                self, "API setup", f"{self.platform.title()} API settings saved."
            )

    def refresh(self):
        summary = self.service.summary(self.platform)
        for key, card in self.cards.items():
            value = summary[key]
            value = f"{value:,.2f}%" if key == "engagement_rate" else f"{value:,}"
            card.update_value(value)

        status = self.service.connection_status(self.platform)
        self.connection_panel.set_status(status)
        if status["configured"]:
            account = f" as {status['account_name']}" if status.get("account_name") else ""
            message = (
                f"{status['state'].replace('_', ' ').title()}{account} "
                f"· Sync: {status['sync_status']}"
            )
        else:
            names = [LABELS[self.platform].get(field, field) for field in status["missing"]]
            message = "Missing: " + ", ".join(names)
        if status.get("last_synced_at"):
            message += f" · Last sync: {status['last_synced_at']}"
        if status.get("last_error"):
            message += f" · Error: {status['last_error']}"
        self.status.setText(message)

        access = []
        for item in status.get("capabilities") or []:
            marker = "Available" if item["available"] else "Unavailable"
            access.append(f"{marker}: {item['capability']} — {item['permission']}")
        self.capabilities.setText("\n".join(access))

        app_field = self.fields.get("app_id") or self.fields.get("client_key")
        has_app_setup = bool(app_field and app_field.text().strip())
        set_button_enabled(
            self.connect_button,
            has_app_setup,
            f"Save the {self.platform.title()} app details first.",
        )
        set_button_enabled(
            self.validate_button,
            bool(status.get("can_disconnect")),
            f"Connect {self.platform.title()} before checking the account.",
        )
        set_button_enabled(
            self.sync_button,
            bool(status.get("can_sync")) and self.enabled.isChecked(),
            f"Connect {self.platform.title()}, approve content access, and enable sync first.",
        )
        set_button_enabled(
            self.disconnect_button,
            bool(status.get("can_disconnect")),
            f"There are no saved {self.platform.title()} account credentials to clear.",
        )
        self.table.setModel(FrameModel(self.service.content(self.platform)))

    def connect_account(self):
        if "redirect_uri" in self.fields and not self.fields["redirect_uri"].text().strip():
            port = 49153 if self.platform == "instagram" else 49152
            self.fields["redirect_uri"].setText(f"http://127.0.0.1:{port}/callback/")
        self.enabled.setChecked(True)
        self.save(silent=True)
        redirect = self.fields.get("redirect_uri")
        try:
            result = run_browser_oauth(
                self,
                self.service,
                self.platform,
                redirect.text().strip() if redirect else None,
            )
        except Exception as exc:
            self.banner.set_status(f"Connection failed: {exc}", "error")
            QMessageBox.critical(self, f"Connect {self.platform.title()}", str(exc))
            return
        if result:
            self.load()
            self.refresh()
            show_connection_result(self, self.platform, result)
            self._initial_sync_after_connect()

    def _initial_sync_after_connect(self):
        status = self.service.connection_status(self.platform)
        if not status.get("can_sync"):
            self.banner.set_status(status.get("message") or "Connected with limited access.", "warning")
            return
        try:
            result = self.service.sync(self.platform)
        except Exception as exc:
            self.banner.set_status(f"Connected, but the first sync failed: {exc}", "warning")
            self.refresh()
            return
        self._show_sync_result(result, prefix="Connected. ")
        self.refresh()

    def copy_authorization_url(self):
        self.save(silent=True)
        try:
            redirect = self.fields.get("redirect_uri")
            self.manual_flow = self.service.begin_oauth(
                self.platform, redirect.text().strip() if redirect else None
            )
            url = self.manual_flow["authorization_url"]
        except Exception as exc:
            QMessageBox.critical(self, "OAuth setup", str(exc))
            return
        QApplication.clipboard().setText(url)
        QMessageBox.information(
            self,
            "OAuth setup",
            "Authorization URL copied. Open it in your browser, approve access, then paste "
            "the complete callback URL here.",
        )

    def exchange_code(self):
        if not self.manual_flow:
            QMessageBox.information(
                self, "OAuth authorization", "Create the authorization URL first."
            )
            return
        callback_url, ok = QInputDialog.getMultiLineText(
            self, "OAuth authorization", "Complete callback URL:"
        )
        if not ok or not callback_url.strip():
            return
        callback = {
            key: values[0]
            for key, values in parse_qs(urlparse(callback_url.strip()).query).items()
            if values
        }
        if not callback:
            QMessageBox.critical(
                self,
                "OAuth authorization",
                "Paste the complete callback URL, including its code and state values.",
            )
            return
        try:
            result = self.service.complete_oauth(
                self.platform, callback, self.manual_flow
            )
        except Exception as exc:
            QMessageBox.critical(self, "OAuth authorization", str(exc))
            return
        self.load()
        self.refresh()
        show_connection_result(self, self.platform, result)
        self._initial_sync_after_connect()

    def sync_now(self):
        self.save(silent=True)
        try:
            result = self.service.sync(self.platform)
        except Exception as exc:
            self.banner.set_status(f"Sync failed: {exc}", "error")
            QMessageBox.critical(self, f"{self.platform.title()} sync", str(exc))
            self.refresh()
            return
        self.refresh()
        self._show_sync_result(result)
        QMessageBox.information(
            self,
            f"{self.platform.title()} sync",
            f"Found {result['seen']} post(s); updated {result['changed']}.",
        )

    def _show_sync_result(self, result, prefix=""):
        warnings = result.get("warnings") or []
        message = (
            f"{prefix}Found {result['seen']} item(s); updated {result['changed']}."
        )
        if warnings:
            message += " " + " ".join(warnings)
        self.banner.set_status(message, "warning" if warnings else "success")

    def refresh_token(self):
        self.save(silent=True)
        try:
            self.service.refresh_access_token(self.platform)
        except Exception as exc:
            self.banner.set_status(f"Token refresh failed: {exc}", "error")
            QMessageBox.critical(self, "Token refresh", str(exc))
            return
        self.load()
        self.refresh()
        self.banner.set_status("Access token refreshed and saved.", "success")

    def validate_connection(self):
        status = self.service.validate_connection(self.platform)
        self.refresh()
        level = "info" if status.get("state") in {"connected", "limited"} else "error"
        self.banner.set_status(status.get("message") or "Connection check complete.", level)

    def validate_silently(self):
        status = self.service.connection_status(self.platform)
        if not status.get("can_disconnect"):
            return
        try:
            self.service.validate_connection(self.platform)
        except Exception:
            return
        self.refresh()

    def sync_silently(self):
        status = self.service.connection_status(self.platform)
        if not status.get("can_sync") or not self.enabled.isChecked():
            return
        try:
            result = self.service.sync(self.platform)
        except Exception as exc:
            self.banner.set_status(
                f"Background {self.platform.title()} sync failed: {exc}", "warning"
            )
            self.refresh()
            return
        self._show_sync_result(result)
        self.refresh()

    def disconnect(self):
        if (
            QMessageBox.question(
                self,
                "Disconnect account",
                "Clear this platform's credentials from the operating-system vault?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        result = self.service.revoke_and_disconnect(self.platform)
        self.load()
        self.refresh()
        warning = result.get("revocation_warning")
        self.banner.set_status(
            warning or f"{self.platform.title()} credentials were cleared.",
            "warning" if warning else "success",
        )
