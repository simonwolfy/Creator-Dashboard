import logging
from PySide6.QtWidgets import QMainWindow,QWidget,QHBoxLayout,QListWidget,QStackedWidget,QStatusBar,QLabel,QVBoxLayout
from PySide6.QtCore import QSize

log = logging.getLogger(__name__)

STYLE = """
QMainWindow,QWidget { background:#0d1018; color:#eef1ff; font-size:13px; }
QListWidget { background:#131827; border:none; padding:10px; font-size:15px; }
QListWidget::item { padding:13px; border-radius:8px; }
QListWidget::item:selected { background:#6f36c9; }
QPushButton { background:#7137c8; border:none; padding:9px 14px; border-radius:7px; font-weight:600; }
QPushButton:hover { background:#8248d8; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QDateEdit,QDateTimeEdit,QPlainTextEdit {
 background:#171d2d; border:1px solid #333d5d; padding:7px; border-radius:6px;
}
QTableView,QTableWidget { background:#121725; gridline-color:#29314b; alternate-background-color:#171d2d; }
QHeaderView::section { background:#202841; padding:7px; border:none; }
QGroupBox { border:1px solid #303a5e; border-radius:8px; margin-top:8px; padding-top:12px; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; }
#pageTitle { font-size:27px; font-weight:700; padding:8px 0 14px 0; }
#metricCard { background:#151b2d; border:1px solid #303a5e; border-radius:12px; padding:8px; }
#metricTitle { color:#abb4d5; font-weight:600; }
#metricValue { font-size:24px; font-weight:700; }
#metricSubtitle { color:#8993b4; }
"""

class ModuleFailurePage(QWidget):
    def __init__(self, label, error):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel(f"{label} could not be loaded")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        message = QLabel(str(error))
        message.setWordWrap(True)
        layout.addWidget(message)
        layout.addStretch()

class MainWindow(QMainWindow):
    def __init__(self, runtime, application_core=None):
        super().__init__()
        self.runtime = runtime
        self.application_core = application_core
        self.db = runtime.db
        self.context = runtime.context
        self.registry = runtime.registry
        self.setWindowTitle("Creator Intelligence 5.0 — Creator OS")
        self.resize(1600,960)
        self.setMinimumSize(QSize(1180,740))
        self.setStyleSheet(STYLE)

        container=QWidget()
        layout=QHBoxLayout(container)
        layout.setContentsMargins(0,0,0,0)
        nav=QListWidget()
        nav.setFixedWidth(245)
        stack=QStackedWidget()

        for item in self.registry.build_navigation():
            try:
                page = item.factory()
            except Exception as exc:
                log.exception("Failed to create page %s", item.label)
                page = ModuleFailurePage(item.label, exc)
            nav.addItem(item.label)
            stack.addWidget(page)

        if nav.count() == 0:
            nav.addItem("No modules")
            stack.addWidget(ModuleFailurePage(
                "Application modules",
                "No application modules loaded. Check config/modules.json and the logs."
            ))

        nav.currentRowChanged.connect(stack.setCurrentIndex)
        nav.setCurrentRow(0)
        layout.addWidget(nav)
        layout.addWidget(stack,1)
        self.setCentralWidget(container)

        status=QStatusBar()
        loaded = len(self.registry.modules)
        failed = len(self.registry.failures)
        health_issues = len([check for check in runtime.health_checks if not check.ok])
        status.showMessage(
            f"Workspace: {runtime.workspace.paths.root} | "
            f"Modules: {loaded} | Failed: {failed} | Health issues: {health_issues}"
        )
        self.setStatusBar(status)

    def closeEvent(self,event):
        if self.application_core is not None:
            try:
                self.application_core.stop()
            except Exception:
                log.exception("Application shutdown pipeline failed")
        else:
            self.registry.emit("application_closing")
        log.info("Application closed normally")
        event.accept()
