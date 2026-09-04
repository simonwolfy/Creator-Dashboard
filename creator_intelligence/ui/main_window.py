import logging
from html import escape

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QTextBrowser,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.core.versioning import APPLICATION_VERSION
from creator_intelligence.services.update_checker import UpdateStatus
from creator_intelligence.ui.page_help import (
    CATEGORY_ORDER,
    help_for_page,
    navigation_category,
)
from creator_intelligence.ui.release_notes import CURRENT_RELEASE_NOTES, NOTES_REVISION
from creator_intelligence.ui.update_worker import UpdateCheckWorker, UpdateDownloadWorker

log = logging.getLogger(__name__)

STYLE = """
QMainWindow,QWidget { background:#0d1018; color:#eef1ff; font-size:14px; }
QTreeWidget { background:#131827; border:none; padding:8px; font-size:14px; outline:none; }
QTreeWidget::item { min-height:30px; padding:3px 5px; border-radius:7px; }
QTreeWidget::item:selected { background:#6f36c9; color:#ffffff; }
QPushButton { background:#7137c8; border:none; padding:9px 14px; min-height:20px; border-radius:7px; font-weight:600; }
QPushButton:hover { background:#8248d8; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QDateEdit,QDateTimeEdit,QPlainTextEdit {
 background:#171d2d; border:1px solid #333d5d; padding:7px; min-height:20px; border-radius:6px;
}
QLabel { min-height:18px; }
QCheckBox { min-height:22px; spacing:7px; }
QTabBar::tab { min-height:22px; padding:8px 12px; }
QTableView,QTableWidget { background:#121725; gridline-color:#29314b; alternate-background-color:#171d2d; font-size:13px; }
QHeaderView::section { background:#202841; padding:8px; min-height:22px; border:none; font-weight:600; }
QGroupBox { border:1px solid #303a5e; border-radius:8px; margin-top:8px; padding-top:12px; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; }
#pageTitle { font-size:27px; font-weight:700; min-height:38px; padding:8px 0 14px 0; }
#metricCard { background:#151b2d; border:1px solid #303a5e; border-radius:12px; padding:8px; }
#metricTitle { color:#abb4d5; font-weight:600; }
#metricValue { font-size:24px; font-weight:700; }
#metricSubtitle { color:#8993b4; }
#sidebarToggle { background:#171d2d; border:1px solid #384362; text-align:left; }
#pageHelpButton { background:#7137c8; color:white; border-radius:15px; font-size:17px; font-weight:700; }
#pageHelpButton:hover { background:#8248d8; }
"""

NAV_KEY_ROLE = Qt.ItemDataRole.UserRole


class GroupedNavigation(QWidget):
    pageSelected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(272)
        self._expanded_width = 272
        self._groups: dict[str, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        self.toggle = QPushButton("◀  Collapse navigation")
        self.toggle.setObjectName("sidebarToggle")
        self.toggle.clicked.connect(self.toggle_collapsed)
        layout.addWidget(self.toggle)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(17)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.tree, 1)

    def add_page(self, category: str, label: str, key: str) -> QTreeWidgetItem:
        group = self._groups.get(category)
        if group is None:
            group = QTreeWidgetItem([category])
            font = QFont()
            font.setBold(True)
            group.setFont(0, font)
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(group)
            self._groups[category] = group
        item = QTreeWidgetItem([label])
        item.setData(0, NAV_KEY_ROLE, key)
        group.addChild(item)
        group.setExpanded(True)
        return item

    def select_first_page(self) -> None:
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            if group.childCount():
                self.tree.setCurrentItem(group.child(0))
                return

    def toggle_collapsed(self) -> None:
        collapsed = self.tree.isVisible()
        self.tree.setVisible(not collapsed)
        self.setFixedWidth(46 if collapsed else self._expanded_width)
        self.toggle.setText("▶" if collapsed else "◀  Collapse navigation")
        self.toggle.setToolTip("Expand navigation" if collapsed else "Collapse navigation")

    def _selection_changed(self) -> None:
        item = self.tree.currentItem()
        key = item.data(0, NAV_KEY_ROLE) if item is not None else None
        if key:
            self.pageSelected.emit(str(key))


class GuidedPage(QWidget):
    helpRequested = Signal(str)

    def __init__(self, key: str, page: QWidget):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        help_row = QHBoxLayout()
        help_row.addStretch()
        button = QToolButton()
        button.setObjectName("pageHelpButton")
        button.setText("?")
        button.setFixedSize(30, 30)
        button.setToolTip("What does this page do?")
        button.setAccessibleName("Page help")
        button.clicked.connect(lambda: self.helpRequested.emit(key))
        help_row.addWidget(button)
        layout.addLayout(help_row)
        layout.addWidget(page, 1)


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
        self.setWindowTitle(f"Creator Intelligence {APPLICATION_VERSION} — Creator OS")
        self.resize(1600, 960)
        self.setMinimumSize(QSize(1180, 740))
        self.setStyleSheet(STYLE)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.nav = GroupedNavigation()
        self.stack = QStackedWidget()
        self.pages_by_key: dict[str, QWidget] = {}
        self.page_help_by_key: dict[str, tuple[str, str, str]] = {}

        navigation = list(self.registry.build_navigation())
        category_positions = {category: index for index, category in enumerate(CATEGORY_ORDER)}
        navigation.sort(
            key=lambda item: (
                category_positions[navigation_category(item.label, item.module_id)],
                item.order,
                item.label,
            )
        )

        for item in navigation:
            key = self._navigation_key(item)
            category = navigation_category(item.label, item.module_id)
            module_id = str(item.module_id or "").split(":", 1)[0]
            metadata = self.registry.modules.get(module_id)
            description = metadata.description if metadata is not None else ""
            try:
                page = item.factory()
            except Exception as exc:
                log.exception("Failed to create page %s", item.label)
                page = ModuleFailurePage(item.label, exc)
            guided_page = GuidedPage(key, page)
            guided_page.helpRequested.connect(self._show_page_help)
            self.nav.add_page(category, item.label, key)
            self.pages_by_key[key] = guided_page
            self.page_help_by_key[key] = (item.label, category, description)
            self.stack.addWidget(guided_page)

        if not self.pages_by_key:
            page = ModuleFailurePage(
                "Application modules",
                "No application modules loaded. Check config/modules.json and the logs.",
            )
            key = "system:no-modules"
            guided_page = GuidedPage(key, page)
            guided_page.helpRequested.connect(self._show_page_help)
            self.nav.add_page("System", "No modules", key)
            self.pages_by_key[key] = guided_page
            self.page_help_by_key[key] = (
                "No modules", "System", "Diagnose why application modules did not load."
            )
            self.stack.addWidget(guided_page)

        self.nav.pageSelected.connect(self._show_navigation_page)
        self.nav.select_first_page()
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

        if str(self.settings.value("updates/last_notes_revision", "")) != NOTES_REVISION:
            QTimer.singleShot(700, self._show_release_notes)

        self.update_checker = self.context.services.get("update_checker")
        self._update_worker = None
        self._update_download_worker = None
        if (
            self.update_checker is not None
            and getattr(runtime.settings, "auto_check_updates", True)
            and self.update_checker.should_check()
        ):
            QTimer.singleShot(2500, self._start_automatic_update_check)

    def _start_automatic_update_check(self) -> None:
        if self._update_worker is not None and self._update_worker.running:
            return
        self._update_worker = UpdateCheckWorker(self.update_checker, force=False, parent=self)
        self._update_worker.result_ready.connect(self._handle_automatic_update_result)
        self._update_worker.start()

    def _handle_automatic_update_result(self, result) -> None:
        if result.status != UpdateStatus.AVAILABLE or result.release is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Creator Intelligence update available")
        box.setText(f"Version {result.release.version} is ready.")
        size = (
            f" ({result.release.installer_size / 1024**2:.1f} MB)"
            if result.release.installer_size else ""
        )
        notes = result.release.notes[:800]
        box.setInformativeText(
            f"Verified Windows installer{size}. Your workspace stays in its current location."
            + (f"\n\n{notes}" if notes else "")
        )
        download_button = box.addButton("Download update", QMessageBox.ButtonRole.AcceptRole)
        view_button = box.addButton("View release", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        skip_button = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is download_button:
            self._download_update(result.release)
        elif box.clickedButton() is view_button:
            QDesktopServices.openUrl(QUrl(result.release.page_url))
        elif box.clickedButton() is skip_button:
            self.update_checker.skip(result.release.version)

    def _download_update(self, release) -> None:
        if self._has_active_processing():
            QMessageBox.information(
                self, "Update postponed",
                "Content processing is active. Finish or cancel those jobs before downloading an update.",
            )
            return
        if self._update_download_worker is not None and self._update_download_worker.running:
            return
        self.statusBar().showMessage("Downloading and verifying the Creator Intelligence update…")
        self._update_download_worker = UpdateDownloadWorker(
            self.update_checker, release, parent=self
        )
        self._update_download_worker.download_ready.connect(self._update_download_ready)
        self._update_download_worker.download_failed.connect(self._update_download_failed)
        self._update_download_worker.start()

    def _update_download_ready(self, path) -> None:
        self.statusBar().showMessage(f"Verified update ready: {path.name}")
        answer = QMessageBox.question(
            self, "Install verified update?",
            "The installer passed its SHA-256 verification. Close Creator Intelligence "
            "and start the installer now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                self.close()
            else:
                QMessageBox.warning(self, "Update installer", "Windows could not start the installer.")

    def _update_download_failed(self, message) -> None:
        self.statusBar().showMessage("The update could not be downloaded and verified.")
        QMessageBox.warning(self, "Update download", message)

    def _has_active_processing(self) -> bool:
        tables = {
            "content_analysis_jobs": ("Queued", "Running", "Retrying"),
            "transcript_jobs": ("Queued", "Running"),
            "media_processing_jobs": ("Queued", "Running"),
            "scene_analysis_jobs": ("Queued", "Running"),
        }
        existing = set(self.db.frame(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )["name"].astype(str))
        for table, statuses in tables.items():
            if table not in existing:
                continue
            placeholders = ",".join("?" for _ in statuses)
            active = self.db.frame(
                f"SELECT COUNT(*) AS count FROM {table} WHERE status IN ({placeholders})",
                statuses,
            )
            if not active.empty and int(active.iloc[0]["count"]) > 0:
                return True
        return False

    @staticmethod
    def _navigation_key(item) -> str:
        # A module may expose multiple pages, so module_id alone is not unique.
        module = str(item.module_id or "unowned")
        return f"{module}:{item.label}"

    def _show_navigation_page(self, key: str) -> None:
        page = self.pages_by_key.get(str(key))
        if page is not None:
            self.stack.setCurrentWidget(page)

    def _show_page_help(self, key: str) -> None:
        label, category, description = self.page_help_by_key[key]
        content = help_for_page(label, category, description)
        steps = "".join(
            f"<li style='margin-bottom:8px'>{escape(step)}</li>" for step in content.steps
        )
        self._show_information_dialog(
            f"{label} help",
            (
                f"<h2>{escape(label)}</h2>"
                f"<p><b>What it does</b></p><p>{escape(content.purpose)}</p>"
                f"<p><b>First-time steps</b></p><ol>{steps}</ol>"
                "<p>You can reopen this guide at any time with the <b>?</b> button.</p>"
            ),
        )

    def _show_release_notes(self) -> None:
        self.settings.setValue("updates/last_notes_revision", NOTES_REVISION)
        self.settings.setValue("updates/last_seen_version", APPLICATION_VERSION)
        self.settings.sync()
        notes = "".join(
            f"<li style='margin-bottom:9px'>{escape(note)}</li>"
            for note in CURRENT_RELEASE_NOTES
        )
        self._show_information_dialog(
            f"What’s new in Creator Intelligence {APPLICATION_VERSION}",
            (
                f"<h2>What’s new in {escape(APPLICATION_VERSION)}</h2>"
                "<p>This appears once after an updated build is installed.</p>"
                f"<ul>{notes}</ul>"
                "<p>Your existing workspace and creator data remain in their current location.</p>"
            ),
        )

    def _show_information_dialog(self, title: str, html: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(650, 460)
        layout = QVBoxLayout(dialog)
        content = QTextBrowser()
        content.setOpenExternalLinks(True)
        content.setHtml(html)
        layout.addWidget(content)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

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
