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


class Chart(QWidget):
    def __init__(self, title=""):
        super().__init__()
        layout = QVBoxLayout(self)
        self.figure = Figure(figsize=(6,3), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.title = title
        layout.addWidget(self.canvas)

    def clear(self):
        self.ax.clear()
        self.ax.set_title(self.title)

    def line(self, x, y, ylabel="", label=None):
        self.clear()
        self.ax.plot(x, safe_numeric_values(y), label=label)
        self.ax.set_ylabel(ylabel)
        self.ax.grid(True, alpha=.25)
        if label:
            self.ax.legend()
        self.figure.autofmt_xdate()
        self.canvas.draw_idle()

    def bar(self, x, y, ylabel=""):
        self.clear()
        labels = ["" if value is None else str(value) for value in x]
        self.ax.bar(labels, safe_numeric_values(y))
        self.ax.set_ylabel(ylabel)
        self.ax.tick_params(axis="x", rotation=35)
        self.ax.grid(True, axis="y", alpha=.25)
        self.canvas.draw_idle()

    def scatter(self, x, y, xlabel="", ylabel=""):
        self.clear()
        self.ax.scatter(x, safe_numeric_values(y), alpha=.7)
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)
        self.ax.grid(True, alpha=.25)
        self.canvas.draw_idle()
