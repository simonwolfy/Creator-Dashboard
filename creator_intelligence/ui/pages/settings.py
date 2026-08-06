from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QMessageBox,QFormLayout,
    QLineEdit,QComboBox,QCheckBox,QSpinBox,QGroupBox,QTableWidget,QTableWidgetItem
)
from creator_intelligence.services.backup import BackupService
from creator_intelligence.core.config import ConfigService
from creator_intelligence.core.health import HealthService
from creator_intelligence.utils.paths import DB_PATH, BACKUP_DIR

class SettingsPage(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.config_service = ConfigService()
        self.config = self.config_service.load()
        self.backups = BackupService(DB_PATH, BACKUP_DIR, self.config.backup_retention)

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
        buttons.addWidget(backup)
        buttons.addWidget(health)
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
        checks = HealthService(DB_PATH).run()
        self.health_table.setRowCount(len(checks))
        for row, check in enumerate(checks):
            values = [check.name, "PASS" if check.ok else "FAIL", check.message]
            for col, value in enumerate(values):
                self.health_table.setItem(row,col,QTableWidgetItem(value))
