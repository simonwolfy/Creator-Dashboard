import logging

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QTableView,
    QToolButton,
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
        self._dragged_item = None

    def startDrag(self, supported_actions) -> None:
        """Keep a stable source item for the whole native drag operation."""
        self._dragged_item = self.currentItem()
        try:
            super().startDrag(supported_actions)
        finally:
            self._dragged_item = None

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
        item = self._dragged_item
        if item is None or item.treeWidget() is not self:
            event.ignore()
            return

        destination = self.drop_destination(
            item,
            self.itemAt(event.position().toPoint()),
            self.dropIndicatorPosition(),
        )
        if destination is None:
            event.ignore()
            return

        # Let QTreeWidget perform the native move. Manually taking and reinserting
        # an item here while accepting MoveAction lets the source-side drag cleanup
        # remove the already-moved item a second time on some Qt/Windows builds.
        super().dropEvent(event)
        if not event.isAccepted() or item.treeWidget() is not self:
            event.ignore()
            return
        self.setCurrentItem(item)
        self.orderChanged.emit()

    def move_item(self, item, destination_parent, destination_index: int) -> bool:
        """Move an item without allowing Qt to discard it between tree owners."""
        original_parent = item.parent()
        if (original_parent is None) != (destination_parent is None):
            return False
        if original_parent is not None and destination_parent is not original_parent:
            return False
        original_index = (
            self.indexOfTopLevelItem(item)
            if original_parent is None
            else original_parent.indexOfChild(item)
        )
        if original_index < 0:
            return False

        original_siblings = self._siblings(original_parent)

        moved_item = (
            self.takeTopLevelItem(original_index)
            if original_parent is None
            else original_parent.takeChild(original_index)
        )
        if moved_item is None:
            return False
        if original_index < destination_index:
            destination_index -= 1

        try:
            if destination_parent is None:
                destination_index = max(
                    0, min(destination_index, self.topLevelItemCount())
                )
                self.insertTopLevelItem(destination_index, moved_item)
            else:
                destination_index = max(
                    0, min(destination_index, destination_parent.childCount())
                )
                destination_parent.insertChild(destination_index, moved_item)
        except Exception:
            self._restore_siblings(original_parent, original_siblings)
            return False

        current_siblings = self._siblings(original_parent)
        if (
            moved_item.treeWidget() is not self
            or len(current_siblings) != len(original_siblings)
            or {id(entry) for entry in current_siblings}
            != {id(entry) for entry in original_siblings}
        ):
            self._restore_siblings(original_parent, original_siblings)
            return False
        self.setCurrentItem(moved_item)
        return True

    def _siblings(self, parent) -> list[QTreeWidgetItem]:
        if parent is None:
            return [self.topLevelItem(index) for index in range(self.topLevelItemCount())]
        return [parent.child(index) for index in range(parent.childCount())]

    def _restore_siblings(self, parent, siblings: list[QTreeWidgetItem]) -> None:
        """Restore the complete level after any failed or incomplete tree move."""
        if parent is None:
            while self.topLevelItemCount():
                self.takeTopLevelItem(0)
            self.addTopLevelItems(siblings)
            return
        while parent.childCount():
            parent.takeChild(0)
        parent.addChildren(siblings)


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
        self.setMinimumSize(QSize(720, 480))
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
        self.navigation_panel = QWidget()
        self.navigation_panel.setObjectName("sidebarPanel")
        navigation_layout = QVBoxLayout(self.navigation_panel)
        navigation_layout.setContentsMargins(6, 6, 6, 6)
        navigation_layout.setSpacing(6)
        self.navigation_toggle = QToolButton()
        self.navigation_toggle.setObjectName("sidebarToggle")
        self.navigation_toggle.clicked.connect(self._toggle_navigation_sidebar)
        navigation_layout.addWidget(self.navigation_toggle)
        navigation_layout.addWidget(self.nav, 1)
        self.stack = QStackedWidget()
        self.content_scroll = QScrollArea()
        self.content_scroll.setObjectName("contentScroll")
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.content_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.content_scroll.setWidget(self.stack)
        self.pages_by_key: dict[str, QWidget] = {}
        self._navigation_catalog: dict[str, tuple[str, str]] = {}

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
                self._navigation_catalog[key] = (group_name, item.label)
                try:
                    page = item.factory()
                except Exception as exc:
                    log.exception("Failed to create page %s", item.label)
                    page = ModuleFailurePage(item.label, exc)
                self._add_navigation_item(group_item, item.label, key)
                self.pages_by_key[key] = page
                self.stack.addWidget(page)
                self._configure_page_tables(page, key)
                appearance_signal = getattr(page, "appearance_changed", None)
                if appearance_signal is not None:
                    appearance_signal.connect(self.apply_appearance)
                navigation_signal = getattr(page, "navigation_requested", None)
                if navigation_signal is not None:
                    navigation_signal.connect(self._open_related_page)

        if self.nav.topLevelItemCount() == 0:
            page = ModuleFailurePage(
                "Application modules",
                "No application modules loaded. Check config/modules.json and the logs.",
            )
            group_item = self._add_navigation_group("System")
            self._add_navigation_item(group_item, "No modules", "system:no-modules")
            self.pages_by_key["system:no-modules"] = page
            self._navigation_catalog["system:no-modules"] = (
                "System",
                "No modules",
            )
            self.stack.addWidget(page)

        self.nav.currentItemChanged.connect(self._show_current_navigation_page)
        self.nav.orderChanged.connect(self._navigation_reordered)
        self.nav.itemExpanded.connect(lambda _item: self._save_navigation_state())
        self.nav.itemCollapsed.connect(lambda _item: self._save_navigation_state())
        self._restore_navigation_state()
        collapsed = self.settings.value(
            "navigation/sidebar_collapsed", False, type=bool
        )
        self._set_navigation_sidebar_collapsed(collapsed, persist=False)
        layout.addWidget(self.navigation_panel)
        layout.addWidget(self.content_scroll, 1)
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
        ):
            QTimer.singleShot(1500, self._start_automatic_update_check)

    def _start_automatic_update_check(self) -> None:
        if self._update_worker is not None and self._update_worker.running:
            return
        self._update_worker = UpdateCheckWorker(
            self.update_checker,
            force=False,
            every_launch=True,
            parent=self,
        )
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
            if hasattr(self, "content_scroll"):
                self.content_scroll.horizontalScrollBar().setValue(0)
                self.content_scroll.verticalScrollBar().setValue(0)
            self.settings.setValue("navigation/current", str(key))
            self.settings.sync()

    def _open_related_page(self, label: str, item_id=None) -> None:
        target_item = None
        for group_index in range(self.nav.topLevelItemCount()):
            group = self.nav.topLevelItem(group_index)
            for item_index in range(group.childCount()):
                item = group.child(item_index)
                if item.text(0) == label:
                    target_item = item
                    group.setExpanded(True)
                    break
            if target_item is not None:
                break
        if target_item is None:
            self.statusBar().showMessage(f"{label} is not available in this workspace.", 5000)
            return
        self.nav.setCurrentItem(target_item)
        page_key = str(target_item.data(0, NAV_KEY_ROLE))
        page = self.pages_by_key.get(page_key)
        method_name = {
            "Transcripts": "open_transcript",
            "Production": "open_project",
            "Publishing": "open_item",
        }.get(label)
        if (
            label == "Publishing"
            and page is not None
            and isinstance(item_id, dict)
            and item_id.get("view") == "package_outcomes"
        ):
            opener = getattr(page, "open_outcomes", None)
            if opener is not None:
                opener(
                    item_id.get("package_id"),
                    prompt_link=bool(item_id.get("prompt_link")),
                )
        elif item_id is not None and page is not None and method_name:
            opener = getattr(page, method_name, None)
            if opener is not None:
                opener(item_id)
        self.statusBar().showMessage(f"Opened {label}.", 3000)

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

    def _toggle_navigation_sidebar(self) -> None:
        self._set_navigation_sidebar_collapsed(not self.sidebar_collapsed)

    def _set_navigation_sidebar_collapsed(
        self, collapsed: bool, *, persist: bool = True
    ) -> None:
        self.sidebar_collapsed = bool(collapsed)
        self.nav.setVisible(not self.sidebar_collapsed)
        if self.sidebar_collapsed:
            self.navigation_panel.setFixedWidth(46)
            self.navigation_toggle.setText("▶")
            self.navigation_toggle.setToolTip("Expand navigation")
            self.navigation_toggle.setAccessibleName("Expand navigation")
        else:
            self.navigation_panel.setFixedWidth(272)
            self.navigation_toggle.setText("◀  Collapse navigation")
            self.navigation_toggle.setToolTip("Collapse navigation")
            self.navigation_toggle.setAccessibleName("Collapse navigation")
        if persist:
            self.settings.setValue(
                "navigation/sidebar_collapsed", self.sidebar_collapsed
            )
            self.settings.sync()

    def _navigation_reordered(self) -> None:
        self._repair_navigation_inventory()
        self._persist_navigation_order()
        # Native drag cleanup finishes after dropEvent returns. Audit once more on
        # the next event-loop turn so a platform or folder can never stay missing.
        QTimer.singleShot(0, self._repair_navigation_after_drop)

    def _persist_navigation_order(self) -> None:
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

    def _repair_navigation_inventory(self) -> list[str]:
        present = set()
        groups: dict[str, QTreeWidgetItem] = {}
        for group_index in range(self.nav.topLevelItemCount()):
            group = self.nav.topLevelItem(group_index)
            group_name = str(group.data(0, NAV_GROUP_ROLE))
            groups[group_name] = group
            for child_index in range(group.childCount()):
                key = group.child(child_index).data(0, NAV_KEY_ROLE)
                if key is not None:
                    present.add(str(key))

        missing = [key for key in self._navigation_catalog if key not in present]
        for key in missing:
            group_name, label = self._navigation_catalog[key]
            group = groups.get(group_name)
            if group is None:
                group = self._add_navigation_group(group_name)
                groups[group_name] = group
            self._add_navigation_item(group, label, key)
        return missing

    def _repair_navigation_after_drop(self) -> None:
        repaired = self._repair_navigation_inventory()
        if not repaired:
            return
        self._persist_navigation_order()
        labels = [self._navigation_catalog[key][1] for key in repaired]
        self.statusBar().showMessage(
            "Restored navigation item(s): " + ", ".join(labels),
            5000,
        )

    def _configure_page_tables(self, page: QWidget, page_key: str) -> None:
        attribute_names = {
            id(value): name
            for name, value in vars(page).items()
            if isinstance(value, QTableView)
        }
        for index, table in enumerate(page.findChildren(QTableView)):
            name = attribute_names.get(id(table), f"table_{index}")
            if not table.objectName():
                table.setObjectName(name)
            label = name.removesuffix("_table").replace("_", " ")
            configure_readable_table(
                table,
                settings=self.settings,
                settings_key=f"{page_key}/{name}",
                empty_text=f"No {label} yet.",
            )

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
