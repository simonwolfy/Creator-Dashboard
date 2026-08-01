import logging

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

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

NAV_KEY_ROLE = Qt.ItemDataRole.UserRole


class ReorderableNavigation(QListWidget):
    orderChanged = Signal()

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.orderChanged.emit()


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
        self.settings = QSettings("Creator Intelligence", "Creator OS")
        self.setWindowTitle("Creator Intelligence 5.0 — Creator OS")
        self.resize(1600, 960)
        self.setMinimumSize(QSize(1180, 740))
        self.setStyleSheet(STYLE)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.nav = ReorderableNavigation()
        self.nav.setFixedWidth(245)
        self.stack = QStackedWidget()
        self.pages_by_key: dict[str, QWidget] = {}

        navigation = list(self.registry.build_navigation())
        saved_order = self.settings.value("navigation/order", [], list)
        saved_positions = {key: index for index, key in enumerate(saved_order)}
        navigation.sort(
            key=lambda item: (
                saved_positions.get(self._navigation_key(item), len(saved_positions) + item.order),
                item.order,
                item.label,
            )
        )

        for item in navigation:
            key = self._navigation_key(item)
            try:
                page = item.factory()
            except Exception as exc:
                log.exception("Failed to create page %s", item.label)
                page = ModuleFailurePage(item.label, exc)
            nav_item = self._add_navigation_item(item.label, key)
            self.pages_by_key[key] = page
            self.stack.addWidget(page)

        if self.nav.count() == 0:
            page = ModuleFailurePage(
                "Application modules",
                "No application modules loaded. Check config/modules.json and the logs.",
            )
            self._add_navigation_item("No modules", "system:no-modules")
            self.pages_by_key["system:no-modules"] = page
            self.stack.addWidget(page)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.orderChanged.connect(self._navigation_reordered)
        self.nav.setCurrentRow(0)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(container)

        status = QStatusBar()
        loaded = len(self.registry.modules)
        failed = len(self.registry.failures)
        health_issues = len([check for check in runtime.health_checks if not check.ok])
        status.showMessage(
            f"Workspace: {runtime.workspace.paths.root} | "
            f"Modules: {loaded} | Failed: {failed} | Health issues: {health_issues}"
        )
        self.setStatusBar(status)

    @staticmethod
    def _navigation_key(item) -> str:
        return str(item.module_id or f"label:{item.label}")

    def _add_navigation_item(self, label: str, key: str):
        self.nav.addItem(label)
        item = self.nav.item(self.nav.count() - 1)
        item.setData(NAV_KEY_ROLE, key)
        return item

    def _navigation_reordered(self) -> None:
        current_item = self.nav.currentItem()
        current_key = current_item.data(NAV_KEY_ROLE) if current_item else None
        ordered_keys = [
            str(self.nav.item(index).data(NAV_KEY_ROLE))
            for index in range(self.nav.count())
        ]

        for key in ordered_keys:
            page = self.pages_by_key.get(key)
            if page is not None:
                self.stack.removeWidget(page)
                self.stack.addWidget(page)

        self.settings.setValue("navigation/order", ordered_keys)
        if current_key in ordered_keys:
            row = ordered_keys.index(current_key)
            self.nav.setCurrentRow(row)
            self.stack.setCurrentIndex(row)

    def closeEvent(self, event):
        if self.application_core is not None:
            try:
                self.application_core.stop()
            except Exception:
                log.exception("Application shutdown pipeline failed")
        else:
            self.registry.emit("application_closing")
        log.info("Application closed normally")
        event.accept()
