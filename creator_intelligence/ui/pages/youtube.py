import pandas as pd
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTableView,QTabWidget,QComboBox,QPushButton,QCheckBox,
    QMessageBox,QFormLayout,QLineEdit,QPlainTextEdit,QDialog,QDialogButtonBox,QAbstractItemView
)
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.widgets import MetricCard
from creator_intelligence.ui.charts import Chart
from creator_intelligence.services.reporting import ReportingService
from creator_intelligence.utils.paths import EXPORT_DIR

class YouTubePage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service=service
        self.reporter=ReportingService()
        layout=QVBoxLayout(self)
        title=QLabel("YouTube Intelligence"); title.setObjectName("pageTitle"); layout.addWidget(title)

        filters=QHBoxLayout()
        self.format=QComboBox(); self.format.addItems(["All","Short","Video"])
        self.format.currentTextChanged.connect(self.refresh_all)
        export=QPushButton("Export content report"); export.clicked.connect(self.export_content)
        filters.addWidget(QLabel("Format")); filters.addWidget(self.format); filters.addWidget(export); filters.addStretch()
        layout.addLayout(filters)

        cards=QHBoxLayout(); self.cards={}
        for key,label in [
            ("uploads","Uploads"),("views","Views"),("watch_hours","Watch hours"),
            ("net_subscribers","Net subscribers"),("weighted_ctr","Weighted CTR"),
            ("engagement_rate","Engagement rate")
        ]:
            self.cards[key]=MetricCard(label); cards.addWidget(self.cards[key])
        layout.addLayout(cards)

        self.tabs=QTabWidget()
        self.tabs.addTab(self._dashboard(),"Dashboard")
        self.tabs.addTab(self._content(),"Content")
        self.tabs.addTab(self._topics(),"Topics and tags")
        self.tabs.addTab(self._titles(),"Titles")
        self.tabs.addTab(self._audience(),"Audience")
        self.tabs.addTab(self._geography(),"Geography")
        self.tabs.addTab(self._metadata(),"Metadata editor")
        self.tabs.addTab(self._api_setup(),"API setup")
        layout.addWidget(self.tabs)
        self.refresh_all()

    def current_format(self): return self.format.currentText()

    def _dashboard(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        self.format_chart=Chart("Shorts vs videos")
        self.weekday_chart=Chart("Median views by publish weekday")
        row.addWidget(self.format_chart); row.addWidget(self.weekday_chart); layout.addLayout(row)
        row2=QHBoxLayout()
        self.views_chart=Chart("Views by upload")
        self.retention_chart=Chart("Average percentage viewed by upload")
        row2.addWidget(self.views_chart); row2.addWidget(self.retention_chart); layout.addLayout(row2)
        return page

    def _content(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.content_table=QTableView(); self.content_table.setSortingEnabled(True)
        self.content_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.content_table)
        return page

    def _topics(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.topic_chart=Chart("Views by game/topic")
        layout.addWidget(self.topic_chart)
        self.topic_table=QTableView(); layout.addWidget(self.topic_table)
        return page

    def _titles(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.title_chart=Chart("Median views by title length")
        layout.addWidget(self.title_chart)
        self.title_table=QTableView(); layout.addWidget(self.title_table)
        return page

    def _audience(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        self.audience_chart=Chart("Monthly audience")
        self.subscriber_chart=Chart("Subscribers")
        row.addWidget(self.audience_chart); row.addWidget(self.subscriber_chart)
        layout.addLayout(row)
        self.audience_table=QTableView(); layout.addWidget(self.audience_table)
        return page

    def _geography(self):
        page=QWidget(); layout=QVBoxLayout(page)
        tabs=QTabWidget()
        self.geo_table=QTableView(); self.city_table=QTableView(); self.age_table=QTableView()
        tabs.addTab(self.geo_table,"Countries/regions")
        tabs.addTab(self.city_table,"Cities")
        tabs.addTab(self.age_table,"Viewer age")
        layout.addWidget(tabs)
        return page

    def _metadata(self):
        page=QWidget(); layout=QVBoxLayout(page)
        layout.addWidget(QLabel("Select a row in Content, then use this editor to tag its game, series, collaborator, thumbnail style, and hook style."))
        edit=QPushButton("Edit metadata for selected content"); edit.clicked.connect(self.edit_metadata)
        layout.addWidget(edit)
        self.metadata_table=QTableView(); layout.addWidget(self.metadata_table)
        return page

    def _api_setup(self):
        page=QWidget(); form=QFormLayout(page)
        self.youtube_api_key=QLineEdit(); self.youtube_api_key.setEchoMode(QLineEdit.Password)
        self.youtube_channel_id=QLineEdit(); self.youtube_sync_enabled=QCheckBox("Enable title sync")
        form.addRow("YouTube Data API key",self.youtube_api_key)
        form.addRow("Channel ID",self.youtube_channel_id)
        form.addRow(self.youtube_sync_enabled)
        save=QPushButton("Save YouTube API setup"); save.clicked.connect(self.save_api_setup)
        form.addRow(save)
        self.youtube_api_status=QLabel(); self.youtube_api_status.setWordWrap(True)
        form.addRow("Status",self.youtube_api_status)
        config=self.service.social.configuration("youtube")
        self.youtube_api_key.setText(config.get("api_key") or "")
        self.youtube_channel_id.setText(config.get("channel_id") or "")
        self.youtube_sync_enabled.setChecked(bool(config.get("enabled")))
        self.refresh_api_status()
        return page

    def save_api_setup(self):
        self.service.social.save_configuration("youtube",{
            "api_key":self.youtube_api_key.text(),"channel_id":self.youtube_channel_id.text()
        },self.youtube_sync_enabled.isChecked())
        self.refresh_api_status()
        QMessageBox.information(self,"YouTube API setup","YouTube credentials saved. Packaging sync will use this setup.")

    def refresh_api_status(self):
        status=self.service.social.connection_status("youtube")
        self.youtube_api_status.setText(
            f"Configured · Sync: {status['sync_status']}" if status["configured"]
            else "Missing YouTube Data API key or channel ID"
        )

    def refresh_all(self):
        fmt=self.current_format()
        summary=self.service.summary(fmt)
        for key,card in self.cards.items():
            value=summary.get(key,0)
            if key in {"weighted_ctr","engagement_rate"}: value=f"{value:,.2f}%"
            elif isinstance(value,float): value=f"{value:,.2f}"
            card.update_value(value)

        content=self.service.content(fmt)
        columns=[c for c in [
            "content_id","title","format","publish_date","duration_seconds","views","engaged_views",
            "watch_time_hours","avg_percentage_viewed","stayed_to_watch","impressions","ctr",
            "net_subscribers","likes","comments","shares","engagement_rate","subscriber_conversion",
            "game_topic","series","collaborator","thumbnail_style","hook_style"
        ] if c in content]
        self.content_table.setModel(FrameModel(content[columns].sort_values("views",ascending=False)))
        self.metadata_table.setModel(FrameModel(content[[
            c for c in ["content_id","title","game_topic","series","episode","collaborator","thumbnail_style","hook_style","tags","notes"] if c in content
        ]]))

        comparison=self.service.format_comparison()
        if not comparison.empty:
            self.format_chart.bar(comparison["format"],comparison["median_views"],"Median views")
        weekday=self.service.weekday(fmt)
        if not weekday.empty:
            self.weekday_chart.bar(weekday["weekday"],weekday["median_views"],"Median views")
        if not content.empty:
            ordered=content.sort_values("publish_date")
            self.views_chart.line(ordered["publish_date"],ordered["views"],"Views")
            self.retention_chart.line(ordered["publish_date"],ordered["avg_percentage_viewed"],"% viewed")

        topics=self.service.topic_analysis()
        self.topic_table.setModel(FrameModel(topics))
        if not topics.empty:
            top=topics.head(15)
            self.topic_chart.bar(top["game_topic"],top["views"],"Views")

        titles=self.service.title_analysis()
        self.title_table.setModel(FrameModel(titles))
        if not titles.empty:
            self.title_chart.bar(titles["title_band"],titles["median_views"],"Median views")

        audience=self.service.audience()
        self.audience_table.setModel(FrameModel(audience.sort_values("date",ascending=False)))
        if not audience.empty:
            self.audience_chart.line(audience["date"],audience["monthly_audience"],"Audience")
            self.subscriber_chart.line(audience["date"],audience["subscribers"],"Subscribers")

        self.geo_table.setModel(FrameModel(self.service.geography()))
        self.city_table.setModel(FrameModel(self.service.cities()))
        self.age_table.setModel(FrameModel(self.service.age()))

    def selected_content(self):
        index=self.content_table.currentIndex()
        if not index.isValid(): return None
        return self.content_table.model().frame.iloc[index.row()].to_dict()

    def edit_metadata(self):
        row=self.selected_content()
        if not row:
            QMessageBox.information(self,"Select content","Select a row in the Content tab first.")
            return
        dialog=QDialog(self); dialog.setWindowTitle(f'Metadata — {row.get("title","")}')
        form=QFormLayout(dialog)
        fields={}
        for key,label in [
            ("game_topic","Game/topic"),("series","Series"),("episode","Episode"),
            ("collaborator","Collaborator"),("thumbnail_style","Thumbnail style"),
            ("hook_style","Hook style"),("tags","Tags")
        ]:
            widget=QLineEdit(str(row.get(key) or "")); fields[key]=widget; form.addRow(label,widget)
        notes=QPlainTextEdit(str(row.get("notes") or "")); fields["notes"]=notes; form.addRow("Notes",notes)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec():
            values={k:(w.toPlainText() if isinstance(w,QPlainTextEdit) else w.text()) for k,w in fields.items()}
            self.service.save_metadata(row["content_id"],values)
            self.refresh_all()

    def export_content(self):
        path=self.reporter.export_csv(self.service.content(self.current_format()),EXPORT_DIR,"youtube_content_report")
        QMessageBox.information(self,"Export complete",str(path))
