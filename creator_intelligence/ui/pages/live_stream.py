from __future__ import annotations
from datetime import datetime, timedelta
import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QLabel,QPushButton,QTabWidget,
    QTableView,QAbstractItemView,QGroupBox,QGridLayout,QFormLayout,
    QLineEdit,QSpinBox,QDoubleSpinBox,QCheckBox,QMessageBox,QInputDialog
)
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.oauth_connect import run_twitch_device_oauth, show_connection_result
from creator_intelligence.services.live_stream import LiveSimulationAdapter
from creator_intelligence.services.twitch_eventsub import TwitchEventSubClient
from creator_intelligence.ui.widgets import (
    ConnectionStatusPanel,
    FlowLayout,
    StatusBanner,
    set_button_enabled,
)

class MetricCard(QGroupBox):
    def __init__(self,title):
        super().__init__(title)
        layout=QVBoxLayout(self)
        self.value=QLabel("—")
        self.value.setStyleSheet("font-size:24px;font-weight:700;")
        layout.addWidget(self.value)

class LiveStreamPage(QWidget):
    def __init__(self,service):
        super().__init__()
        self.service=service
        self.simulator=LiveSimulationAdapter(service)
        self.timer=QTimer(self)
        self.timer.timeout.connect(self.simulation_tick)
        self.twitch_timer=QTimer(self)
        self.twitch_timer.timeout.connect(self.poll_twitch)
        self.validation_timer=QTimer(self)
        self.validation_timer.setInterval(60*60*1000)
        self.validation_timer.timeout.connect(self.validate_twitch_silently)
        self.validation_timer.start()
        self.eventsub=TwitchEventSubClient(service,self)
        self.eventsub.status_changed.connect(self.set_twitch_tracking_status)
        self.eventsub.failed.connect(self.twitch_tracking_failed)
        self.eventsub.chat_received.connect(lambda _message:self.refresh_chat())
        self.eventsub.data_changed.connect(self.refresh)

        layout=QVBoxLayout(self)
        title=QLabel("Live Stream Intelligence")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        twitch_group=QGroupBox("Real Twitch tracking")
        twitch_group_layout=QVBoxLayout(twitch_group)
        twitch_controls_widget=QWidget()
        twitch_controls=FlowLayout(twitch_controls_widget)
        self.start_twitch_button=QPushButton("Start Twitch tracking")
        self.start_twitch_button.clicked.connect(self.start_twitch_tracking)
        self.stop_twitch_button=QPushButton("Stop Twitch tracking")
        self.stop_twitch_button.clicked.connect(self.stop_twitch_tracking)
        check_twitch=QPushButton("Check Twitch connection")
        check_twitch.clicked.connect(self.validate_twitch_connection)
        for button in (self.start_twitch_button,self.stop_twitch_button,check_twitch):
            twitch_controls.addWidget(button)
        twitch_group_layout.addWidget(twitch_controls_widget)
        layout.addWidget(twitch_group)

        simulation_group=QGroupBox("Simulation tools")
        simulation_group_layout=QVBoxLayout(simulation_group)
        simulation_controls_widget=QWidget()
        simulation_controls=FlowLayout(simulation_controls_widget)
        start=QPushButton("Start simulation")
        start.clicked.connect(self.start_simulation)
        tick=QPushButton("Advance simulation")
        tick.clicked.connect(self.simulation_tick)
        auto=QPushButton("Run simulation automatically")
        auto.clicked.connect(self.toggle_auto)
        raid=QPushButton("Simulate raid")
        raid.clicked.connect(self.simulate_raid)
        for button in (start,tick,auto,raid):
            simulation_controls.addWidget(button)
        simulation_group_layout.addWidget(simulation_controls_widget)
        layout.addWidget(simulation_group)

        session_group=QGroupBox("Session tools")
        session_group_layout=QVBoxLayout(session_group)
        session_controls_widget=QWidget()
        session_controls=FlowLayout(session_controls_widget)
        marker=QPushButton("Mark moment")
        marker.clicked.connect(self.manual_marker)
        end=QPushButton("End session")
        end.clicked.connect(self.end_session)
        refresh=QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        for button in (marker,end,refresh):
            session_controls.addWidget(button)
        session_group_layout.addWidget(session_controls_widget)
        layout.addWidget(session_group)

        tabs=QTabWidget()
        tabs.addTab(self._dashboard_tab(),"Live dashboard")
        tabs.addTab(self._timeline_tab(),"Session timeline")
        tabs.addTab(self._chat_tab(),"Live chat")
        tabs.addTab(self._markers_tab(),"Markers")
        tabs.addTab(self._settings_tab(),"Connections and rules")
        layout.addWidget(tabs)
        self.refresh()
        QTimer.singleShot(1500,self.validate_twitch_silently)

    def _dashboard_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        grid=QGridLayout()
        titles=[
            ("current","Current viewers"),("average","Session average"),
            ("peak","Peak viewers"),("projected","Projected average"),
            ("velocity","Viewer velocity (5m)"),("followers","Followers gained"),
            ("subs","Subscribers gained"),("chat","Chat messages/min"),
            ("revenue","Revenue / hour"),("retention","Retention estimate"),
            ("score","Performance score"),("status","Prediction status")
        ]
        self.cards={}
        for index,(key,title) in enumerate(titles):
            card=MetricCard(title)
            self.cards[key]=card
            grid.addWidget(card,index//4,index%4)
        layout.addLayout(grid)
        self.session_label=QLabel("No active session")
        layout.addWidget(self.session_label)
        self.tracking_status=QLabel("Twitch real-time tracking is stopped")
        self.tracking_status.setWordWrap(True)
        layout.addWidget(self.tracking_status)
        return page

    def _timeline_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.timeline_table=QTableView()
        self.timeline_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.timeline_table)
        return page

    def _markers_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.marker_table=QTableView()
        self.marker_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.marker_table)
        return page

    def _chat_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        help_text=QLabel(
            "Read-only live chat from the connected Twitch channel. Messages are kept in this "
            "workspace so chat activity can improve real-time markers and session analytics."
        )
        help_text.setWordWrap(True);layout.addWidget(help_text)
        self.chat_table=QTableView()
        self.chat_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.chat_table)
        return page

    def _settings_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.connection_panel=ConnectionStatusPanel("Twitch")
        layout.addWidget(self.connection_panel)
        self.connection_notice=StatusBanner("Twitch connection controls are ready.")
        layout.addWidget(self.connection_notice)
        form=QFormLayout()
        self.simulation_mode=QCheckBox()
        self.twitch_enabled=QCheckBox()
        self.twitch_client_id=QLineEdit()
        self.twitch_broadcaster_id=QLineEdit()
        self.twitch_broadcaster_id.setReadOnly(True)
        self.twitch_broadcaster_id.setPlaceholderText("Filled automatically after sign-in")
        self.twitch_access_token=QLineEdit()
        self.twitch_access_token.setEchoMode(QLineEdit.Password)
        self.twitch_access_token.setReadOnly(True)
        self.twitch_access_token.setPlaceholderText("Stored in the operating-system credential vault")
        self.store_raw_chat=QCheckBox("Retain full chat messages in this workspace")
        self.obs_enabled=QCheckBox()
        self.obs_host=QLineEdit()
        self.obs_port=QSpinBox(); self.obs_port.setRange(1,65535)
        self.obs_password=QLineEdit(); self.obs_password.setEchoMode(QLineEdit.Password)
        self.polling_interval=QSpinBox(); self.polling_interval.setRange(15,600)
        self.viewer_spike=QDoubleSpinBox(); self.viewer_spike.setRange(0.5,5); self.viewer_spike.setSingleStep(0.1)
        self.chat_spike=QDoubleSpinBox(); self.chat_spike.setRange(1.1,10); self.chat_spike.setSingleStep(0.1)
        self.follow_spike=QSpinBox(); self.follow_spike.setRange(1,50)
        self.raid_threshold=QSpinBox(); self.raid_threshold.setRange(1,10000)
        form.addRow("Simulation mode",self.simulation_mode)
        form.addRow("Enable Twitch",self.twitch_enabled)
        form.addRow("Twitch client ID",self.twitch_client_id)
        form.addRow("Broadcaster ID",self.twitch_broadcaster_id)
        form.addRow("OAuth access token",self.twitch_access_token)
        twitch_help=QLabel(
            "Paste only the Client ID from a Public Twitch application. Secure device sign-in "
            "stores tokens in the operating-system credential vault. Requested permissions read "
            "live chat, follower activity, and subscriber totals; Creator Intelligence cannot "
            "post chat messages or modify your channel."
        )
        twitch_help.setWordWrap(True)
        form.addRow(twitch_help)
        connection_buttons=QWidget(); connection_actions=FlowLayout(connection_buttons)
        self.connect_twitch_button=QPushButton("Connect / reconnect Twitch")
        self.connect_twitch_button.clicked.connect(self.connect_twitch)
        self.twitch_client_id.textChanged.connect(
            lambda _text:self._update_twitch_action_states()
        )
        self.validate_twitch_button=QPushButton("Check connection")
        self.validate_twitch_button.clicked.connect(self.validate_twitch_connection)
        self.refresh_twitch_button=QPushButton("Refresh credentials")
        self.refresh_twitch_button.clicked.connect(self.refresh_twitch_credentials)
        self.disconnect_twitch_button=QPushButton("Disconnect and revoke")
        self.disconnect_twitch_button.clicked.connect(
            lambda:self.disconnect_integration("twitch")
        )
        for button in (
            self.connect_twitch_button,self.validate_twitch_button,
            self.refresh_twitch_button,self.disconnect_twitch_button,
        ):
            connection_actions.addWidget(button)
        form.addRow(connection_buttons)
        self.twitch_status=QLabel()
        self.twitch_status.setWordWrap(True)
        form.addRow("Twitch status",self.twitch_status)
        self.twitch_capabilities_table=QTableView()
        self.twitch_capabilities_table.setMaximumHeight(180)
        form.addRow("Available data",self.twitch_capabilities_table)
        form.addRow("Chat privacy",self.store_raw_chat)
        form.addRow("Enable OBS",self.obs_enabled)
        form.addRow("OBS host",self.obs_host)
        form.addRow("OBS port",self.obs_port)
        form.addRow("OBS password",self.obs_password)
        form.addRow("Polling interval",self.polling_interval)
        form.addRow("Viewer spike standard deviations",self.viewer_spike)
        form.addRow("Chat spike multiplier",self.chat_spike)
        form.addRow("Follow spike count",self.follow_spike)
        form.addRow("Raid marker minimum viewers",self.raid_threshold)
        layout.addLayout(form)
        save=QPushButton("Save connection and marker settings")
        save.clicked.connect(self.save_settings)
        layout.addWidget(save)
        disconnect_obs=QPushButton("Disconnect OBS and clear password")
        disconnect_obs.clicked.connect(lambda:self.disconnect_integration("obs"));layout.addWidget(disconnect_obs)
        return page

    def start_simulation(self):
        self.stop_twitch_tracking()
        active=self.service.active_session()
        if active and active.get("source_mode")!="simulation":
            self.service.end_session(active["id"])
            active=None
        self.service.update_settings(simulation_mode=1)
        if not active:
            self.simulator.start()
        self.refresh()

    def simulation_tick(self):
        active=self.service.active_session()
        if active and active.get("source_mode")!="simulation":
            QMessageBox.warning(
                self,"Simulation unavailable",
                "End the real Twitch session before advancing a simulation."
            )
            return
        if not active:
            self.simulator.start()
        # Advance test time one minute per click so rolling calculations are meaningful.
        session=self.service.active_session()
        snapshots=self.service.snapshots(session["id"])
        at=datetime.fromisoformat(session["started_at"]) + timedelta(minutes=len(snapshots)+1)
        self.simulator.tick(at=at)
        self.refresh()

    def toggle_auto(self):
        if self.timer.isActive():
            self.timer.stop()
        else:
            active=self.service.active_session()
            if active and active.get("source_mode")!="simulation":
                QMessageBox.warning(
                    self,"Simulation unavailable",
                    "End the real Twitch session before running a simulation."
                )
                return
            if not active:
                self.simulator.start()
            self.timer.start(1000)

    def manual_marker(self):
        if not self.service.active_session():
            QMessageBox.information(self,"No session","Start a session first.")
            return
        label,ok=QInputDialog.getText(self,"Mark moment","Marker label")
        if ok and label:
            self.service.add_manual_marker(label)
            self.refresh()

    def simulate_raid(self):
        if not self.service.active_session():
            self.simulator.start()
        viewers,ok=QInputDialog.getInt(self,"Simulate raid","Raid viewers",50,1,100000)
        if ok:
            self.service.add_raid(viewers,"SimulationChannel",f"sim-raid-{datetime.now().timestamp()}")
            self.refresh()

    def end_session(self):
        self.timer.stop()
        self.stop_twitch_tracking()
        if self.service.active_session():
            self.service.end_session()
        self.refresh()

    def refresh(self):
        session=self.service.active_session()
        if not session:
            self.session_label.setText("No active session")
            for card in self.cards.values():
                card.value.setText("—")
            self.timeline_table.setModel(FrameModel(pd.DataFrame()))
            self.marker_table.setModel(FrameModel(pd.DataFrame()))
            self.refresh_chat()
            self.load_settings()
            return
        dashboard=self.service.dashboard(session["id"])
        predicted=float(session.get("predicted_average_viewers") or 0)
        projected=float(dashboard["projected_average"])
        status="No baseline"
        if predicted:
            diff=(projected-predicted)/predicted*100
            status=("Above prediction" if diff>=3 else
                    "Below prediction" if diff<=-3 else "Near prediction")
            status += f" ({diff:+.1f}%)"
        values={
            "current":f'{dashboard["current_viewers"]:,}',
            "average":f'{dashboard["average_viewers"]:.1f}',
            "peak":f'{dashboard["peak_viewers"]:,}',
            "projected":f'{dashboard["projected_average"]:.1f}',
            "velocity":f'{dashboard["viewer_velocity_5m"]:+.2f}/min',
            "followers":f'{dashboard["followers_gained"]:,}',
            "subs":f'{dashboard["subscribers_gained"]:,}',
            "chat":f'{dashboard["chat_messages_minute"]:,}',
            "revenue":f'${dashboard["revenue_per_hour"]:.2f}',
            "retention":f'{dashboard["retention_estimate"]*100:.0f}%',
            "score":f'{dashboard["performance_score"]:.0f}/100',
            "status":status
        }
        for key,value in values.items():
            self.cards[key].value.setText(value)
        self.session_label.setText(
            f'{session.get("title") or "Untitled"} • '
            f'{session.get("game") or "No category"} • '
            f'{session.get("source_mode")} mode'
        )
        self.timeline_table.setModel(FrameModel(self.service.timeline(session["id"])))
        self.marker_table.setModel(FrameModel(self.service.markers(session["id"])))
        self.refresh_chat()
        self.load_settings()

    def refresh_chat(self):
        if bool(self.service.settings().get("store_raw_chat")):
            frame=self.service.chat_messages()
        else:
            frame=pd.DataFrame(self.eventsub.recent_chat())
        self.chat_table.setModel(FrameModel(frame))

    def start_twitch_tracking(self):
        try:
            status=self.service.ensure_twitch_connection(force_validation=True)
            settings=self.service.settings()
            if self.service.active_session() and self.service.active_session().get("source_mode")!="twitch":
                raise ValueError("End the simulation session before starting Twitch tracking.")
            self.timer.stop()
            self.service.update_settings(simulation_mode=0,twitch_enabled=1)
            self.eventsub.start()
            interval=max(15,int(settings.get("polling_interval_seconds") or 60))*1000
            self.twitch_timer.start(interval)
            self.poll_twitch()
            self.connection_notice.set_status(status["message"],"success")
            self.load_settings()
        except Exception as exc:
            safe=self.service.vault.redact(exc)
            self.connection_notice.set_status(safe,"error")
            QMessageBox.critical(self,"Start Twitch tracking",safe)

    def stop_twitch_tracking(self):
        self.twitch_timer.stop()
        self.eventsub.stop()
        if hasattr(self,"tracking_status"):
            self.tracking_status.setText("Twitch real-time tracking is stopped")
        if hasattr(self,"stop_twitch_button"):
            self._update_twitch_action_states()

    def poll_twitch(self):
        try:
            status=self.service.poll_twitch_live()
        except Exception as exc:
            self.twitch_tracking_failed(str(exc));return
        if status.get("is_live"):
            self.tracking_status.setText(
                f'Twitch is live Â· {int(status.get("viewers") or 0):,} viewers Â· '
                f'{status.get("game") or "No category"}'
            )
        else:
            self.tracking_status.setText(
                "Connected and watching Twitch Â· Channel is currently offline"
            )
        self.refresh()

    def set_twitch_tracking_status(self,message):
        self.tracking_status.setText(str(message))

    def twitch_tracking_failed(self,message):
        safe=self.service.vault.redact(message)
        self.tracking_status.setText(f"Twitch tracking needs attention: {safe}")
        if hasattr(self,"connection_notice"):
            self.connection_notice.set_status(safe,"error")

    def validate_twitch_connection(self):
        status=self.service.validate_twitch_connection()
        self.load_settings()
        level="success" if status.get("can_sync") else "error"
        self.connection_notice.set_status(status["message"],level)

    def validate_twitch_silently(self):
        status=self.service.twitch_connection_status()
        if not status.get("configured"):
            return
        try:
            status=self.service.ensure_twitch_connection()
        except Exception:
            status=self.service.twitch_connection_status()
        if not status.get("can_sync") and self.eventsub.wanted:
            self.stop_twitch_tracking()
        self.load_settings()

    def refresh_twitch_credentials(self):
        try:
            self.service.refresh_twitch_connection()
            status=self.service.validate_twitch_connection()
        except Exception as exc:
            safe=self.service.vault.redact(exc)
            self.connection_notice.set_status(safe,"error")
            QMessageBox.warning(self,"Refresh Twitch credentials",safe)
            self.load_settings()
            return
        self.load_settings()
        self.connection_notice.set_status(status["message"],"success")

    def _update_twitch_action_states(self):
        status=self.service.twitch_connection_status()
        tracking=bool(self.eventsub.wanted or self.twitch_timer.isActive())
        set_button_enabled(
            self.start_twitch_button,
            bool(status.get("can_sync")) and not tracking,
            "Connect Twitch and resolve any authentication problem first."
            if not status.get("can_sync") else "Twitch tracking is already running.",
        )
        set_button_enabled(
            self.stop_twitch_button,tracking,"Twitch tracking is already stopped."
        )
        if hasattr(self,"validate_twitch_button"):
            set_button_enabled(
                self.connect_twitch_button,
                bool(self.twitch_client_id.text().strip()),
                "Paste the Twitch Client ID first.",
            )
            set_button_enabled(
                self.validate_twitch_button,
                bool(status.get("configured")),
                "Connect Twitch before checking the account.",
            )
            has_refresh=bool(self.service.settings().get("twitch_refresh_token"))
            set_button_enabled(
                self.refresh_twitch_button,has_refresh,
                "Reconnect Twitch to obtain a refresh token.",
            )
            set_button_enabled(
                self.disconnect_twitch_button,
                bool(status.get("can_disconnect")),
                "Twitch is already disconnected.",
            )

    def load_settings(self):
        settings=self.service.display_settings()
        self.simulation_mode.setChecked(bool(settings["simulation_mode"]))
        self.twitch_enabled.setChecked(bool(settings["twitch_enabled"]))
        self.twitch_client_id.setText(settings["twitch_client_id"] or "")
        self.twitch_broadcaster_id.setText(settings["twitch_broadcaster_id"] or "")
        self.twitch_access_token.setText(settings["twitch_access_token"] or "")
        connected = bool(
            settings.get("twitch_enabled") and settings.get("twitch_client_id")
            and settings.get("twitch_broadcaster_id") and settings.get("twitch_access_token")
        )
        self.twitch_status.setText(
            f"Connected · Broadcaster ID {settings.get('twitch_broadcaster_id')}"
            if connected else "Not connected · A Client ID is required to start sign-in"
        )
        status=self.service.twitch_connection_status()
        self.connection_panel.set_status(status)
        details=[]
        if status.get("last_validated_at"):
            details.append(f"Last checked {status['last_validated_at']}")
        if status.get("expires_at"):
            details.append(f"Access token expires {status['expires_at']}")
        if status.get("last_error"):
            details.append(f"Error: {status['last_error']}")
        self.twitch_status.setText(" | ".join(details) or status["message"])
        self.twitch_capabilities_table.setModel(
            FrameModel(pd.DataFrame(self.service.twitch_capabilities()))
        )
        self.obs_enabled.setChecked(bool(settings["obs_enabled"]))
        self.obs_host.setText(settings["obs_host"] or "127.0.0.1")
        self.obs_port.setValue(int(settings["obs_port"] or 4455))
        self.obs_password.setText(settings["obs_password"] or "")
        self.polling_interval.setValue(int(settings["polling_interval_seconds"] or 60))
        self.viewer_spike.setValue(float(settings["viewer_spike_stddev"] or 2.0))
        self.chat_spike.setValue(float(settings["chat_spike_multiplier"] or 2.5))
        self.follow_spike.setValue(int(settings["follow_spike_count"] or 3))
        self.raid_threshold.setValue(int(settings["raid_marker_min_viewers"] or 10))
        self.store_raw_chat.setChecked(bool(settings.get("store_raw_chat")))
        self._update_twitch_action_states()

    def save_settings(self):
        self.service.update_settings(
            simulation_mode=int(self.simulation_mode.isChecked()),
            twitch_enabled=int(self.twitch_enabled.isChecked()),
            twitch_client_id=self.twitch_client_id.text().strip() or None,
            twitch_broadcaster_id=self.twitch_broadcaster_id.text().strip() or None,
            obs_enabled=int(self.obs_enabled.isChecked()),
            obs_host=self.obs_host.text().strip() or "127.0.0.1",
            obs_port=self.obs_port.value(),
            obs_password=self.obs_password.text() or None,
            polling_interval_seconds=self.polling_interval.value(),
            viewer_spike_stddev=self.viewer_spike.value(),
            chat_spike_multiplier=self.chat_spike.value(),
            follow_spike_count=self.follow_spike.value(),
            raid_marker_min_viewers=self.raid_threshold.value(),
            store_raw_chat=int(self.store_raw_chat.isChecked())
        )
        QMessageBox.information(self,"Settings saved","Live integration settings were saved.")

    def connect_twitch(self):
        try:
            result=run_twitch_device_oauth(self,self.service,self.twitch_client_id.text().strip())
        except Exception as exc:
            safe=self.service.vault.redact(exc)
            self.connection_notice.set_status(safe,"error")
            QMessageBox.critical(self,"Connect Twitch",safe);return
        if result:
            self.load_settings()
            try:
                synced=self.service.sync_twitch_content()
            except Exception as exc:
                safe=self.service.vault.redact(exc)
                self.connection_notice.set_status(
                    f"Twitch connected, but the initial content sync failed: {safe}",
                    "error",
                )
            else:
                self.connection_notice.set_status(
                    f"Twitch connected. Initial sync found {synced['videos']} video(s) "
                    f"and {synced['clips']} clip(s).",
                    "success",
                )
            show_connection_result(self,"twitch",result)

    def disconnect_integration(self,provider):
        if QMessageBox.question(self,"Disconnect",f"Clear {provider.title()} credentials from the operating-system vault?")!=QMessageBox.StandardButton.Yes:return
        warning=None
        if provider=="twitch":
            self.stop_twitch_tracking()
            try:self.service.revoke_twitch_access()
            except Exception as exc:warning=self.service.vault.redact(exc)
        self.service.disconnect_integration(provider);self.load_settings()
        if provider=="twitch":
            self.connection_notice.set_status(
                "Twitch disconnected and local credentials cleared.","success"
            )
        if warning:QMessageBox.warning(self,"Disconnected locally",f"Credentials were cleared, but Twitch could not be reached to revoke the token: {warning}")
