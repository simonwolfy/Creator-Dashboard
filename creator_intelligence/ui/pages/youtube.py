from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTableView,QTabWidget,QComboBox,QPushButton,QCheckBox,
    QMessageBox,QFormLayout,QLineEdit,QPlainTextEdit,QDialog,QDialogButtonBox,QAbstractItemView,QFileDialog
)
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.widgets import (
    ConnectionStatusPanel, FlowLayout, MetricCard, StatusBanner, set_button_enabled,
)
from creator_intelligence.ui.charts import Chart
from creator_intelligence.services.reporting import ReportingService
from creator_intelligence.ui.oauth_connect import run_browser_oauth, show_connection_result
from creator_intelligence.utils.paths import EXPORT_DIR

class YouTubePage(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service=service
        self.reporter=ReportingService()
        self.validation_timer=QTimer(self)
        self.validation_timer.setInterval(60*60*1000)
        self.validation_timer.timeout.connect(self.validate_youtube_silently)
        self.validation_timer.start()
        self.sync_timer=QTimer(self)
        self.sync_timer.setInterval(30*60*1000)
        self.sync_timer.timeout.connect(self.sync_youtube_silently)
        self.sync_timer.start()
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
        QTimer.singleShot(1500,self.validate_youtube_silently)

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
        page=QWidget(); page_layout=QVBoxLayout(page)
        self.youtube_connection_panel=ConnectionStatusPanel("YouTube")
        page_layout.addWidget(self.youtube_connection_panel)
        self.youtube_banner=StatusBanner("Connection checks run automatically while this page is open.")
        page_layout.addWidget(self.youtube_banner)
        form=QFormLayout();page_layout.addLayout(form)
        self.youtube_api_key=QLineEdit(); self.youtube_api_key.setEchoMode(QLineEdit.Password)
        self.youtube_channel_id=QLineEdit(); self.youtube_sync_enabled=QCheckBox("Enable title sync")
        form.addRow("Optional public-only API key",self.youtube_api_key)
        form.addRow("Channel ID",self.youtube_channel_id)
        form.addRow(self.youtube_sync_enabled)
        oauth_help=QLabel(
            "Recommended: create Google OAuth credentials as a Desktop app, download the JSON file, "
            "then import it once. Connect YouTube will fill the channel ID and tokens."
        )
        oauth_help.setWordWrap(True);form.addRow(oauth_help)
        self.youtube_oauth_client=QLabel("No Google OAuth desktop client imported")
        self.youtube_oauth_client.setWordWrap(True);form.addRow("Google sign-in",self.youtube_oauth_client)
        import_oauth=QPushButton("Import Google OAuth client JSON")
        import_oauth.clicked.connect(self.import_youtube_oauth);form.addRow(import_oauth)
        self.youtube_connect_button=QPushButton("Connect or reconnect YouTube")
        self.youtube_connect_button.clicked.connect(self.connect_youtube);form.addRow(self.youtube_connect_button)
        save=QPushButton("Save YouTube API setup"); save.clicked.connect(self.save_api_setup)
        form.addRow(save)
        controls_widget=QWidget();controls=FlowLayout(controls_widget)
        self.youtube_validate_button=QPushButton("Check connection")
        self.youtube_validate_button.clicked.connect(self.validate_youtube_connection)
        self.youtube_sync_button=QPushButton("Sync content and analytics")
        self.youtube_sync_button.clicked.connect(self.sync_youtube_now)
        self.youtube_disconnect_button=QPushButton("Disconnect and revoke access")
        self.youtube_disconnect_button.clicked.connect(self.disconnect_youtube)
        for button in (self.youtube_validate_button,self.youtube_sync_button,self.youtube_disconnect_button):
            controls.addWidget(button)
        form.addRow(controls_widget)
        self.youtube_api_status=QLabel(); self.youtube_api_status.setWordWrap(True)
        form.addRow("Status",self.youtube_api_status)
        self.youtube_capabilities=QLabel();self.youtube_capabilities.setWordWrap(True)
        form.addRow("Available access",self.youtube_capabilities)
        privacy=QLabel(
            "Creator Intelligence requests read-only YouTube and Analytics access. It cannot edit, upload, "
            "or delete videos. Tokens stay in the operating-system credential vault."
        )
        privacy.setWordWrap(True);form.addRow(privacy)
        page_layout.addStretch()
        config=self.service.social.display_configuration("youtube")
        self.youtube_api_key.setText(config.get("api_key") or "")
        self.youtube_channel_id.setText(config.get("channel_id") or "")
        self.youtube_sync_enabled.setChecked(bool(config.get("enabled")))
        if config.get("oauth_client_id"):
            self.youtube_oauth_client.setText(f"Desktop OAuth client imported · {config.get('oauth_client_id')}")
        self.refresh_api_status()
        return page

    def import_youtube_oauth(self):
        path,_=QFileDialog.getOpenFileName(self,"Choose Google OAuth client JSON","","JSON files (*.json)")
        if not path:return
        try:self.service.social.import_youtube_oauth_client(path)
        except Exception as exc:QMessageBox.critical(self,"Google OAuth setup",str(exc));return
        config=self.service.social.display_configuration("youtube")
        self.youtube_oauth_client.setText(f"Desktop OAuth client imported · {config.get('oauth_client_id')}")
        self.youtube_sync_enabled.setChecked(True)
        QMessageBox.information(self,"Google OAuth setup","Desktop OAuth credentials imported securely. You can now connect YouTube.")

    def connect_youtube(self):
        self.service.social.save_configuration("youtube",{
            "api_key":self.youtube_api_key.text(),"channel_id":self.youtube_channel_id.text()
        },True)
        self.youtube_banner.set_status("Waiting for Google approval...","info")
        try:result=run_browser_oauth(self,self.service.social,"youtube")
        except Exception as exc:
            self.youtube_banner.set_status(str(exc),"error")
            QMessageBox.critical(self,"Connect YouTube",str(exc));return
        if result:
            config=self.service.social.display_configuration("youtube")
            self.youtube_channel_id.setText(config.get("channel_id") or "")
            self.youtube_sync_enabled.setChecked(True)
            self.refresh_api_status()
            try:
                sync_result=self.service.social.sync("youtube")
            except Exception as exc:
                self.youtube_banner.set_status(
                    f"YouTube connected, but the initial sync needs attention: {exc}","warning"
                )
            else:
                self._show_sync_result(sync_result,initial=True)
            self.refresh_all()
            show_connection_result(self,"youtube",result)

    def save_api_setup(self):
        self.service.social.save_configuration("youtube",{
            "api_key":self.youtube_api_key.text(),"channel_id":self.youtube_channel_id.text()
        },self.youtube_sync_enabled.isChecked())
        self.refresh_api_status()
        QMessageBox.information(self,"YouTube API setup","YouTube credentials saved. Packaging sync will use this setup.")

    def refresh_api_status(self):
        status=self.service.social.connection_status("youtube")
        self.youtube_connection_panel.set_status(status)
        account=f" · {status['account_name']}" if status.get("account_name") else ""
        self.youtube_api_status.setText(
            f"{str(status.get('state') or 'not configured').replace('_',' ').title()}{account} · "
            f"Sync: {status['sync_status']}"
        )
        capabilities=[]
        for item in status.get("capabilities") or []:
            marker="Available" if item.get("available") else "Unavailable"
            capabilities.append(f"{marker}: {item['capability']} — {item['permission']}")
        self.youtube_capabilities.setText("\n".join(capabilities))
        set_button_enabled(
            self.youtube_validate_button,bool(status.get("can_disconnect")),
            "Connect YouTube before checking the account.",
        )
        set_button_enabled(
            self.youtube_sync_button,
            bool(status.get("can_sync")) and self.youtube_sync_enabled.isChecked(),
            "Connect YouTube and enable title sync first.",
        )
        set_button_enabled(
            self.youtube_disconnect_button,bool(status.get("can_disconnect")),
            "There are no saved YouTube credentials to clear.",
        )

    def sync_youtube_now(self):
        self.service.social.save_configuration("youtube",{
            "api_key":self.youtube_api_key.text(),"channel_id":self.youtube_channel_id.text()
        },self.youtube_sync_enabled.isChecked())
        try:
            result=self.service.social.sync("youtube")
        except Exception as exc:
            QMessageBox.critical(self,"YouTube sync",str(exc)); self.refresh_api_status(); return
        self.refresh_api_status(); self.refresh_all();self._show_sync_result(result)
        QMessageBox.information(self,"YouTube sync",f"Found {result['seen']} video(s); updated {result['changed']}.")

    def disconnect_youtube(self):
        if QMessageBox.question(self,"Disconnect YouTube","Clear the API key from the operating-system vault?")!=QMessageBox.StandardButton.Yes:return
        result=self.service.social.revoke_and_disconnect("youtube")
        self.youtube_api_key.clear();self.youtube_sync_enabled.setChecked(False);self.refresh_api_status()
        warning=result.get("revocation_warning")
        self.youtube_banner.set_status(
            warning or "YouTube disconnected and local credentials cleared.",
            "warning" if warning else "info",
        )

    def validate_youtube_connection(self):
        status=self.service.social.validate_connection("youtube")
        self.refresh_api_status()
        level="info" if status.get("state") in {"connected","limited"} else "error"
        self.youtube_banner.set_status(status.get("message") or "Connection check complete.",level)

    def validate_youtube_silently(self):
        status=self.service.social.connection_status("youtube")
        if not status.get("can_disconnect"):
            return
        try:self.service.social.validate_connection("youtube")
        except Exception:return
        self.refresh_api_status()

    def sync_youtube_silently(self):
        status=self.service.social.connection_status("youtube")
        if not status.get("can_sync") or not self.youtube_sync_enabled.isChecked():
            return
        try:result=self.service.social.sync("youtube")
        except Exception as exc:
            self.youtube_banner.set_status(f"Background YouTube sync failed: {exc}","warning")
            self.refresh_api_status();return
        self._show_sync_result(result)
        self.refresh_api_status();self.refresh_all()

    def _show_sync_result(self,result,initial=False):
        prefix="Initial sync complete" if initial else "Sync complete"
        message=f"{prefix}: {result['seen']} video(s) checked, {result['changed']} updated."
        warnings=result.get("warnings") or []
        if warnings:
            message += " " + " ".join(warnings)
        self.youtube_banner.set_status(message,"warning" if warnings else "info")

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
