from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QPushButton, QVBoxLayout


class FlowLayout(QLayout):
    """A compact button layout that wraps items as its width changes."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _arrange(self, rect, *, test_only):
        left, top, right, bottom = self.getContentsMargins()
        available = rect.adjusted(left, top, -right, -bottom)
        x = available.x()
        y = available.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self.spacing()
            if line_height and next_x - self.spacing() > available.right() + 1:
                x = available.x()
                y += line_height + self.spacing()
                next_x = x + hint.width() + self.spacing()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + bottom


class StatusBanner(QLabel):
    """A shared, non-blocking status message used by creator workflows."""

    def __init__(self, message="Ready", parent=None):
        super().__init__(message, parent)
        self.setObjectName("statusBanner")
        self.setWordWrap(True)
        self.set_status(message)

    def set_status(self, message: str, level: str = "info") -> None:
        self.setText(message)
        self.setProperty("statusLevel", level)
        self.style().unpolish(self)
        self.style().polish(self)


def set_button_enabled(
    button: QPushButton,
    enabled: bool,
    disabled_reason: str = "",
) -> None:
    """Enable an action and explain unavailable states through its tooltip."""
    button.setEnabled(enabled)
    button.setToolTip("" if enabled else disabled_reason or "This action is unavailable.")


class MetricCard(QFrame):
    def __init__(self, title="", value="—", subtitle=""):
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        self.title = QLabel(title)
        self.title.setObjectName("metricTitle")
        self.value = QLabel(value)
        self.value.setObjectName("metricValue")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("metricSubtitle")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.subtitle)

    def update_value(self, value, subtitle=""):
        self.value.setText(str(value))
        self.subtitle.setText(subtitle)
