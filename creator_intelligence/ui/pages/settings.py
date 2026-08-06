from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QMessageBox,QFormLayout,
    QLineEdit,QComboBox,QCheckBox,QSpinBox,QGroupBox,QTableWidget,QTableWidgetItem
)
from creator_intelligence.services.backup import BackupService
from creator_intelligence.core.config import ConfigService
from creator_intelligence.core.health import HealthService
from creator_intelligence.utils.paths import DB_PATH, BACKUP_DIR

class SettingsPage(QWidget):
    def __init__(self, db, context=None):
        super().__init__()
        self.db = db
        self.context = context
        self.onboarding = context.services.get("onboarding") if context else None
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
        self.config.auto_backup_on_start = self.auto_start.isChecked()
        self.config.auto_backup_before_write = self.auto_write.isChecked()
        self.config.backup_retention = self.retention.value()
        self.config_service.save(self.config)
        self.backups.retention = self.config.backup_retention
        QMessageBox.information(self,"Saved","Settings were saved.")

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
