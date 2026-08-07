import logging

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from creator_intelligence.core.versioning import APPLICATION_VERSION
from creator_intelligence.services.update_checker import UpdateStatus
from creator_intelligence.ui.table_utils import configure_readable_table
from creator_intelligence.ui.theme import build_stylesheet, normalize_accent
from creator_intelligence.ui.update_worker import UpdateCheckWorker

log = logging.getLogger(__name__)

NAV_KEY_ROLE = Qt.ItemDataRole.UserRole
NAV_GROUP_ROLE = Qt.ItemDataRole.UserRole + 1

NAVIGATION_GROUP_ORDER = (
    "Overview",
    "Platforms",
    "Content",
    "Intelligence",
    "Production",
    "System",
)

NAVIGATION_LABEL_GROUPS = {
    "Home": "Overview",
    "Dashboard": "Overview",
    "Live Stream": "Overview",
    "Twitch": "Platforms",
    "YouTube": "Platforms",
    "Instagram": "Platforms",
    "TikTok": "Platforms",
    "Google Drive": "Platforms",
    "Drive Folders": "Platforms",
    "Cross-platform": "Platforms",
    "Asset Library": "Content",
    "Folder Watcher": "Content",
    "Content Pipeline": "Content",
    "Transcripts": "Content",
    "Import Center": "Content",
    "Import Watcher": "Content",
    "Notifications": "Content",
    "Highlights": "Intelligence",
    "Highlight Scoring": "Intelligence",
    "Highlight Learning": "Intelligence",
    "Scene Intelligence": "Intelligence",
    "Visual Scene Detection": "Intelligence",
    "Content Recommendations": "Intelligence",
    "Opportunity & Workload": "Intelligence",
    "Creator Planner": "Intelligence",
    "Creator Intelligence": "Intelligence",
    "Predictions": "Intelligence",
    "Production": "Production",
    "Publishing": "Production",
    "Packaging Review": "Production",
    "Editor Workspace": "Production",
    "Review & Revision": "Production",
    "FFmpeg Manager": "Production",
    "Video Processing": "Production",
    "Video Metadata": "Production",
    "Proxy Engine": "Production",
    "Thumbnail Engine": "Production",
    "Processing Scheduler": "Production",
    "Goals": "System",
    "Data Quality": "System",
    "Modules": "System",
    "Settings": "System",
}


class HierarchicalNavigation(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(17)
        self.setUniformRowHeights(True)


class ModuleFailurePage(QWidget):
    def __init__(self, label, error):
        super().__init__()
        self.error_message = str(error)
        layout = QVBoxLayout(self)
        title = QLabel(f"{label} could not be loaded")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        message = QLabel(self.error_message)
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
        self.theme = str(getattr(runtime.settings, "theme", "dark"))
        self.accent_color = normalize_accent(
            str(getattr(runtime.settings, "accent_color", "#7137c8"))
        )
        self.setStyleSheet(build_stylesheet(self.theme, self.accent_color))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.nav = HierarchicalNavigation()
        self.nav.setFixedWidth(260)
        self.stack = QStackedWidget()
        self.pages_by_key: dict[str, QWidget] = {}

        navigation = list(self.registry.build_navigation())
        grouped_navigation: dict[str, list] = {}
        for item in navigation:
            grouped_navigation.setdefault(self._navigation_group(item), []).append(item)

        known_groups = [group for group in NAVIGATION_GROUP_ORDER if group in grouped_navigation]
        extra_groups = sorted(set(grouped_navigation) - set(known_groups))
        for group_name in [*known_groups, *extra_groups]:
            group_item = self._add_navigation_group(group_name)
            for item in sorted(
                grouped_navigation[group_name], key=lambda entry: (entry.order, entry.label.lower())
            ):
                key = self._navigation_key(item)
                try:
                    page = item.factory()
                except Exception as exc:
                    log.exception("Failed to create page %s", item.label)
                    page = ModuleFailurePage(item.label, exc)
                self._add_navigation_item(group_item, item.label, key)
                self.pages_by_key[key] = page
                self.stack.addWidget(page)
                self._configure_page_tables(page)
                appearance_signal = getattr(page, "appearance_changed", None)
                if appearance_signal is not None:
                    appearance_signal.connect(self.apply_appearance)

        if self.nav.topLevelItemCount() == 0:
            page = ModuleFailurePage(
                "Application modules",
                "No application modules loaded. Check config/modules.json and the logs.",
            )
            group_item = self._add_navigation_group("System")
            self._add_navigation_item(group_item, "No modules", "system:no-modules")
            self.pages_by_key["system:no-modules"] = page
            self.stack.addWidget(page)

        self.nav.currentItemChanged.connect(self._show_current_navigation_page)
        self.nav.itemExpanded.connect(lambda _item: self._save_navigation_state())
        self.nav.itemCollapsed.connect(lambda _item: self._save_navigation_state())
        self._restore_navigation_state()
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

        self.update_checker = self.context.services.get("update_checker")
        self._update_worker = None
        if (
            self.update_checker is not None
            and getattr(runtime.settings, "auto_check_updates", True)
            and self.update_checker.should_check()
        ):
            QTimer.singleShot(1500, self._start_automatic_update_check)

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
        box.setInformativeText(
            "Your workspace stays in its current location. You can view the release, "
            "install it later, or skip this version."
        )
        view_button = box.addButton("View update", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        skip_button = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is view_button:
            QDesktopServices.openUrl(QUrl(result.release.page_url))
        elif box.clickedButton() is skip_button:
            self.update_checker.skip(result.release.version)

    @staticmethod
    def _navigation_key(item) -> str:
        # A module may expose multiple pages, so module_id alone is not unique.
        module = str(item.module_id or "unowned")
        return f"{module}:{item.label}"

    def _navigation_group(self, item) -> str:
        explicit = str(getattr(item, "group", "") or "").strip()
        if explicit:
            return explicit
        if item.label in NAVIGATION_LABEL_GROUPS:
            return NAVIGATION_LABEL_GROUPS[item.label]
        module_id = str(item.module_id or "").split(":", 1)[0]
        metadata = self.registry.modules.get(module_id)
        category = str(getattr(metadata, "category", "system")).lower()
        return {
            "analytics": "Platforms",
            "content": "Content",
            "imports": "Content",
            "media": "Intelligence",
            "intelligence": "Intelligence",
            "ai": "Intelligence",
            "production": "Production",
            "system": "System",
            "storage": "System",
        }.get(category, "System")

    def _add_navigation_group(self, label: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, NAV_GROUP_ROLE, label)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        self.nav.addTopLevelItem(item)
        return item

    @staticmethod
    def _add_navigation_item(parent: QTreeWidgetItem, label: str, key: str):
        item = QTreeWidgetItem([label])
        item.setData(0, NAV_KEY_ROLE, key)
        parent.addChild(item)
        return item

    def _show_current_navigation_page(self, item, _previous=None) -> None:
        key = item.data(0, NAV_KEY_ROLE) if item else None
        page = self.pages_by_key.get(str(key)) if key is not None else None
        if page is not None:
            self.stack.setCurrentWidget(page)
            self.settings.setValue("navigation/current", str(key))
            self.settings.sync()

    def _restore_navigation_state(self) -> None:
        expanded = self.settings.value("navigation/expanded_groups", ["Overview"], list)
        expanded_groups = {str(value) for value in expanded}
        selected_key = str(self.settings.value("navigation/current", ""))
        selected_item = None
        first_item = None
        for index in range(self.nav.topLevelItemCount()):
            group = self.nav.topLevelItem(index)
            group_name = str(group.data(0, NAV_GROUP_ROLE))
            group.setExpanded(group_name in expanded_groups)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if first_item is None:
                    first_item = child
                if str(child.data(0, NAV_KEY_ROLE)) == selected_key:
                    selected_item = child
                    group.setExpanded(True)
        self.nav.setCurrentItem(selected_item or first_item)

    def _save_navigation_state(self) -> None:
        expanded = []
        for index in range(self.nav.topLevelItemCount()):
            group = self.nav.topLevelItem(index)
            if group.isExpanded():
                expanded.append(str(group.data(0, NAV_GROUP_ROLE)))
        self.settings.setValue("navigation/expanded_groups", expanded)
        self.settings.sync()

    @staticmethod
    def _configure_page_tables(page: QWidget) -> None:
        for table in page.findChildren(QTableView):
            configure_readable_table(table)

    def apply_appearance(self, theme: str, accent_color: str) -> None:
        self.theme = str(theme)
        self.accent_color = normalize_accent(accent_color)
        self.setStyleSheet(build_stylesheet(self.theme, self.accent_color))
        self.runtime.settings.theme = self.theme
        self.runtime.settings.accent_color = self.accent_color

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
