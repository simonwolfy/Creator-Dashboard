from __future__ import annotations
from datetime import datetime, timedelta
import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTabWidget,
    QTableView,QAbstractItemView,QGroupBox,QGridLayout,QFormLayout,
    QLineEdit,QSpinBox,QDoubleSpinBox,QCheckBox,QMessageBox,QInputDialog
)
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.oauth_connect import run_twitch_device_oauth, show_connection_result
from creator_intelligence.services.live_stream import LiveSimulationAdapter

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

        layout=QVBoxLayout(self)
        title=QLabel("Live Stream Intelligence")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        controls=QHBoxLayout()
        start=QPushButton("Start simulation")
        start.clicked.connect(self.start_simulation)
        tick=QPushButton("Advance simulation")
        tick.clicked.connect(self.simulation_tick)
        auto=QPushButton("Run simulation automatically")
        auto.clicked.connect(self.toggle_auto)
        marker=QPushButton("Mark moment")
        marker.clicked.connect(self.manual_marker)
        raid=QPushButton("Simulate raid")
        raid.clicked.connect(self.simulate_raid)
        end=QPushButton("End session")
        end.clicked.connect(self.end_session)
        refresh=QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        for button in (start,tick,auto,marker,raid,end,refresh):
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        tabs=QTabWidget()
        tabs.addTab(self._dashboard_tab(),"Live dashboard")
        tabs.addTab(self._timeline_tab(),"Session timeline")
        tabs.addTab(self._markers_tab(),"Markers")
        tabs.addTab(self._settings_tab(),"Connections and rules")
        layout.addWidget(tabs)
        self.refresh()

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

    def _settings_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        form=QFormLayout()
        self.simulation_mode=QCheckBox()
        self.twitch_enabled=QCheckBox()
        self.twitch_client_id=QLineEdit()
        self.twitch_broadcaster_id=QLineEdit()
        self.twitch_access_token=QLineEdit()
        self.twitch_access_token.setEchoMode(QLineEdit.Password)
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
            "Paste only the Client ID from the Twitch developer console. Connect Twitch will open "
            "a secure device sign-in and fill the broadcaster ID and tokens automatically."
        )
        twitch_help.setWordWrap(True)
        form.addRow(twitch_help)
        connect_twitch=QPushButton("Connect Twitch")
        connect_twitch.clicked.connect(self.connect_twitch)
        form.addRow(connect_twitch)
        self.twitch_status=QLabel()
        self.twitch_status.setWordWrap(True)
        form.addRow("Twitch status",self.twitch_status)
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
        disconnect_twitch=QPushButton("Disconnect Twitch and clear credentials")
        disconnect_twitch.clicked.connect(lambda:self.disconnect_integration("twitch"));layout.addWidget(disconnect_twitch)
        disconnect_obs=QPushButton("Disconnect OBS and clear password")
        disconnect_obs.clicked.connect(lambda:self.disconnect_integration("obs"));layout.addWidget(disconnect_obs)
        return page

    def start_simulation(self):
        if not self.service.active_session():
            self.simulator.start()
        self.refresh()

    def simulation_tick(self):
        if not self.service.active_session():
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
            if not self.service.active_session():
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
        self.load_settings()

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
        self.obs_enabled.setChecked(bool(settings["obs_enabled"]))
        self.obs_host.setText(settings["obs_host"] or "127.0.0.1")
        self.obs_port.setValue(int(settings["obs_port"] or 4455))
        self.obs_password.setText(settings["obs_password"] or "")
        self.polling_interval.setValue(int(settings["polling_interval_seconds"] or 60))
        self.viewer_spike.setValue(float(settings["viewer_spike_stddev"] or 2.0))
        self.chat_spike.setValue(float(settings["chat_spike_multiplier"] or 2.5))
        self.follow_spike.setValue(int(settings["follow_spike_count"] or 3))
        self.raid_threshold.setValue(int(settings["raid_marker_min_viewers"] or 10))

    def save_settings(self):
        self.service.update_settings(
            simulation_mode=int(self.simulation_mode.isChecked()),
            twitch_enabled=int(self.twitch_enabled.isChecked()),
            twitch_client_id=self.twitch_client_id.text().strip() or None,
            twitch_broadcaster_id=self.twitch_broadcaster_id.text().strip() or None,
            twitch_access_token=self.twitch_access_token.text().strip() or None,
            obs_enabled=int(self.obs_enabled.isChecked()),
            obs_host=self.obs_host.text().strip() or "127.0.0.1",
            obs_port=self.obs_port.value(),
            obs_password=self.obs_password.text() or None,
            polling_interval_seconds=self.polling_interval.value(),
            viewer_spike_stddev=self.viewer_spike.value(),
            chat_spike_multiplier=self.chat_spike.value(),
            follow_spike_count=self.follow_spike.value(),
            raid_marker_min_viewers=self.raid_threshold.value()
        )
        QMessageBox.information(self,"Settings saved","Live integration settings were saved.")

    def connect_twitch(self):
        try:
            result=run_twitch_device_oauth(self,self.service,self.twitch_client_id.text().strip())
        except Exception as exc:
            QMessageBox.critical(self,"Connect Twitch",str(exc));return
        if result:
            self.load_settings()
            show_connection_result(self,"twitch",result)

    def disconnect_integration(self,provider):
        if QMessageBox.question(self,"Disconnect",f"Clear {provider.title()} credentials from the operating-system vault?")!=QMessageBox.StandardButton.Yes:return
        warning=None
        if provider=="twitch":
            try:self.service.revoke_twitch_access()
            except Exception as exc:warning=str(exc)
        self.service.disconnect_integration(provider);self.load_settings()
        if warning:QMessageBox.warning(self,"Disconnected locally",f"Credentials were cleared, but Twitch could not be reached to revoke the token: {warning}")
