from pathlib import Path
import pandas as pd
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTableView,QTabWidget,QDateEdit,
    QPushButton,QMessageBox,QFormLayout,QLineEdit,QComboBox,QDialog,QDialogButtonBox,
    QDoubleSpinBox,QTableWidget,QTableWidgetItem,QAbstractItemView
)
from PySide6.QtCore import QAbstractTableModel, Qt, QDate
from creator_intelligence.ui.widgets import MetricCard
from creator_intelligence.ui.charts import Chart
from creator_intelligence.ui.table_utils import friendly_header
from creator_intelligence.services.reporting import ReportingService
from creator_intelligence.utils.paths import EXPORT_DIR

class FrameModel(QAbstractTableModel):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame.reset_index(drop=True)

    def rowCount(self, parent=None): return len(self.frame)
    def columnCount(self, parent=None): return len(self.frame.columns)
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        value = self.frame.iat[index.row(), index.column()]
        if role == Qt.DisplayRole:
            if pd.isna(value): return ""
            if isinstance(value, float): return f"{value:,.2f}"
            if isinstance(value, pd.Timestamp): return value.strftime("%Y-%m-%d %H:%M")
            return str(value)
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return friendly_header(self.frame.columns[section]) if orientation == Qt.Horizontal else str(section+1)

class TwitchPage(QWidget):
    def __init__(self, service, db):
        super().__init__()
        self.service=service
        self.db=db
        self.reporter=ReportingService()
        layout=QVBoxLayout(self)
        title=QLabel("Twitch Intelligence"); title.setObjectName("pageTitle"); layout.addWidget(title)

        filters=QHBoxLayout()
        self.start=QDateEdit(QDate(2023,1,1)); self.start.setCalendarPopup(True)
        self.end=QDateEdit(QDate.currentDate()); self.end.setCalendarPopup(True)
        refresh=QPushButton("Apply date range"); refresh.clicked.connect(self.refresh_all)
        export=QPushButton("Export filtered streams"); export.clicked.connect(self.export_streams)
        filters.addWidget(QLabel("Start")); filters.addWidget(self.start)
        filters.addWidget(QLabel("End")); filters.addWidget(self.end)
        filters.addWidget(refresh); filters.addWidget(export); filters.addStretch()
        layout.addLayout(filters)

        self.cards_row=QHBoxLayout()
        self.cards={}
        for key,label in [
            ("streams","Streams"),("hours","Hours"),("average_viewers","Average viewers"),
            ("peak_viewers","Peak viewers"),("follows","Follows"),("revenue","Revenue")
        ]:
            self.cards[key]=MetricCard(label)
            self.cards_row.addWidget(self.cards[key])
        layout.addLayout(self.cards_row)

        self.tabs=QTabWidget()
        self.tabs.addTab(self._dashboard(),"Dashboard")
        self.tabs.addTab(self._streams(),"Streams")
        self.tabs.addTab(self._games(),"Games")
        self.tabs.addTab(self._switches(),"Switch impact")
        self.tabs.addTab(self._timeline(),"Timeline editor")
        self.tabs.addTab(self._raids(),"Raids")
        self.tabs.addTab(self._comparison(),"Period comparison")
        layout.addWidget(self.tabs)
        self.refresh_all()

    def dates(self):
        return self.start.date().toPython(), self.end.date().toPython()

    def _dashboard(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        self.viewer_chart=Chart("Average viewers over time")
        self.revenue_chart=Chart("Revenue over time")
        row.addWidget(self.viewer_chart); row.addWidget(self.revenue_chart)
        layout.addLayout(row)
        row2=QHBoxLayout()
        self.weekday_chart=Chart("Average viewers by weekday")
        self.duration_chart=Chart("Revenue per hour by duration")
        row2.addWidget(self.weekday_chart); row2.addWidget(self.duration_chart)
        layout.addLayout(row2)
        return page

    def _streams(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.stream_table=QTableView(); self.stream_table.setSortingEnabled(True)
        layout.addWidget(self.stream_table)
        return page

    def _games(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.game_chart=Chart("Hours by game/category")
        layout.addWidget(self.game_chart)
        self.game_table=QTableView(); self.game_table.setSortingEnabled(True)
        layout.addWidget(self.game_table)
        return page

    def _switches(self):
        page=QWidget(); layout=QVBoxLayout(page)
        layout.addWidget(QLabel("Viewer change compares the five minutes before a category switch with the following 5, 15, and 30 minutes."))
        self.switch_chart=Chart("Viewer impact after category switches")
        layout.addWidget(self.switch_chart)
        self.switch_table=QTableView(); layout.addWidget(self.switch_table)
        return page

    def _timeline(self):
        page=QWidget(); layout=QVBoxLayout(page)
        buttons=QHBoxLayout()
        edit=QPushButton("Edit selected segment"); edit.clicked.connect(self.edit_segment)
        add=QPushButton("Add manual segment"); add.clicked.connect(self.add_segment)
        delete=QPushButton("Delete selected manual segment"); delete.clicked.connect(self.delete_segment)
        buttons.addWidget(edit); buttons.addWidget(add); buttons.addWidget(delete); buttons.addStretch()
        layout.addLayout(buttons)
        self.timeline_table=QTableView()
        self.timeline_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.timeline_table)
        return page

    def _raids(self):
        page=QWidget(); layout=QVBoxLayout(page)
        layout.addWidget(QLabel("Raid retention fields are ready for imported raid events. Add records manually until a Twitch/StreamElements raid importer is connected."))
        add=QPushButton("Add raid record"); add.clicked.connect(self.add_raid); layout.addWidget(add)
        self.raid_table=QTableView(); layout.addWidget(self.raid_table)
        return page

    def _comparison(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.compare_table=QTableView(); layout.addWidget(self.compare_table)
        return page

    def refresh_all(self):
        start,end=self.dates()
        summary=self.service.summary(start,end)
        for key,card in self.cards.items():
            value=summary.get(key,0)
            if key=="revenue": value=f"${value:,.2f}"
            elif key=="hours": value=f"{value:,.1f}"
            elif isinstance(value,float): value=f"{value:,.2f}"
            card.update_value(value)

        df=self.service.daily(start,end)
        self.stream_table.setModel(FrameModel(df[[
            "date","duration_hours","average_viewers","max_viewers","unique_viewers",
            "follows","followers_per_hour","watch_hours","total_revenue","revenue_per_hour",
            "chat_messages","messages_per_hour"
        ]].sort_values("date",ascending=False)))
        if not df.empty:
            self.viewer_chart.line(df["date"],df["average_viewers"],"Viewers")
            self.revenue_chart.line(df["date"],df["total_revenue"],"Revenue")
        weekday=self.service.weekday(start,end)
        if not weekday.empty:
            self.weekday_chart.bar(weekday["weekday"],weekday["average_viewers"],"Viewers")
        bands=self.service.duration_bands(start,end)
        if not bands.empty:
            self.duration_chart.bar(bands["duration_band"],bands["revenue_per_hour"],"Revenue/hour")

        games=self.service.game_summary()
        self.game_table.setModel(FrameModel(games))
        if not games.empty:
            top=games.head(15)
            self.game_chart.bar(top["game"],top["hours"],"Hours")

        switches=self.service.switch_impact()
        self.switch_table.setModel(FrameModel(switches))
        if not switches.empty:
            labels=[f'{a} → {b}' for a,b in zip(switches["from_game"],switches["to_game"])]
            self.switch_chart.bar(labels,switches["change_15m"].fillna(0),"Viewer change")

        self.timeline_table.setModel(FrameModel(self.service.game_segments().sort_values("segment_start_ts",ascending=False)))
        self.raid_table.setModel(FrameModel(self.service.raids()))
        self.compare_table.setModel(FrameModel(self.service.period_comparison(start,end)))

    def selected_id(self, table):
        index=table.currentIndex()
        if not index.isValid(): return None
        model=table.model()
        if "id" not in model.frame.columns: return None
        return int(model.frame.iloc[index.row()]["id"])

    def segment_dialog(self, existing=None):
        dialog=QDialog(self); dialog.setWindowTitle("Game segment")
        form=QFormLayout(dialog)
        start=QLineEdit("" if existing is None else str(existing.get("segment_start_ts","")))
        end=QLineEdit("" if existing is None else str(existing.get("segment_end_ts","")))
        game=QLineEdit("" if existing is None else str(existing.get("game","")))
        stream=QLineEdit("" if existing is None else str(existing.get("stream_start_ts","")))
        form.addRow("Stream start timestamp",stream)
        form.addRow("Segment start timestamp",start)
        form.addRow("Segment end timestamp",end)
        form.addRow("Game/category",game)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            return stream.text(),start.text(),end.text(),game.text()
        return None

    def add_segment(self):
        values=self.segment_dialog()
        if values:
            self.db.execute("""INSERT INTO game_segments(stream_start_ts,segment_start_ts,segment_end_ts,game,changed_by,source_file)
                VALUES(?,?,?,?,?,'manual')""", (*values,"manual"))
            self.refresh_all()

    def edit_segment(self):
        sid=self.selected_id(self.timeline_table)
        if sid is None: return
        row=self.db.frame("SELECT * FROM game_segments WHERE id=?",(sid,))
        if row.empty: return
        values=self.segment_dialog(row.iloc[0].to_dict())
        if values:
            self.db.execute("""UPDATE game_segments SET stream_start_ts=?,segment_start_ts=?,segment_end_ts=?,
                game=?,changed_by='manual' WHERE id=?""", (*values,sid))
            self.refresh_all()

    def delete_segment(self):
        sid=self.selected_id(self.timeline_table)
        if sid is None: return
        self.db.execute("DELETE FROM game_segments WHERE id=? AND (changed_by='manual' OR source_file='manual')",(sid,))
        self.refresh_all()

    def add_raid(self):
        dialog=QDialog(self); dialog.setWindowTitle("Raid")
        form=QFormLayout(dialog)
        ts=QLineEdit(); raider=QLineEdit(); size=QDoubleSpinBox(); size.setRange(0,100000)
        r5=QDoubleSpinBox(); r5.setRange(0,100); r15=QDoubleSpinBox(); r15.setRange(0,100)
        follows=QDoubleSpinBox(); follows.setRange(0,10000)
        for label,w in [("Event timestamp",ts),("Raider",raider),("Raid size",size),
                        ("Retained after 5m (%)",r5),("Retained after 15m (%)",r15),
                        ("Followers after raid",follows)]:
            form.addRow(label,w)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec():
            self.db.execute("""INSERT INTO raids(event_ts,raider,raid_size,retained_5m,retained_15m,followers_after,source)
                VALUES(?,?,?,?,?,?,'manual')""",(ts.text(),raider.text(),size.value(),r5.value(),r15.value(),follows.value()))
            self.refresh_all()

    def export_streams(self):
        start,end=self.dates()
        path=self.reporter.export_csv(self.service.daily(start,end),EXPORT_DIR,"twitch_stream_report")
        QMessageBox.information(self,"Export complete",str(path))
