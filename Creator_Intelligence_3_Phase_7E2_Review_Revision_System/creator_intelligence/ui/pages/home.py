from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem
from creator_intelligence.ui.widgets import MetricCard

class HomePage(QWidget):
    def __init__(self, analytics, recommendations):
        super().__init__()
        self.analytics = analytics
        self.recommendations = recommendations
        layout = QVBoxLayout(self)
        title = QLabel("Creator Command Center")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        row = QHBoxLayout()
        self.cards = {
            "hours": MetricCard("Twitch stream hours"),
            "revenue": MetricCard("Twitch revenue"),
            "ytviews": MetricCard("YouTube views"),
            "subs": MetricCard("YouTube net subscribers"),
        }
        for card in self.cards.values():
            row.addWidget(card)
        layout.addLayout(row)

        layout.addWidget(QLabel("Top recommended Twitch schedule windows"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Date", "Day", "Start", "Expected avg", "Likely range"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self):
        s = self.analytics.summary()
        self.cards["hours"].update_value(f'{s["stream_hours"]:,.1f} h')
        self.cards["revenue"].update_value(f'${s["twitch_revenue"]:,.2f}')
        self.cards["ytviews"].update_value(f'{s["youtube_views"]:,.0f}')
        self.cards["subs"].update_value(f'{s["youtube_subscribers"]:,.0f}')
        try:
            recs = self.recommendations.twitch_schedule()
        except Exception:
            recs = []
        self.table.setRowCount(len(recs))
        for r, item in enumerate(recs):
            values = [
                item["date"], item["weekday"], f'{item["start_hour"]:02d}:00',
                f'{item["estimate"]:.2f}', f'{item["low"]:.2f}–{item["high"]:.2f}'
            ]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(value))
