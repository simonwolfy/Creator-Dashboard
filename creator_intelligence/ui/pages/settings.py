from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QColorDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.core.config import ConfigService
from creator_intelligence.core.health import HealthService
from creator_intelligence.core.versioning import APPLICATION_VERSION
from creator_intelligence.services.backup import BackupService
from creator_intelligence.services.update_checker import RELEASES_PAGE_URL, UpdateStatus
from creator_intelligence.ui.theme import ACCENT_PRESETS, DEFAULT_ACCENT, normalize_accent
from creator_intelligence.ui.update_worker import UpdateCheckWorker, UpdateDownloadWorker
from creator_intelligence.ui.widgets import set_button_enabled
from creator_intelligence.utils.paths import BACKUP_DIR, DB_PATH


class SettingsPage(QWidget):
    appearance_changed = Signal(str, str)

    def __init__(self, db, context=None):
        super().__init__()
        self.db = db
        self.context = context
        self.onboarding = context.services.get("onboarding") if context else None
        self.update_checker = context.services.get("update_checker") if context else None
        self.runtime_setup = context.services.get("runtime_setup") if context else None
        self.update_release = None
        self.update_worker = None
        self.download_worker = None
        workspace = context.services.get("workspace") if context else None
        config_path = workspace.paths.config / "settings.json" if workspace else None
        backup_dir = workspace.paths.backups if workspace else BACKUP_DIR
        database_path = workspace.paths.database if workspace else DB_PATH
        self.config_service = ConfigService(config_path)
        self.config = self.config_service.load()
        self.backups = BackupService(database_path, backup_dir, self.config.backup_retention)
        self.database_path = database_path

        layout=QVBoxLayout(self)
        title=QLabel("Settings and Maintenance")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        appearance = QGroupBox("Appearance")
        appearance_form = QFormLayout(appearance)
        self.theme_selector = QComboBox()
        self.theme_selector.addItem("Dark", "dark")
        self.theme_selector.addItem("Light", "light")
        self.theme_selector.addItem("Use Windows setting", "system")
        theme_index = self.theme_selector.findData(self.config.theme)
        self.theme_selector.setCurrentIndex(max(0, theme_index))

        self.custom_accent = normalize_accent(
            getattr(self.config, "accent_color", DEFAULT_ACCENT)
        )
        self.accent_selector = QComboBox()
        for preset_name, preset_color in ACCENT_PRESETS:
            self.accent_selector.addItem(preset_name, preset_color)
        self.accent_selector.addItem("Custom", "custom")
        accent_index = self.accent_selector.findData(self.custom_accent)
        if accent_index < 0:
            accent_index = self.accent_selector.findData("custom")
        self.accent_selector.setCurrentIndex(accent_index)
        self.choose_accent_button = QPushButton("Choose custom color")
        self.choose_accent_button.clicked.connect(self.choose_custom_accent)
        self.accent_preview = QLabel()
        self.accent_preview.setObjectName("accentPreview")
        self.accent_preview.setFixedSize(44, 28)
        accent_row = QHBoxLayout()
        accent_row.addWidget(self.accent_selector)
        accent_row.addWidget(self.choose_accent_button)
        accent_row.addWidget(self.accent_preview)
        accent_row.addStretch()
        self.accent_selector.currentIndexChanged.connect(self._update_accent_preview)
        appearance_form.addRow("Theme", self.theme_selector)
        appearance_form.addRow("Button and highlight color", accent_row)
        appearance_note = QLabel(
            "Appearance changes apply when settings are saved and are remembered for the next launch."
        )
        appearance_note.setWordWrap(True)
        appearance_form.addRow(appearance_note)
        layout.addWidget(appearance)
        self._update_accent_preview()

        group = QGroupBox("Creator settings")
        form = QFormLayout(group)
        self.channel = QLineEdit(self.config.channel_name)
        self.timezone = QLineEdit(self.config.timezone)
        self.currency = QComboBox()
        self.currency.addItems(["USD","CAD","GBP","EUR","AUD"])
        self.currency.setCurrentText(self.config.currency)
        self.auto_start = QCheckBox()
        self.auto_start.setChecked(self.config.auto_backup_on_start)
        self.auto_write = QCheckBox()
        self.auto_write.setChecked(self.config.auto_backup_before_write)
        self.retention = QSpinBox()
        self.retention.setRange(1,365)
        self.retention.setValue(self.config.backup_retention)
        form.addRow("Channel name", self.channel)
        form.addRow("Timezone", self.timezone)
        form.addRow("Currency", self.currency)
        form.addRow("Backup when app starts", self.auto_start)
        form.addRow("Backup before imports/writes", self.auto_write)
        form.addRow("Backups to retain", self.retention)
        save = QPushButton("Save settings")
        save.clicked.connect(self.save_settings)
        form.addRow(save)
        layout.addWidget(group)

        updates = QGroupBox("Software updates")
        update_form = QFormLayout(updates)
        update_form.addRow("Installed version", QLabel(APPLICATION_VERSION))
        self.auto_updates = QCheckBox("Check automatically after the installed app starts")
        self.auto_updates.setChecked(self.config.auto_check_updates)
        self.update_channel = QComboBox()
        self.update_channel.addItem("Stable releases", "stable")
        self.update_channel.addItem("Preview releases", "preview")
        channel_index = self.update_channel.findData(self.config.update_channel)
        self.update_channel.setCurrentIndex(max(0, channel_index))
        self.update_status = QLabel(
            "Automatic checks use GitHub Releases once per day and never block startup."
        )
        self.update_status.setWordWrap(True)
        update_actions = QHBoxLayout()
        self.check_update_button = QPushButton("Check now")
        self.check_update_button.clicked.connect(self.check_updates)
        self.open_update_button = QPushButton("View release")
        self.open_update_button.clicked.connect(self.open_update)
        set_button_enabled(
            self.open_update_button, False, "Check for updates to find a release."
        )
        self.download_update_button = QPushButton("Download verified installer")
        self.download_update_button.clicked.connect(self.download_update)
        set_button_enabled(
            self.download_update_button, False, "Check for updates to find an installer."
        )
        self.skip_update_button = QPushButton("Skip this version")
        self.skip_update_button.clicked.connect(self.skip_update)
        set_button_enabled(
            self.skip_update_button, False, "Check for updates to find a version to skip."
        )
        update_actions.addWidget(self.check_update_button)
        update_actions.addWidget(self.open_update_button)
        update_actions.addWidget(self.download_update_button)
        update_actions.addWidget(self.skip_update_button)
        update_actions.addStretch()
        update_form.addRow("Automatic checks", self.auto_updates)
        update_form.addRow("Update channel", self.update_channel)
        update_form.addRow("Status", self.update_status)
        update_form.addRow(update_actions)
        layout.addWidget(updates)

        runtime = QGroupBox("Local processing setup")
        runtime_form = QFormLayout(runtime)
        self.runtime_status = QLabel(); self.runtime_status.setWordWrap(True)
        runtime_button = QPushButton("Open Setup Once")
        runtime_button.clicked.connect(self.open_runtime_setup)
        runtime_form.addRow("Status", self.runtime_status)
        runtime_form.addRow(runtime_button)
        layout.addWidget(runtime)
        self.refresh_runtime_status()

        buttons = QHBoxLayout()
        backup = QPushButton("Create database backup")
        backup.clicked.connect(self.make_backup)
        health = QPushButton("Run startup health checks")
        health.clicked.connect(self.run_health)
        onboarding = QPushButton("Open welcome and workspace setup")
        onboarding.clicked.connect(self.open_onboarding)
        buttons.addWidget(backup)
        buttons.addWidget(health)
        buttons.addWidget(onboarding)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.health_table = QTableWidget(0,3)
        self.health_table.setHorizontalHeaderLabels(["Check","Status","Details"])
        self.health_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.health_table)
        self.run_health()

    def save_settings(self):
        self.config.channel_name = self.channel.text().strip() or "My Channel"
        self.config.timezone = self.timezone.text().strip() or "America/Chicago"
        self.config.currency = self.currency.currentText()
        self.config.theme = str(self.theme_selector.currentData())
        self.config.accent_color = self._selected_accent()
        self.config.auto_backup_on_start = self.auto_start.isChecked()
        self.config.auto_backup_before_write = self.auto_write.isChecked()
        self.config.backup_retention = self.retention.value()
        self.config.auto_check_updates = self.auto_updates.isChecked()
        self.config.update_channel = str(self.update_channel.currentData())
        self.config_service.save(self.config)
        if self.update_checker:
            self.update_checker.set_channel(self.config.update_channel)
        self.backups.retention = self.config.backup_retention
        self.appearance_changed.emit(self.config.theme, self.config.accent_color)
        QMessageBox.information(self,"Saved","Settings were saved.")

    def _selected_accent(self) -> str:
        selected = str(self.accent_selector.currentData())
        return self.custom_accent if selected == "custom" else normalize_accent(selected)

    def _update_accent_preview(self, _index=None) -> None:
        color = self._selected_accent()
        self.accent_preview.setStyleSheet(
            f"background-color: {color}; border-radius: 6px; min-width: 44px; min-height: 28px;"
        )

    def choose_custom_accent(self) -> None:
        selected = QColorDialog.getColor(
            QColor(self.custom_accent), self, "Choose interface accent color"
        )
        if not selected.isValid():
            return
        self.custom_accent = selected.name().lower()
        custom_index = self.accent_selector.findData("custom")
        self.accent_selector.setItemText(custom_index, f"Custom ({self.custom_accent})")
        self.accent_selector.setCurrentIndex(custom_index)
        self._update_accent_preview()

    def make_backup(self):
        path = self.backups.create("manual")
        QMessageBox.information(self,"Backup complete",f"Created:\n{path}")

    def run_health(self):
        checks = HealthService(self.database_path).run()
        self.health_table.setRowCount(len(checks))
        for row, check in enumerate(checks):
            values = [check.name, "PASS" if check.ok else "FAIL", check.message]
            for col, value in enumerate(values):
                self.health_table.setItem(row,col,QTableWidgetItem(value))

    def open_onboarding(self):
        if not self.onboarding:
            QMessageBox.information(self,"Welcome setup","Restart the application to open first-run setup.")
            return
        from creator_intelligence.ui.dialogs.onboarding import OnboardingWizard
        OnboardingWizard(self.onboarding,self).exec()

    def refresh_runtime_status(self):
        if not self.runtime_setup:
            self.runtime_status.setText("Runtime setup is unavailable in this session.")
            return
        result = self.runtime_setup.status()
        missing = [component.name for component in result.components if not component.ready]
        self.runtime_status.setText(
            "All local processing components are ready."
            if not missing else "Setup needed: " + ", ".join(missing)
        )

    def open_runtime_setup(self):
        if not self.runtime_setup:
            QMessageBox.information(self, "Setup Once", "Runtime setup is unavailable in this session.")
            return
        from creator_intelligence.ui.dialogs.runtime_setup import RuntimeSetupDialog

        RuntimeSetupDialog(self.runtime_setup, self).exec()
        self.refresh_runtime_status()

    def check_updates(self):
        if not self.update_checker:
            self.update_status.setText("Update checking is unavailable in this session.")
            return
        if self.update_worker is not None and self.update_worker.running:
            return
        self.update_checker.set_channel(str(self.update_channel.currentData()))
        self.update_status.setText("Checking GitHub Releases…")
        set_button_enabled(
            self.check_update_button, False, "An update check is already running."
        )
        self.update_worker = UpdateCheckWorker(self.update_checker, force=True, parent=self)
        self.update_worker.result_ready.connect(self._update_check_finished)
        self.update_worker.start()

    def _update_check_finished(self, result):
        set_button_enabled(self.check_update_button, True)
        self.update_status.setText(result.message)
        self.update_release = result.release if result.status == UpdateStatus.AVAILABLE else None
        available = self.update_release is not None
        set_button_enabled(
            self.open_update_button, available, "No newer release was found."
        )
        set_button_enabled(
            self.skip_update_button, available, "No newer version is available to skip."
        )
        packaged_download = available and bool(
            self.update_checker and self.update_checker.packaged
        )
        set_button_enabled(
            self.download_update_button,
            packaged_download,
            "Verified installer downloads are available in the installed Windows app."
            if available else "No newer installer was found.",
        )
        if available and self.update_checker and not self.update_checker.packaged:
            self.download_update_button.setToolTip(
                "Verified installer downloads are available in the installed Windows app."
            )

    def open_update(self):
        url = self.update_release.page_url if self.update_release else RELEASES_PAGE_URL
        QDesktopServices.openUrl(QUrl(url))

    def skip_update(self):
        if not self.update_checker or not self.update_release:
            return
        if self.update_checker.skip(self.update_release.version):
            self.update_status.setText(f"Version {self.update_release.version} will be skipped.")
            set_button_enabled(
                self.skip_update_button, False, "This version is already being skipped."
            )
        else:
            self.update_status.setText("The skip preference could not be saved.")

    def download_update(self):
        if not self.update_checker or not self.update_release:
            return
        if self.download_worker is not None and self.download_worker.running:
            return
        set_button_enabled(
            self.download_update_button, False, "The installer is downloading now."
        )
        self.update_status.setText("Downloading and verifying the installer…")
        self.download_worker = UpdateDownloadWorker(
            self.update_checker, self.update_release, parent=self
        )
        self.download_worker.download_ready.connect(self._download_finished)
        self.download_worker.download_failed.connect(self._download_failed)
        self.download_worker.start()

    def _download_finished(self, path):
        self.update_status.setText(f"Verified installer downloaded: {path.name}")
        set_button_enabled(self.download_update_button, True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        QMessageBox.information(
            self,
            "Update ready",
            "The installer passed its SHA-256 check. The folder is open so you can run it when ready.",
        )

    def _download_failed(self, message):
        self.update_status.setText("The installer could not be downloaded and verified.")
        set_button_enabled(self.download_update_button, True)
        QMessageBox.warning(self, "Update download", message)
