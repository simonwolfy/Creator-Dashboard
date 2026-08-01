from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFormLayout,
    QSpinBox,QCheckBox,QPlainTextEdit,QMessageBox
)

class WatcherPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service=service
        layout=QVBoxLayout(self)
        title=QLabel("Background Import Watcher")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        form=QFormLayout()
        self.enabled=QCheckBox()
        self.interval=QSpinBox()
        self.interval.setRange(10,86400)
        self.interval.setSuffix(" seconds")
        self.auto_commit=QCheckBox()
        form.addRow("Enabled",self.enabled)
        form.addRow("Scan interval",self.interval)
        form.addRow("Automatically commit valid imports",self.auto_commit)
        layout.addLayout(form)

        row=QHBoxLayout()
        save=QPushButton("Save settings"); save.clicked.connect(self.save)
        start=QPushButton("Start watcher"); start.clicked.connect(self.start)
        stop=QPushButton("Stop watcher"); stop.clicked.connect(self.stop)
        run=QPushButton("Run one scan now"); run.clicked.connect(self.run_cycle)
        row.addWidget(save); row.addWidget(start); row.addWidget(stop); row.addWidget(run)
        row.addStretch()
        layout.addLayout(row)

        self.status=QPlainTextEdit()
        self.status.setReadOnly(True)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self):
        settings=self.service.settings()
        self.enabled.setChecked(settings.enabled)
        self.interval.setValue(settings.interval_seconds)
        self.auto_commit.setChecked(settings.auto_commit)
        state=self.service.status()
        self.status.setPlainText(
            "\n".join(f"{key}: {value}" for key,value in state.items())
        )

    def save(self):
        self.service.update_settings(
            enabled=self.enabled.isChecked(),
            interval_seconds=self.interval.value(),
            auto_commit=self.auto_commit.isChecked()
        )
        self.refresh()

    def start(self):
        self.save()
        started=self.service.start()
        QMessageBox.information(
            self,"Watcher",
            "Background watcher started." if started else
            "Watcher was already running or is disabled."
        )
        self.refresh()

    def stop(self):
        self.service.stop()
        self.refresh()

    def run_cycle(self):
        results=self.service.run_cycle()
        QMessageBox.information(
            self,"Scan complete",
            f"{len(results)} file or folder results were processed."
        )
        self.refresh()
