import pandas as pd
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTabWidget,QTableView,QPushButton,
    QMessageBox,QDialog,QDialogButtonBox,QFormLayout,QComboBox,QLineEdit,
    QSpinBox,QDoubleSpinBox,QPlainTextEdit,QDateTimeEdit,QAbstractItemView
)
from PySide6.QtCore import QDateTime
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.widgets import MetricCard
from creator_intelligence.ui.charts import Chart
from creator_intelligence.services.reporting import ReportingService
from creator_intelligence.utils.paths import EXPORT_DIR

class CrossPlatformPage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.reporter = ReportingService()
        layout = QVBoxLayout(self)
        title = QLabel("Cross-Platform Content Intelligence")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        cards = QHBoxLayout()
        self.cards = {}
        for key,label in [
            ("streams","Streams"),("linked_streams","Linked streams"),
            ("linked_uploads","Linked uploads"),("youtube_views_from_links","Linked YouTube views"),
            ("combined_revenue","Combined revenue"),("editing_hours","Editing hours")
        ]:
            self.cards[key] = MetricCard(label)
            cards.addWidget(self.cards[key])
        layout.addLayout(cards)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._overview_tab(),"Overview")
        self.tabs.addTab(self._links_tab(),"Stream-to-content links")
        self.tabs.addTab(self._attribution_tab(),"Attribution and ROI")
        self.tabs.addTab(self._repurpose_tab(),"Repurposing")
        self.tabs.addTab(self._calendar_tab(),"Content calendar")
        layout.addWidget(self.tabs)
        self.refresh_all()

    def _overview_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        self.views_chart=Chart("YouTube views attributed by stream")
        self.revenue_chart=Chart("Combined revenue by stream")
        row.addWidget(self.views_chart); row.addWidget(self.revenue_chart)
        layout.addLayout(row)
        self.chain_table=QTableView()
        layout.addWidget(self.chain_table)
        export=QPushButton("Export cross-platform chains")
        export.clicked.connect(self.export_chains)
        layout.addWidget(export)
        return page

    def _links_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        add=QPushButton("Link stream to YouTube content"); add.clicked.connect(self.add_link)
        delete=QPushButton("Delete selected link"); delete.clicked.connect(self.delete_link)
        row.addWidget(add); row.addWidget(delete); row.addStretch()
        layout.addLayout(row)
        self.links_table=QTableView()
        self.links_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.links_table)
        return page

    def _attribution_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        edit=QPushButton("Edit attribution for selected link")
        edit.clicked.connect(self.edit_attribution)
        layout.addWidget(edit)
        self.attribution_table=QTableView()
        self.attribution_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.attribution_table)
        return page

    def _repurpose_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.repurpose_chart=Chart("Top streams to repurpose")
        layout.addWidget(self.repurpose_chart)
        self.repurpose_table=QTableView()
        layout.addWidget(self.repurpose_table)
        return page

    def _calendar_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        add=QPushButton("Add calendar item"); add.clicked.connect(self.add_calendar_item)
        status=QPushButton("Change selected status"); status.clicked.connect(self.change_calendar_status)
        delete=QPushButton("Delete selected item"); delete.clicked.connect(self.delete_calendar_item)
        row.addWidget(add); row.addWidget(status); row.addWidget(delete); row.addStretch()
        layout.addLayout(row)
        self.calendar_table=QTableView()
        self.calendar_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.calendar_table)
        return page

    def selected_id(self, table):
        idx=table.currentIndex()
        if not idx.isValid(): return None
        frame=table.model().frame
        if "id" not in frame.columns: return None
        return int(frame.iloc[idx.row()]["id"])

    def refresh_all(self):
        overview=self.service.overview()
        for key,card in self.cards.items():
            value=overview.get(key,0)
            if key=="combined_revenue":
                value=f"${value:,.2f}"
            elif isinstance(value,float):
                value=f"{value:,.1f}"
            card.update_value(value)

        chains=self.service.chain_summary()
        self.chain_table.setModel(FrameModel(chains))
        if not chains.empty:
            top=chains.head(20)
            self.views_chart.bar(top["stream_id"],top["youtube_views"],"Views")
            self.revenue_chart.bar(top["stream_id"],top["combined_revenue"],"Revenue")

        links=self.service.links()
        self.links_table.setModel(FrameModel(links))
        attr = links.merge(
            self.service.db.frame("SELECT * FROM stream_content_metrics"),
            left_on=["source_id","target_id"],right_on=["stream_id","content_id"],how="left"
        ) if not links.empty else links
        self.attribution_table.setModel(FrameModel(attr))

        scores=self.service.repurposing_scores()
        self.repurpose_table.setModel(FrameModel(scores))
        if not scores.empty:
            top=scores.head(15)
            self.repurpose_chart.bar(top["stream_id"],top["repurposing_score"],"Score")

        self.calendar_table.setModel(FrameModel(
            self.service.calendar_items().sort_values("scheduled_start")
        ))

    def add_link(self):
        streams=self.service.twitch_streams()
        content=self.service.youtube_content()
        if streams.empty or content.empty:
            QMessageBox.information(self,"Data required","Twitch streams and YouTube content are required.")
            return
        dialog=QDialog(self); dialog.setWindowTitle("Link stream to content")
        form=QFormLayout(dialog)
        stream=QComboBox()
        for _,r in streams.head(1000).iterrows():
            stream.addItem(str(r["stream_id"]),str(r["stream_id"]))
        upload=QComboBox()
        for _,r in content.iterrows():
            upload.addItem(f'{r["title"]} [{r["content_id"]}]',str(r["content_id"]))
        rel=QComboBox(); rel.addItems(["Derived from","Full video","Highlight","Short","Clip","Episode"])
        start=QSpinBox(); start.setRange(0,1000000)
        end=QSpinBox(); end.setRange(0,1000000)
        notes=QPlainTextEdit()
        form.addRow("Twitch stream",stream); form.addRow("YouTube content",upload)
        form.addRow("Relationship",rel); form.addRow("Source start seconds",start)
        form.addRow("Source end seconds",end); form.addRow("Notes",notes)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec():
            self.service.create_link(
                stream.currentData(),upload.currentData(),rel.currentText(),
                start.value() or None,end.value() or None,notes.toPlainText()
            )
            self.refresh_all()

    def delete_link(self):
        link_id=self.selected_id(self.links_table)
        if link_id:
            self.service.delete_link(link_id)
            self.refresh_all()

    def edit_attribution(self):
        idx=self.attribution_table.currentIndex()
        if not idx.isValid(): return
        row=self.attribution_table.model().frame.iloc[idx.row()]
        dialog=QDialog(self); dialog.setWindowTitle("Attribution")
        form=QFormLayout(dialog)
        editing=QDoubleSpinBox(); editing.setRange(0,10000); editing.setValue(float(row.get("editing_hours") or 0))
        cost=QDoubleSpinBox(); cost.setRange(0,1000000); cost.setValue(float(row.get("direct_cost") or 0))
        revenue=QDoubleSpinBox(); revenue.setRange(0,1000000); revenue.setValue(float(row.get("attributed_revenue") or 0))
        subs=QDoubleSpinBox(); subs.setRange(0,1000000); subs.setValue(float(row.get("attributed_subscribers") or 0))
        views=QDoubleSpinBox(); views.setRange(0,100000000); views.setValue(float(row.get("attributed_views") or 0))
        notes=QPlainTextEdit(str(row.get("notes_y") or row.get("notes") or ""))
        for label,w in [
            ("Editing hours",editing),("Direct cost",cost),("Attributed revenue",revenue),
            ("Attributed subscribers",subs),("Attributed views",views),("Notes",notes)
        ]:
            form.addRow(label,w)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec():
            self.service.update_attribution(
                str(row["source_id"]),str(row["target_id"]),editing.value(),cost.value(),
                revenue.value(),subs.value(),views.value(),notes.toPlainText()
            )
            self.refresh_all()

    def add_calendar_item(self):
        dialog=QDialog(self); dialog.setWindowTitle("Calendar item")
        form=QFormLayout(dialog)
        item_type=QComboBox(); item_type.addItems(["Twitch stream","YouTube video","Short","Editing deadline","Thumbnail deadline","Other"])
        title=QLineEdit()
        platform=QComboBox(); platform.addItems(["Twitch","YouTube","Cross-platform","Other"])
        start=QDateTimeEdit(QDateTime.currentDateTime()); start.setCalendarPopup(True)
        end=QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600)); end.setCalendarPopup(True)
        status=QComboBox(); status.addItems(["Planned","In progress","Scheduled","Published","Complete","Cancelled"])
        priority=QComboBox(); priority.addItems(["Low","Normal","High","Critical"])
        recurrence=QLineEdit()
        notes=QPlainTextEdit()
        for label,w in [
            ("Type",item_type),("Title",title),("Platform",platform),("Start",start),
            ("End",end),("Status",status),("Priority",priority),
            ("Recurrence",recurrence),("Notes",notes)
        ]:
            form.addRow(label,w)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec():
            self.service.add_calendar_item(
                item_type.currentText(),title.text(),platform.currentText(),
                start.dateTime().toPython(),end.dateTime().toPython(),
                status.currentText(),recurrence=recurrence.text(),
                priority=priority.currentText(),notes=notes.toPlainText()
            )
            self.refresh_all()

    def change_calendar_status(self):
        item_id=self.selected_id(self.calendar_table)
        if not item_id: return
        dialog=QDialog(self); dialog.setWindowTitle("Change status")
        form=QFormLayout(dialog)
        status=QComboBox(); status.addItems(["Planned","In progress","Scheduled","Published","Complete","Cancelled"])
        form.addRow("Status",status)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec():
            self.service.update_calendar_status(item_id,status.currentText())
            self.refresh_all()

    def delete_calendar_item(self):
        item_id=self.selected_id(self.calendar_table)
        if item_id:
            self.service.delete_calendar_item(item_id)
            self.refresh_all()

    def export_chains(self):
        path=self.reporter.export_csv(
            self.service.chain_summary(),EXPORT_DIR,"cross_platform_content_chains"
        )
        QMessageBox.information(self,"Export complete",str(path))
