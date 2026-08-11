import pandas as pd
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTableView,QTabWidget,QDateEdit,
    QPushButton,QMessageBox,QFormLayout,QLineEdit,QDialog,QDialogButtonBox,
    QDoubleSpinBox,QAbstractItemView
)
from PySide6.QtCore import QAbstractTableModel, Qt, QDate
from creator_intelligence.ui.widgets import MetricCard
from creator_intelligence.ui.charts import Chart
from creator_intelligence.ui.table_utils import friendly_header
from creator_intelligence.services.reporting import ReportingService
from creator_intelligence.utils.paths import EXPORT_DIR


def prepare_time_trend(frame, value_column, aggregation="mean"):
    """Return a chronological, readable trend for the selected date range."""
    if frame.empty or not {"date", value_column} <= set(frame.columns):
        return pd.DataFrame(columns=["date", value_column]), "daily"

    trend = frame[["date", value_column]].copy()
    trend["date"] = pd.to_datetime(
        trend["date"], errors="coerce", format="mixed"
    ).dt.normalize()
    trend[value_column] = pd.to_numeric(trend[value_column], errors="coerce")
    trend = trend.dropna(subset=["date", value_column]).sort_values(
        "date", kind="stable"
    )
    if trend.empty:
        return trend, "daily"

    span_days = int((trend["date"].max() - trend["date"].min()).days)
    if span_days > 730:
        frequency, resolution = "MS", "monthly"
    elif span_days > 180 or len(trend) > 180:
        frequency, resolution = "W-MON", "weekly"
    else:
        frequency, resolution = "D", "daily"

    trend = (
        trend.set_index("date")[value_column]
        .resample(frequency)
        .agg(aggregation)
        .dropna()
        .reset_index()
        .sort_values("date", kind="stable")
        .reset_index(drop=True)
    )
    return trend, resolution


def trend_title(base_title, resolution):
    return base_title if resolution == "daily" else f"{base_title} ({resolution})"


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
            if orientation == Qt.Horizontal:
                if 0 <= section < len(self.frame.columns):
                    return friendly_header(self.frame.columns[section])
                return None
            if 0 <= section < len(self.frame):
                return str(section+1)
            return None

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
        sync=QPushButton("Sync connected Twitch data"); sync.clicked.connect(self.sync_connected_twitch)
        filters.addWidget(QLabel("Start")); filters.addWidget(self.start)
        filters.addWidget(QLabel("End")); filters.addWidget(self.end)
        filters.addWidget(refresh); filters.addWidget(export); filters.addWidget(sync); filters.addStretch()
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
        self.tabs.addTab(self._historical(),"Historical data")
        self.tabs.addTab(self._connected_api(),"Connected Twitch API")
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

    def _historical(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.historical_health=QLabel(); self.historical_health.setWordWrap(True)
        layout.addWidget(self.historical_health)
        warning=QLabel(
            "Historical metrics use one row per calendar stream-day. Daily metrics are "
            "attributed to a category only for source-backed single-game days; multi-game "
            "days remain visible but are never falsely assigned to one game."
        )
        warning.setWordWrap(True); layout.addWidget(warning)
        tabs=QTabWidget()
        self.historical_days_table=QTableView(); self.historical_days_table.setSortingEnabled(True)
        self.historical_benchmarks_table=QTableView(); self.historical_benchmarks_table.setSortingEnabled(True)
        self.historical_events_table=QTableView(); self.historical_events_table.setSortingEnabled(True)
        self.historical_review_table=QTableView(); self.historical_review_table.setSortingEnabled(True)
        tabs.addTab(self.historical_days_table,"Stream days")
        tabs.addTab(self.historical_benchmarks_table,"Single-game benchmarks")
        tabs.addTab(self.historical_events_table,"Category evidence")
        tabs.addTab(self.historical_review_table,"Needs review")
        layout.addWidget(tabs)
        return page

    def _connected_api(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.connected_status_label=QLabel()
        self.connected_status_label.setWordWrap(True)
        layout.addWidget(self.connected_status_label)
        limits=QLabel(
            "The connection supplies current live status, viewer count, channel title/category, "
            "followers, subscribers, recent broadcasts, and clips. Twitch does not expose the "
            "full Creator Dashboard history (including watch time and revenue) through Helix, so "
            "those historical cards continue to use imported Twitch reports."
        )
        limits.setWordWrap(True);layout.addWidget(limits)
        self.connected_content_table=QTableView()
        self.connected_content_table.setSortingEnabled(True)
        layout.addWidget(self.connected_content_table)
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
        viewer_trend, viewer_resolution = prepare_time_trend(
            df, "average_viewers", "mean"
        )
        revenue_trend, revenue_resolution = prepare_time_trend(
            df, "total_revenue", "sum"
        )
        self.viewer_chart.title = trend_title(
            "Average viewers over time", viewer_resolution
        )
        self.revenue_chart.title = trend_title(
            "Revenue over time", revenue_resolution
        )
        if not viewer_trend.empty:
            self.viewer_chart.line(
                viewer_trend["date"], viewer_trend["average_viewers"], "Viewers"
            )
        else:
            self.viewer_chart.clear()
            self.viewer_chart.canvas.draw_idle()
        if not revenue_trend.empty:
            self.revenue_chart.line(
                revenue_trend["date"], revenue_trend["total_revenue"], "Revenue"
            )
        else:
            self.revenue_chart.clear()
            self.revenue_chart.canvas.draw_idle()
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
            labels=[f'{a} → {b}' for a,b in zip(switches["from_game"],switches["to_game"],strict=True)]
            self.switch_chart.bar(labels,switches["change_15m"].fillna(0),"Viewer change")

        self.timeline_table.setModel(FrameModel(self.service.game_segments().sort_values("segment_start_ts",ascending=False)))
        self.raid_table.setModel(FrameModel(self.service.raids()))
        self.compare_table.setModel(FrameModel(self.service.period_comparison(start,end)))
        health=self.service.historical_health_summary()
        self.historical_health.setText(
            f'{health["stream_days"]:,} stream days | '
            f'{health["source_backed"]:,} source-backed | '
            f'{health["unresolved"]:,} unresolved retained | '
            f'{health["single_game"]:,} single-game | '
            f'{health["multi_game"]:,} multi-game | '
            f'{health["matched_events"]:,} matched events | '
            f'{health["events_for_review"]:,} events retained for review'
        )
        self.historical_days_table.setModel(FrameModel(self.service.historical_stream_days()))
        self.historical_benchmarks_table.setModel(FrameModel(self.service.historical_single_game_benchmarks()))
        self.historical_events_table.setModel(FrameModel(self.service.historical_game_events()))
        self.historical_review_table.setModel(FrameModel(self.service.historical_event_review()))
        connected=self.service.connected_status()
        if connected:
            live="Live" if int(connected.get("is_live") or 0) else "Offline"
            followers=(
                f'{int(connected.get("followers_total")):,} followers'
                if connected.get("followers_total") is not None else "Followers unavailable"
            )
            self.connected_status_label.setText(
                f'{live} Â· {int(connected.get("viewers") or 0):,} viewers Â· '
                f'{followers} Â· '
                f'Last checked {connected.get("captured_at")}'
            )
        else:
            self.connected_status_label.setText(
                "No connected Twitch sync yet. Connect Twitch in Live Stream Intelligence, then sync here."
            )
        self.connected_content_table.setModel(FrameModel(self.service.connected_content()))

    def sync_connected_twitch(self):
        try:
            result=self.service.sync_connected_account()
        except Exception as exc:
            QMessageBox.critical(self,"Twitch sync",str(exc));return
        self.refresh_all()
        status=result.get("status") or {}
        state="live" if status.get("is_live") else "offline"
        QMessageBox.information(
            self,"Twitch sync complete",
            f'Twitch is {state}. Synced {result.get("videos",0)} broadcasts and '
            f'{result.get("clips",0)} clips.'
        )

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
