import math

from PySide6.QtWidgets import QWidget, QVBoxLayout
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


def safe_numeric_values(values):
    """Return finite floats suitable for Matplotlib, replacing nulls with 0."""
    cleaned = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        if not math.isfinite(number):
            number = 0.0
        cleaned.append(number)
    return cleaned


def has_nonzero_numeric_values(values):
    """Return whether a series contains a finite, non-zero numeric value."""
    return any(abs(value) > 0 for value in safe_numeric_values(values))


class Chart(QWidget):
    def __init__(self, title=""):
        super().__init__()
        layout = QVBoxLayout(self)
        self.figure = Figure(figsize=(6,3), tight_layout=True)
        self.figure.patch.set_facecolor("#0f1422")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.title = title
        layout.addWidget(self.canvas)

    def clear(self):
        self.ax.clear()
        self.ax.set_facecolor("#0f1422")
        self.ax.set_title(self.title, color="#f8fafc", pad=10)
        self.ax.tick_params(colors="#dbe4f0")
        self.ax.xaxis.label.set_color("#dbe4f0")
        self.ax.yaxis.label.set_color("#dbe4f0")
        for spine in self.ax.spines.values():
            spine.set_color("#39445c")

    def no_data(self, message="No data available for this period"):
        self.clear()
        self.ax.text(
            0.5,
            0.5,
            message,
            transform=self.ax.transAxes,
            ha="center",
            va="center",
            color="#aebbd0",
            fontsize=11,
            wrap=True,
        )
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.canvas.draw_idle()

    def line(self, x, y, ylabel="", label=None):
        self.clear()
        self.ax.plot(x, safe_numeric_values(y), color="#5da9ff", linewidth=1.8, label=label)
        self.ax.set_ylabel(ylabel)
        self.ax.grid(True, color="#65738c", alpha=.25)
        if label:
            self.ax.legend(facecolor="#182033", edgecolor="#39445c", labelcolor="#f8fafc")
        self.figure.autofmt_xdate()
        self.canvas.draw_idle()

    def bar(self, x, y, ylabel=""):
        self.clear()
        labels = ["" if value is None else str(value) for value in x]
        self.ax.bar(labels, safe_numeric_values(y), color="#5da9ff")
        self.ax.set_ylabel(ylabel)
        self.ax.tick_params(axis="x", rotation=35)
        self.ax.grid(True, axis="y", color="#65738c", alpha=.25)
        self.canvas.draw_idle()

    def scatter(self, x, y, xlabel="", ylabel=""):
        self.clear()
        self.ax.scatter(x, safe_numeric_values(y), color="#5da9ff", alpha=.75)
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)
        self.ax.grid(True, color="#65738c", alpha=.25)
        self.canvas.draw_idle()
