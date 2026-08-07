import logging

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    orderChanged = Signal()

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(17)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def drop_destination(self, item: QTreeWidgetItem, target, position):
        above = QAbstractItemView.DropIndicatorPosition.AboveItem
        below = QAbstractItemView.DropIndicatorPosition.BelowItem
        on_item = QAbstractItemView.DropIndicatorPosition.OnItem
        on_viewport = QAbstractItemView.DropIndicatorPosition.OnViewport

        parent = item.parent()
        if parent is None:
            if target is None and position == on_viewport:
                return None, self.topLevelItemCount()
            if target is None or target.parent() is not None:
                return None
            target_index = self.indexOfTopLevelItem(target)
            if position == above:
                return None, target_index
            if position == below:
                return None, target_index + 1
            return None

        if target is parent and position == on_item:
            return parent, parent.childCount()
        if target is None or target.parent() is not parent:
            return None
        target_index = parent.indexOfChild(target)
        if position == above:
            return parent, target_index
        if position == below:
            return parent, target_index + 1
        return None

    def dropEvent(self, event) -> None:
        item = self.currentItem()
        if item is None:
            event.ignore()
            return
        original_parent = item.parent()
        original_index = (
            self.indexOfTopLevelItem(item)
            if original_parent is None
            else original_parent.indexOfChild(item)
        )

        destination = self.drop_destination(
            item,
            self.itemAt(event.position().toPoint()),
            self.dropIndicatorPosition(),
        )
        if destination is None:
            event.ignore()
            return

        destination_parent, destination_index = destination
        if original_parent is None:
            self.takeTopLevelItem(original_index)
            if original_index < destination_index:
                destination_index -= 1
            self.insertTopLevelItem(destination_index, item)
        else:
            original_parent.takeChild(original_index)
            if original_index < destination_index:
                destination_index -= 1
            destination_parent.insertChild(destination_index, item)
        self.setCurrentItem(item)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.orderChanged.emit()


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
        injected_settings = getattr(runtime, "ui_settings", None)
        self.settings = (
            injected_settings
            if injected_settings is not None
            else QSettings("Creator Intelligence", "Creator OS")
        )
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

        default_groups = [group for group in NAVIGATION_GROUP_ORDER if group in grouped_navigation]
        default_groups.extend(sorted(set(grouped_navigation) - set(default_groups)))
        saved_groups = self.settings.value("navigation/group_order", [], list)
        legacy_item_order = self.settings.value("navigation/order", [], list)
        saved_group_positions = {
            str(group): index for index, group in enumerate(saved_groups)
        }
        for group_name in sorted(
            default_groups,
            key=lambda group: (
                saved_group_positions.get(group, len(saved_group_positions) + default_groups.index(group))
            ),
        ):
            group_item = self._add_navigation_group(group_name)
            item_order_key = f"navigation/item_order/{group_name}"
            saved_items = (
                self.settings.value(item_order_key, [], list)
                if self.settings.contains(item_order_key)
                else legacy_item_order
            )
            saved_item_positions = {
                str(key): index for index, key in enumerate(saved_items)
            }
            for item in sorted(
                grouped_navigation[group_name],
                key=lambda entry: (
                    saved_item_positions.get(
                        self._navigation_key(entry),
                        len(saved_item_positions) + entry.order,
                    ),
                    entry.order,
                    entry.label.lower(),
                ),
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
        self.nav.orderChanged.connect(self._navigation_reordered)
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
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        self.nav.addTopLevelItem(item)
        return item

    @staticmethod
    def _add_navigation_item(parent: QTreeWidgetItem, label: str, key: str):
        item = QTreeWidgetItem([label])
        item.setData(0, NAV_KEY_ROLE, key)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
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

    def _navigation_reordered(self) -> None:
        group_order = []
        for index in range(self.nav.topLevelItemCount()):
            group = self.nav.topLevelItem(index)
            group_name = str(group.data(0, NAV_GROUP_ROLE))
            group_order.append(group_name)
            item_order = [
                str(group.child(child_index).data(0, NAV_KEY_ROLE))
                for child_index in range(group.childCount())
            ]
            self.settings.setValue(f"navigation/item_order/{group_name}", item_order)
        self.settings.setValue("navigation/group_order", group_order)
        self._save_navigation_state()

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
