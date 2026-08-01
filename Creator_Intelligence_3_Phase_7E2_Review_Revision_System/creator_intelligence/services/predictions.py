from __future__ import annotations
from datetime import datetime
import json
import hashlib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

class PredictionService:
    MODEL_VERSION = "4.0.0"

    def __init__(self, db, analytics):
        self.db = db
        self.analytics = analytics
        self._ensure_schema()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS prediction_models(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                target TEXT NOT NULL,
                model_version TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                trained_at TEXT NOT NULL,
                training_rows INTEGER NOT NULL,
                feature_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )""",
            """CREATE TABLE IF NOT EXISTS prediction_metric_results(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_id INTEGER NOT NULL,
                metric TEXT NOT NULL,
                estimate REAL,
                low REAL,
                high REAL,
                validation_mae REAL,
                validation_rmse REAL,
                validation_r2 REAL,
                training_rows INTEGER,
                actual REAL,
                absolute_error REAL,
                percentage_error REAL,
                matched_at TEXT,
                FOREIGN KEY(prediction_id) REFERENCES prediction_runs(id) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS recommendation_candidates(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_run_id INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                platform TEXT NOT NULL,
                objective TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                prediction_json TEXT NOT NULL,
                score REAL NOT NULL,
                created_at TEXT NOT NULL
            )""",
            """CREATE INDEX IF NOT EXISTS idx_pred_metric_prediction
               ON prediction_metric_results(prediction_id)""",
            """CREATE INDEX IF NOT EXISTS idx_pred_models_target
               ON prediction_models(platform,target,is_active)""",
            """CREATE INDEX IF NOT EXISTS idx_recommendation_rank
               ON recommendation_candidates(recommendation_run_id,rank)""",
        ]
        for sql in statements:
            self.db.execute(sql)

    def _model_candidates(self):
        return {
            "RandomForest": RandomForestRegressor(
                n_estimators=350, min_samples_leaf=2, max_features=0.85,
                random_state=42, n_jobs=-1
            ),
            "ExtraTrees": ExtraTreesRegressor(
                n_estimators=350, min_samples_leaf=2, max_features=0.9,
                random_state=42, n_jobs=-1
            ),
        }

    def _fit_best(self, frame, target, categorical, numeric, input_row, min_rows=20):
        cols = categorical + numeric + [target]
        data = frame[cols].replace([np.inf,-np.inf], np.nan).dropna().copy()
        if len(data) < min_rows or data[target].nunique() < 2:
            return None

        split = min(max(int(len(data)*0.8), 1), len(data)-1)
        train, test = data.iloc[:split], data.iloc[split:]
        prep = ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
            ("num", StandardScaler(), numeric),
        ])

        candidates = []
        for name, estimator in self._model_candidates().items():
            model = Pipeline([("prep", prep), ("model", estimator)])
            model.fit(train[categorical+numeric], train[target])
            pred = model.predict(test[categorical+numeric])
            mae = float(mean_absolute_error(test[target], pred))
            rmse = float(mean_squared_error(test[target], pred) ** 0.5)
            r2 = float(r2_score(test[target], pred)) if len(test) > 1 else 0.0
            candidates.append((mae, name, model, pred, rmse, r2))

        mae, name, model, test_pred, rmse, r2 = min(candidates, key=lambda x: x[0])
        estimate = float(model.predict(pd.DataFrame([input_row]))[0])
        residuals = test[target].to_numpy() - test_pred
        q10, q90 = np.quantile(residuals, [0.10,0.90]) if len(residuals) >= 5 else (-mae, mae)
        low = max(0.0, estimate + float(q10))
        high = max(low, estimate + float(q90))
        if high == low:
            spread = max(mae, abs(estimate)*0.1, 1.0)
            low, high = max(0.0, estimate-spread), estimate+spread

        return {
            "estimate": max(0.0, estimate),
            "low": low,
            "high": high,
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "training_rows": len(data),
            "algorithm": name,
            "features": categorical+numeric,
        }

    def _twitch_frame(self):
        df = self.analytics.twitch_daily()
        df = df[df["streamed"]].copy().sort_values("date")
        df["day_index"] = (df["date"]-pd.Timestamp("2023-01-01")).dt.days
        df["start_hour"] = 17
        df["stream_type"] = "Normal"
        df["starting_game"] = "Unknown"
        df["ending_game"] = "Unknown"
        df["collaboration"] = 0
        df["switch_count"] = 0
        for metric in ["average_viewers","follows","total_revenue","watch_hours","unique_viewers","max_viewers"]:
            df[f"recent_{metric}"] = df[metric].shift(1).rolling(5,min_periods=1).mean()
        df["previous_average_viewers"] = df["average_viewers"].shift(1)
        df["month"] = df["date"].dt.month.astype(str)
        return df.fillna(0)

    def predict_twitch(
        self, planned_date, duration_hours, start_hour, stream_type="Normal",
        starting_game="Unknown", ending_game="Unknown", switch_count=0,
        collaboration=False, save=True
    ):
        df = self._twitch_frame()
        row = {
            "weekday": planned_date.strftime("%A"),
            "month": str(planned_date.month),
            "stream_type": stream_type,
            "starting_game": starting_game or "Unknown",
            "ending_game": ending_game or starting_game or "Unknown",
            "day_index": (pd.Timestamp(planned_date)-pd.Timestamp("2023-01-01")).days,
            "duration_hours": float(duration_hours),
            "start_hour": int(start_hour),
            "switch_count": int(switch_count),
            "collaboration": int(bool(collaboration)),
            "recent_average_viewers": float(df["average_viewers"].tail(5).mean()),
            "recent_follows": float(df["follows"].tail(5).mean()),
            "recent_total_revenue": float(df["total_revenue"].tail(5).mean()),
            "recent_watch_hours": float(df["watch_hours"].tail(5).mean()),
            "recent_unique_viewers": float(df["unique_viewers"].tail(5).mean()),
            "recent_max_viewers": float(df["max_viewers"].tail(5).mean()),
            "previous_average_viewers": float(df["average_viewers"].iloc[-1]) if len(df) else 0,
        }
        categorical = ["weekday","month","stream_type","starting_game","ending_game"]
        numeric = [
            "day_index","duration_hours","start_hour","switch_count","collaboration",
            "recent_average_viewers","recent_follows","recent_total_revenue",
            "recent_watch_hours","recent_unique_viewers","recent_max_viewers",
            "previous_average_viewers"
        ]
        targets = {
            "average_viewers":"average_viewers","peak_viewers":"max_viewers",
            "unique_viewers":"unique_viewers","follows":"follows",
            "watch_hours":"watch_hours","revenue":"total_revenue"
        }
        outputs={}
        for label,target in targets.items():
            result=self._fit_best(df,target,categorical,numeric,row)
            if result: outputs[label]=result
        prediction_id = self._save("Twitch",row,outputs) if save else None
        return outputs, prediction_id

    def _youtube_frame(self):
        df=self.analytics.youtube_content().copy().sort_values("publish_date")
        df["weekday"]=df["publish_date"].dt.day_name().fillna("Unknown")
        df["publish_hour"]=df["publish_date"].dt.hour.fillna(12)
        df["title_length"]=df["title"].fillna("").str.len()
        df["day_index"]=(df["publish_date"]-pd.Timestamp("2015-01-01")).dt.days.fillna(0)
        df["game_topic"]="Untagged"
        df["series"]="None"
        df["thumbnail_style"]="Unknown"
        df["hook_style"]="Unknown"
        df["linked_stream"]=0
        for metric in ["views","watch_time_hours","subscribers_gained","likes","comments"]:
            df[f"recent_{metric}"]=df[metric].shift(1).rolling(5,min_periods=1).mean().fillna(0)
        return df.fillna(0)

    def predict_youtube(
        self, format_name, weekday, duration_seconds, title_length, impressions,
        publish_hour=12, game_topic="Untagged", series="None",
        thumbnail_style="Unknown", hook_style="Unknown", linked_stream=False,
        save=True
    ):
        df=self._youtube_frame()
        row={
            "format":format_name,"weekday":weekday,"publish_hour":int(publish_hour),
            "game_topic":game_topic or "Untagged","series":series or "None",
            "thumbnail_style":thumbnail_style or "Unknown","hook_style":hook_style or "Unknown",
            "duration_seconds":int(duration_seconds),"title_length":int(title_length),
            "impressions":float(impressions),"linked_stream":int(bool(linked_stream)),
            "day_index":(pd.Timestamp.today()-pd.Timestamp("2015-01-01")).days,
            "recent_views":float(df["views"].tail(5).mean()),
            "recent_watch_time_hours":float(df["watch_time_hours"].tail(5).mean()),
            "recent_subscribers_gained":float(df["subscribers_gained"].tail(5).mean()),
            "recent_likes":float(df["likes"].tail(5).mean()),
            "recent_comments":float(df["comments"].tail(5).mean()),
        }
        categorical=["format","weekday","game_topic","series","thumbnail_style","hook_style"]
        numeric=[
            "publish_hour","duration_seconds","title_length","impressions","linked_stream",
            "day_index","recent_views","recent_watch_time_hours",
            "recent_subscribers_gained","recent_likes","recent_comments"
        ]
        targets={
            "views":"views","engaged_views":"engaged_views",
            "watch_hours":"watch_time_hours","subscribers_gained":"subscribers_gained",
            "likes":"likes","comments":"comments"
        }
        outputs={}
        for label,target in targets.items():
            result=self._fit_best(df,target,categorical,numeric,row)
            if result: outputs[label]=result
        prediction_id=self._save("YouTube",row,outputs) if save else None
        return outputs,prediction_id

    def _save(self,platform,inputs,outputs):
        prediction_id=self.db.execute("""INSERT INTO prediction_runs
            (created_at,platform,model_name,inputs_json,outputs_json,validation_json)
            VALUES(?,?,?,?,?,?)""",(
                datetime.now().isoformat(),platform,f"AutoSelect-{self.MODEL_VERSION}",
                json.dumps(inputs,default=str),json.dumps(outputs,default=str),
                json.dumps({k:{"mae":v["mae"],"rmse":v["rmse"],"r2":v["r2"],
                                    "rows":v["training_rows"],"algorithm":v["algorithm"]}
                            for k,v in outputs.items()})
            ))
        for metric,v in outputs.items():
            self.db.execute("""INSERT INTO prediction_metric_results
                (prediction_id,metric,estimate,low,high,validation_mae,validation_rmse,
                 validation_r2,training_rows)
                VALUES(?,?,?,?,?,?,?,?,?)""",(
                    prediction_id,metric,v["estimate"],v["low"],v["high"],v["mae"],
                    v["rmse"],v["r2"],v["training_rows"]
                ))
            self.db.execute("""INSERT INTO prediction_models(
                platform,target,model_version,algorithm,trained_at,training_rows,
                feature_json,metrics_json,is_active
            ) VALUES(?,?,?,?,?,?,?,?,1)""",(
                platform,metric,self.MODEL_VERSION,v["algorithm"],datetime.now().isoformat(),
                v["training_rows"],json.dumps(v["features"]),
                json.dumps({"mae":v["mae"],"rmse":v["rmse"],"r2":v["r2"]})
            ))
        return prediction_id

    def match_actuals(self,prediction_id,actuals):
        now=datetime.now().isoformat()
        for metric,actual in actuals.items():
            row=self.db.frame("""SELECT estimate FROM prediction_metric_results
                WHERE prediction_id=? AND metric=?""",(prediction_id,metric))
            if row.empty: continue
            estimate=float(row.iloc[0]["estimate"])
            actual=float(actual)
            abs_error=abs(actual-estimate)
            pct_error=(abs_error/abs(actual)*100) if actual else None
            self.db.execute("""UPDATE prediction_metric_results SET actual=?,
                absolute_error=?,percentage_error=?,matched_at=?
                WHERE prediction_id=? AND metric=?""",
                (actual,abs_error,pct_error,now,prediction_id,metric))
        self.db.execute("""INSERT OR REPLACE INTO prediction_actuals
            (prediction_id,actual_json,matched_at) VALUES(?,?,?)""",
            (prediction_id,json.dumps(actuals),now))

    def backtest_summary(self,platform=None):
        where="WHERE r.actual IS NOT NULL"
        params=[]
        if platform:
            where+=" AND p.platform=?"; params.append(platform)
        return self.db.frame(f"""SELECT p.platform,r.metric,
            COUNT(*) AS matched_predictions,
            AVG(r.absolute_error) AS mae_actual,
            AVG(r.percentage_error) AS mape_actual,
            AVG(r.validation_mae) AS validation_mae,
            AVG(r.validation_r2) AS validation_r2
            FROM prediction_metric_results r
            JOIN prediction_runs p ON p.id=r.prediction_id
            {where}
            GROUP BY p.platform,r.metric
            ORDER BY p.platform,r.metric""",params)

    def diagnostics(self):
        return self.db.frame("""SELECT p.id,p.created_at,p.platform,p.model_name,
            r.metric,r.estimate,r.low,r.high,r.validation_mae,r.validation_rmse,
            r.validation_r2,r.training_rows,r.actual,r.absolute_error,
            r.percentage_error,r.matched_at
            FROM prediction_runs p
            JOIN prediction_metric_results r ON r.prediction_id=p.id
            ORDER BY p.created_at DESC,r.metric""")

    def history(self):
        return self.db.frame("""SELECT p.id,p.created_at,p.platform,p.model_name,
            p.inputs_json,p.outputs_json,
            SUM(CASE WHEN r.actual IS NOT NULL THEN 1 ELSE 0 END) AS matched_metrics,
            AVG(r.absolute_error) AS actual_mae
            FROM prediction_runs p
            LEFT JOIN prediction_metric_results r ON r.prediction_id=p.id
            GROUP BY p.id ORDER BY p.created_at DESC LIMIT 500""")
