from datetime import date
import json
import pandas as pd
from PySide6.QtWidgets import (
    QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QDateEdit,QDoubleSpinBox,
    QSpinBox,QComboBox,QTableWidget,QTableWidgetItem,QTabWidget,QTableView,
    QLineEdit,QCheckBox,QDialog,QDialogButtonBox,QFormLayout,QMessageBox,
    QAbstractItemView
)
from PySide6.QtCore import QDate
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.charts import Chart

class PredictionsPage(QWidget):
    def __init__(self,predictions,recommendations=None):
        super().__init__()
        self.predictions=predictions
        self.recommendations=recommendations
        layout=QVBoxLayout(self)
        title=QLabel("Prediction and Recommendation Intelligence")
        title.setObjectName("pageTitle"); layout.addWidget(title)
        tabs=QTabWidget()
        tabs.addTab(self._twitch_tab(),"Twitch prediction")
        tabs.addTab(self._youtube_tab(),"YouTube prediction")
        tabs.addTab(self._recommend_tab(),"Recommendations")
        tabs.addTab(self._history_tab(),"Prediction history")
        tabs.addTab(self._diagnostics_tab(),"Model diagnostics")
        layout.addWidget(tabs)
        self.refresh_history()

    def _result_table(self):
        table=QTableWidget(0,8)
        table.setHorizontalHeaderLabels([
            "Metric","Estimate","Likely low","Likely high","Algorithm",
            "Validation MAE","RMSE","R²"
        ])
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _fill(self,table,result):
        table.setRowCount(len(result))
        for r,(metric,data) in enumerate(result.items()):
            vals=[
                metric,f'{data["estimate"]:.2f}',f'{data["low"]:.2f}',f'{data["high"]:.2f}',
                data["algorithm"],f'{data["mae"]:.2f}',f'{data["rmse"]:.2f}',f'{data["r2"]:.3f}'
            ]
            for c,v in enumerate(vals): table.setItem(r,c,QTableWidgetItem(v))

    def _twitch_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        self.tw_date=QDateEdit(QDate.currentDate()); self.tw_date.setCalendarPopup(True)
        self.tw_duration=QDoubleSpinBox(); self.tw_duration.setRange(1,24); self.tw_duration.setValue(6)
        self.tw_hour=QSpinBox(); self.tw_hour.setRange(0,23); self.tw_hour.setValue(17)
        self.tw_type=QComboBox(); self.tw_type.addItems(["Normal","Collaboration","Special event"])
        self.tw_start_game=QLineEdit("Unknown"); self.tw_end_game=QLineEdit("Unknown")
        self.tw_switches=QSpinBox(); self.tw_switches.setRange(0,10)
        self.tw_collab=QCheckBox()
        for label,w in [
            ("Date",self.tw_date),("Hours",self.tw_duration),("Start hour",self.tw_hour),
            ("Type",self.tw_type),("Starting game",self.tw_start_game),
            ("Ending game",self.tw_end_game),("Switches",self.tw_switches),
            ("Collab",self.tw_collab)
        ]:
            row.addWidget(QLabel(label)); row.addWidget(w)
        button=QPushButton("Predict Twitch stream"); button.clicked.connect(self.run_twitch)
        row.addWidget(button); layout.addLayout(row)
        self.tw_results=self._result_table(); layout.addWidget(self.tw_results)
        return page

    def run_twitch(self):
        result,pid=self.predictions.predict_twitch(
            self.tw_date.date().toPython(),self.tw_duration.value(),self.tw_hour.value(),
            self.tw_type.currentText(),self.tw_start_game.text(),self.tw_end_game.text(),
            self.tw_switches.value(),self.tw_collab.isChecked()
        )
        self._fill(self.tw_results,result)
        self.refresh_history()

    def _youtube_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        self.yt_format=QComboBox(); self.yt_format.addItems(["Short","Video"])
        self.yt_day=QComboBox(); self.yt_day.addItems(
            ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"])
        self.yt_hour=QSpinBox(); self.yt_hour.setRange(0,23); self.yt_hour.setValue(12)
        self.yt_duration=QSpinBox(); self.yt_duration.setRange(1,20000); self.yt_duration.setValue(45)
        self.yt_title=QSpinBox(); self.yt_title.setRange(1,150); self.yt_title.setValue(45)
        self.yt_impressions=QSpinBox(); self.yt_impressions.setRange(0,10000000); self.yt_impressions.setValue(1000)
        self.yt_topic=QLineEdit("Untagged"); self.yt_series=QLineEdit("None")
        self.yt_thumb=QLineEdit("Unknown"); self.yt_hook=QLineEdit("Unknown")
        self.yt_linked=QCheckBox()
        for label,w in [
            ("Format",self.yt_format),("Weekday",self.yt_day),("Hour",self.yt_hour),
            ("Seconds",self.yt_duration),("Title length",self.yt_title),
            ("Impressions",self.yt_impressions),("Topic",self.yt_topic),
            ("Series",self.yt_series),("Thumbnail",self.yt_thumb),
            ("Hook",self.yt_hook),("Linked stream",self.yt_linked)
        ]:
            row.addWidget(QLabel(label)); row.addWidget(w)
        button=QPushButton("Predict upload"); button.clicked.connect(self.run_youtube)
        row.addWidget(button); layout.addLayout(row)
        self.yt_results=self._result_table(); layout.addWidget(self.yt_results)
        return page

    def run_youtube(self):
        result,pid=self.predictions.predict_youtube(
            self.yt_format.currentText(),self.yt_day.currentText(),
            self.yt_duration.value(),self.yt_title.value(),self.yt_impressions.value(),
            self.yt_hour.value(),self.yt_topic.text(),self.yt_series.text(),
            self.yt_thumb.text(),self.yt_hook.text(),self.yt_linked.isChecked()
        )
        self._fill(self.yt_results,result)
        self.refresh_history()

    def _recommend_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        self.rec_platform=QComboBox(); self.rec_platform.addItems(["Twitch","YouTube"])
        self.rec_objective=QComboBox()
        self.rec_platform.currentTextChanged.connect(self._objective_options)
        self.rec_topics=QLineEdit("Unknown")
        run=QPushButton("Generate ranked plans"); run.clicked.connect(self.run_recommendations)
        row.addWidget(QLabel("Platform")); row.addWidget(self.rec_platform)
        row.addWidget(QLabel("Objective")); row.addWidget(self.rec_objective)
        row.addWidget(QLabel("Games/topics, comma-separated")); row.addWidget(self.rec_topics)
        row.addWidget(run); layout.addLayout(row)
        self.rec_table=QTableView(); layout.addWidget(self.rec_table)
        self._objective_options()
        return page

    def _objective_options(self):
        self.rec_objective.clear()
        if self.rec_platform.currentText()=="Twitch":
            self.rec_objective.addItems(["Balanced","Viewers","Followers","Revenue"])
        else:
            self.rec_objective.addItems(["Balanced","Views","Subscribers","Engagement"])

    def run_recommendations(self):
        if not self.recommendations:
            return
        topics=[x.strip() for x in self.rec_topics.text().split(",") if x.strip()] or ["Unknown"]
        if self.rec_platform.currentText()=="Twitch":
            rows=self.recommendations.recommend_twitch(self.rec_objective.currentText(),topics)
        else:
            rows=self.recommendations.recommend_youtube(self.rec_objective.currentText(),topics)
        flattened=[]
        for item in rows:
            row={"rank":item["rank"],"score":item["score"],**item["plan"]}
            for metric,data in item["prediction"].items():
                row[f"predicted_{metric}"]=data.get("estimate",0)
            flattened.append(row)
        self.rec_table.setModel(FrameModel(pd.DataFrame(flattened)))

    def _history_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        row=QHBoxLayout()
        actual=QPushButton("Enter actual outcome"); actual.clicked.connect(self.enter_actuals)
        refresh=QPushButton("Refresh"); refresh.clicked.connect(self.refresh_history)
        row.addWidget(actual); row.addWidget(refresh); row.addStretch(); layout.addLayout(row)
        self.history_table=QTableView()
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.history_table)
        return page

    def _diagnostics_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        self.accuracy_chart=Chart("Validation MAE by metric")
        layout.addWidget(self.accuracy_chart)
        self.backtest_table=QTableView(); layout.addWidget(self.backtest_table)
        self.diagnostics_table=QTableView(); layout.addWidget(self.diagnostics_table)
        return page

    def refresh_history(self):
        history=self.predictions.history()
        self.history_table.setModel(FrameModel(history))
        diag=self.predictions.diagnostics()
        self.diagnostics_table.setModel(FrameModel(diag))
        back=self.predictions.backtest_summary()
        self.backtest_table.setModel(FrameModel(back))
        if not diag.empty:
            chart=diag.groupby("metric",as_index=False)["validation_mae"].mean()
            self.accuracy_chart.bar(chart["metric"],chart["validation_mae"],"MAE")

    def enter_actuals(self):
        idx=self.history_table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self,"Select prediction","Select a prediction row first.")
            return
        row=self.history_table.model().frame.iloc[idx.row()]
        prediction_id=int(row["id"])
        diag=self.predictions.diagnostics()
        metrics=diag[diag["id"]==prediction_id]["metric"].tolist()
        if not metrics: return
        dialog=QDialog(self); dialog.setWindowTitle(f"Actual outcome — prediction {prediction_id}")
        form=QFormLayout(dialog); widgets={}
        for metric in metrics:
            w=QDoubleSpinBox(); w.setRange(0,100000000); w.setDecimals(2)
            widgets[metric]=w; form.addRow(metric,w)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            self.predictions.match_actuals(
                prediction_id,{metric:w.value() for metric,w in widgets.items()}
            )
            self.refresh_history()
