from __future__ import annotations
from datetime import datetime
import json
import math

class HighlightLearningService:
    FEATURE_KEYS = (
        "base_score","confidence","short_format","long_format",
        "boss_fight","death_failure","clutch_escape","rare_loot",
        "funny","scary","raid_community","progression",
        "tutorial","victory","strong_reaction"
    )

    def __init__(self, db, scoring_service=None, notifications=None):
        self.db = db
        self.scoring_service = scoring_service
        self.notifications = notifications
        self._ensure_schema()
        self._seed_weights()

    def _ensure_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS highlight_learning_examples(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                highlight_id INTEGER,
                source_type TEXT NOT NULL,
                outcome_label REAL NOT NULL,
                views REAL DEFAULT 0,
                watch_time_hours REAL DEFAULT 0,
                retention_rate REAL,
                engagement_rate REAL,
                subscribers_gained REAL DEFAULT 0,
                revenue REAL DEFAULT 0,
                editor_approved INTEGER,
                creator_approved INTEGER,
                published INTEGER DEFAULT 0,
                feature_json TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS highlight_feature_weights(
                feature_key TEXT PRIMARY KEY,
                weight REAL NOT NULL,
                sample_count INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS highlight_learning_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                sample_count INTEGER DEFAULT 0,
                learning_rate REAL DEFAULT 0.08,
                regularization REAL DEFAULT 0.01,
                metrics_json TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS highlight_personalized_scores(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                highlight_id INTEGER NOT NULL,
                original_score REAL NOT NULL,
                personalized_score REAL NOT NULL,
                adjustment REAL NOT NULL,
                confidence REAL NOT NULL,
                explanation_json TEXT NOT NULL,
                model_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(highlight_id,model_version)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_learning_examples_highlight
               ON highlight_learning_examples(highlight_id,created_at)""",
            """CREATE INDEX IF NOT EXISTS idx_personalized_scores_highlight
               ON highlight_personalized_scores(highlight_id,created_at)"""
        ]
        for statement in statements:
            self.db.execute(statement)

    def _seed_weights(self):
        now = datetime.now().isoformat()
        defaults = {
            "base_score":0.55,"confidence":0.10,
            "short_format":0.05,"long_format":0.05,
            "boss_fight":0.04,"death_failure":0.04,
            "clutch_escape":0.04,"rare_loot":0.04,
            "funny":0.05,"scary":0.03,
            "raid_community":0.04,"progression":0.04,
            "tutorial":0.02,"victory":0.03,
            "strong_reaction":0.04
        }
        for key,weight in defaults.items():
            self.db.execute(
                """INSERT OR IGNORE INTO highlight_feature_weights(
                    feature_key,weight,sample_count,updated_at
                ) VALUES(?,?,0,?)""",
                (key,float(weight),now)
            )

    def weights(self):
        return self.db.frame(
            """SELECT feature_key,weight,sample_count,updated_at
               FROM highlight_feature_weights ORDER BY feature_key"""
        )

    def _highlight(self, highlight_id):
        if self.scoring_service:
            return self.scoring_service.highlight(highlight_id)
        frame = self.db.frame(
            "SELECT * FROM scored_highlights WHERE id=?",
            (int(highlight_id),)
        )
        if frame.empty:
            raise KeyError(highlight_id)
        return frame.iloc[0].to_dict()

    def features_for_highlight(self, highlight_id):
        row = self._highlight(highlight_id)
        categories = json.loads(row.get("categories_json") or "[]")
        category_map = {
            "Boss Fight":"boss_fight",
            "Death / Failure":"death_failure",
            "Clutch / Escape":"clutch_escape",
            "Rare Loot":"rare_loot",
            "Funny":"funny",
            "Scary / Jump Scare":"scary",
            "Raid / Community":"raid_community",
            "Progression":"progression",
            "Tutorial / Explanation":"tutorial",
            "Victory / Achievement":"victory",
            "Strong Reaction":"strong_reaction"
        }
        output = str(row.get("recommended_output") or "")
        features = {key:0.0 for key in self.FEATURE_KEYS}
        features["base_score"] = float(
            row.get("override_score") or row.get("score") or 0
        ) / 100.0
        features["confidence"] = float(row.get("confidence") or 0)
        features["short_format"] = 1.0 if "Short" in output or "TikTok" in output else 0.0
        features["long_format"] = 1.0 if "long-form" in output.lower() else 0.0
        for category in categories:
            key = category_map.get(category)
            if key:
                features[key] = 1.0
        return features

    def add_review_feedback(
        self, highlight_id, approved, editor_approved=None, notes=None
    ):
        outcome = 1.0 if approved else 0.0
        features = self.features_for_highlight(highlight_id)
        return self._insert_example(
            highlight_id=highlight_id,
            source_type="review",
            outcome_label=outcome,
            feature_json=features,
            creator_approved=int(bool(approved)),
            editor_approved=(
                None if editor_approved is None
                else int(bool(editor_approved))
            ),
            notes=notes
        )

    def add_performance_feedback(
        self, highlight_id, views=0, watch_time_hours=0,
        retention_rate=None, engagement_rate=None,
        subscribers_gained=0, revenue=0, published=True, notes=None
    ):
        outcome = self._performance_outcome(
            views,retention_rate,engagement_rate,subscribers_gained
        )
        features = self.features_for_highlight(highlight_id)
        return self._insert_example(
            highlight_id=highlight_id,
            source_type="published_performance",
            outcome_label=outcome,
            views=views,
            watch_time_hours=watch_time_hours,
            retention_rate=retention_rate,
            engagement_rate=engagement_rate,
            subscribers_gained=subscribers_gained,
            revenue=revenue,
            published=int(bool(published)),
            feature_json=features,
            notes=notes
        )

    def _performance_outcome(
        self, views, retention_rate, engagement_rate, subscribers_gained
    ):
        view_component = min(1.0,math.log10(max(float(views),1))/5.0)
        retention_component = min(1.0,max(0.0,float(retention_rate or 0)))
        engagement_component = min(1.0,max(0.0,float(engagement_rate or 0)*8))
        subscriber_component = min(1.0,math.log10(max(float(subscribers_gained),1))/3.0)
        return max(0.0,min(1.0,
            view_component*0.35 +
            retention_component*0.30 +
            engagement_component*0.20 +
            subscriber_component*0.15
        ))

    def _insert_example(self, **values):
        now = datetime.now().isoformat()
        columns = [
            "highlight_id","source_type","outcome_label","views",
            "watch_time_hours","retention_rate","engagement_rate",
            "subscribers_gained","revenue","editor_approved",
            "creator_approved","published","feature_json","notes"
        ]
        payload = []
        for column in columns:
            value = values.get(column)
            if column == "feature_json":
                value = json.dumps(value or {})
            payload.append(value)
        return int(self.db.execute(
            f"""INSERT INTO highlight_learning_examples(
                {",".join(columns)},created_at
            ) VALUES({",".join("?" for _ in columns)},?)""",
            payload+[now]
        ))

    def examples(self):
        return self.db.frame(
            """SELECT id,highlight_id,source_type,outcome_label,views,
               retention_rate,engagement_rate,subscribers_gained,
               editor_approved,creator_approved,published,created_at
               FROM highlight_learning_examples ORDER BY created_at DESC"""
        )

    def train(self, learning_rate=0.08, regularization=0.01, epochs=120):
        examples = self.db.frame(
            "SELECT * FROM highlight_learning_examples ORDER BY id"
        )
        started = datetime.now().isoformat()
        run_id = int(self.db.execute(
            """INSERT INTO highlight_learning_runs(
                status,sample_count,learning_rate,regularization,started_at
            ) VALUES(?,?,?,?,?)""",
            ("Running",len(examples),float(learning_rate),
             float(regularization),started)
        ))
        try:
            if examples.empty:
                raise ValueError("At least one feedback example is required.")
            weights = {
                row["feature_key"]:float(row["weight"])
                for _,row in self.weights().iterrows()
            }
            before_loss = self._loss(examples,weights)
            for _ in range(int(epochs)):
                gradients = {key:0.0 for key in weights}
                for _,row in examples.iterrows():
                    features = json.loads(row["feature_json"] or "{}")
                    target = float(row["outcome_label"])
                    prediction = self._predict(features,weights)
                    error = prediction-target
                    for key in gradients:
                        gradients[key] += error*float(features.get(key,0))
                count = max(1,len(examples))
                for key in weights:
                    gradient = gradients[key]/count + regularization*weights[key]
                    weights[key] -= learning_rate*gradient
                    weights[key] = max(-1.5,min(1.5,weights[key]))

            after_loss = self._loss(examples,weights)
            now = datetime.now().isoformat()
            for key,weight in weights.items():
                self.db.execute(
                    """UPDATE highlight_feature_weights SET weight=?,
                       sample_count=?,updated_at=? WHERE feature_key=?""",
                    (float(weight),len(examples),now,key)
                )
            metrics = {
                "before_loss":before_loss,
                "after_loss":after_loss,
                "improvement":before_loss-after_loss,
                "sample_count":len(examples),
                "epochs":int(epochs)
            }
            self.db.execute(
                """UPDATE highlight_learning_runs SET status='Completed',
                   metrics_json=?,completed_at=? WHERE id=?""",
                (json.dumps(metrics),now,run_id)
            )
            if self.notifications:
                self.notifications.create(
                    "Model","Success","Highlight learning complete",
                    f'{len(examples)} feedback examples updated personalized scoring.',
                    "highlight_learning_run",run_id
                )
            return metrics
        except Exception as exc:
            self.db.execute(
                """UPDATE highlight_learning_runs SET status='Failed',
                   error_message=?,completed_at=? WHERE id=?""",
                (str(exc),datetime.now().isoformat(),run_id)
            )
            raise

    def _predict(self, features, weights):
        raw = sum(
            float(weights.get(key,0))*float(features.get(key,0))
            for key in weights
        )
        return 1/(1+math.exp(-max(-20,min(20,raw))))

    def _loss(self, examples, weights):
        total = 0.0
        for _,row in examples.iterrows():
            target = float(row["outcome_label"])
            prediction = min(
                1-1e-9,max(1e-9,
                    self._predict(json.loads(row["feature_json"] or "{}"),weights)
                )
            )
            total += -(target*math.log(prediction)+(1-target)*math.log(1-prediction))
        return total/max(1,len(examples))

    def personalize(self, highlight_id):
        row = self._highlight(highlight_id)
        features = self.features_for_highlight(highlight_id)
        weights = {
            item["feature_key"]:float(item["weight"])
            for _,item in self.weights().iterrows()
        }
        learned_probability = self._predict(features,weights)
        original = float(row.get("override_score") or row.get("score") or 0)
        personalized = max(0,min(100,
            original*0.55 + learned_probability*100*0.45
        ))
        contributions = {
            key:round(float(features.get(key,0))*float(weights.get(key,0))*100,3)
            for key in weights
            if float(features.get(key,0)) != 0
        }
        sample_count = int(
            self.db.frame(
                "SELECT COUNT(*) AS c FROM highlight_learning_examples"
            ).iloc[0]["c"]
        )
        confidence = min(0.95,0.35+math.log10(max(sample_count,1)+1)*0.25)
        version = self.model_version()
        now = datetime.now().isoformat()
        self.db.execute(
            """INSERT OR REPLACE INTO highlight_personalized_scores(
                highlight_id,original_score,personalized_score,adjustment,
                confidence,explanation_json,model_version,created_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                int(highlight_id),original,personalized,personalized-original,
                confidence,json.dumps({
                    "learned_probability":learned_probability,
                    "contributions":contributions,
                    "sample_count":sample_count
                }),version,now
            )
        )
        return self.db.frame(
            """SELECT * FROM highlight_personalized_scores
               WHERE highlight_id=? AND model_version=?""",
            (int(highlight_id),version)
        ).iloc[0].to_dict()

    def personalize_all(self, transcript_id=None):
        sql = "SELECT id FROM scored_highlights"
        params = []
        if transcript_id is not None:
            sql += " WHERE transcript_id=?"
            params.append(int(transcript_id))
        ids = self.db.frame(sql,params)["id"].tolist()
        return [self.personalize(int(highlight_id)) for highlight_id in ids]

    def personalized_scores(self, transcript_id=None):
        sql = """SELECT p.*,h.transcript_id,h.title,h.primary_category,
                 h.recommended_output,h.review_status
                 FROM highlight_personalized_scores p
                 JOIN scored_highlights h ON h.id=p.highlight_id"""
        params = []
        if transcript_id is not None:
            sql += " WHERE h.transcript_id=?"
            params.append(int(transcript_id))
        sql += " ORDER BY p.personalized_score DESC,p.created_at DESC"
        return self.db.frame(sql,params)

    def model_version(self):
        weights = self.weights()
        signature = "|".join(
            f'{row["feature_key"]}:{float(row["weight"]):.6f}:{int(row["sample_count"])}'
            for _,row in weights.iterrows()
        )
        return str(abs(hash(signature)))

    def runs(self):
        return self.db.frame(
            """SELECT * FROM highlight_learning_runs
               ORDER BY started_at DESC"""
        )

    def insights(self):
        weights = self.weights().copy()
        weights["absolute_weight"] = weights["weight"].abs()
        strongest = weights.sort_values(
            "absolute_weight",ascending=False
        ).head(8)
        examples = self.examples()
        return {
            "feedback_examples":len(examples),
            "review_examples":int(
                (examples["source_type"]=="review").sum()
            ) if not examples.empty else 0,
            "performance_examples":int(
                (examples["source_type"]=="published_performance").sum()
            ) if not examples.empty else 0,
            "strongest_features":strongest[
                ["feature_key","weight","sample_count"]
            ].to_dict("records")
        }
