from __future__ import annotations
from datetime import datetime, timedelta
import json
import itertools
import pandas as pd

class RecommendationService:
    def __init__(self, db, predictions):
        self.db=db
        self.predictions=predictions

    def _score(self,outputs,objective,platform):
        estimates={k:v.get("estimate",0) for k,v in outputs.items()}
        if platform=="Twitch":
            weights={
                "Viewers":{"average_viewers":0.55,"unique_viewers":0.25,"watch_hours":0.20},
                "Followers":{"follows":0.70,"average_viewers":0.15,"watch_hours":0.15},
                "Revenue":{"revenue":0.75,"watch_hours":0.15,"average_viewers":0.10},
                "Balanced":{"average_viewers":0.25,"unique_viewers":0.15,"follows":0.25,
                            "watch_hours":0.15,"revenue":0.20},
            }[objective]
        else:
            weights={
                "Views":{"views":0.70,"engaged_views":0.20,"watch_hours":0.10},
                "Subscribers":{"subscribers_gained":0.70,"views":0.15,"watch_hours":0.15},
                "Engagement":{"likes":0.35,"comments":0.25,"engaged_views":0.40},
                "Balanced":{"views":0.30,"watch_hours":0.20,"subscribers_gained":0.25,
                            "likes":0.15,"comments":0.10},
            }[objective]
        return sum(estimates.get(k,0)*w for k,w in weights.items())

    def recommend_twitch(self,objective="Balanced",games=None,days=7):
        games=games or ["Unknown"]
        today=pd.Timestamp.today().date()
        plans=[]
        for offset,hour,duration,game in itertools.product(
            range(1,days+1),[6,9,12,15,17,19,21],[3,4,5,6,8],games
        ):
            planned=today+timedelta(days=offset)
            outputs,_=self.predictions.predict_twitch(
                planned,duration,hour,"Normal",game,game,0,False,save=False
            )
            plans.append({
                "platform":"Twitch","objective":objective,
                "plan":{"date":str(planned),"start_hour":hour,"duration_hours":duration,
                        "starting_game":game,"ending_game":game},
                "prediction":outputs,
                "score":self._score(outputs,objective,"Twitch")
            })
        return self._save_ranked(plans,"Twitch",objective)

    def recommend_youtube(self,objective="Balanced",topics=None):
        topics=topics or ["Untagged"]
        plans=[]
        for fmt,day,hour,duration,title_len,topic in itertools.product(
            ["Short","Video"],
            ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
            [6,9,12,15,18,21],
            [30,45,60] if True else [300],
            [35,45,55,65],
            topics
        ):
            duration = duration if fmt=="Short" else max(300,duration*10)
            outputs,_=self.predictions.predict_youtube(
                fmt,day,duration,title_len,1000,hour,topic,save=False
            )
            plans.append({
                "platform":"YouTube","objective":objective,
                "plan":{"format":fmt,"weekday":day,"publish_hour":hour,
                        "duration_seconds":duration,"title_length":title_len,"game_topic":topic},
                "prediction":outputs,
                "score":self._score(outputs,objective,"YouTube")
            })
        return self._save_ranked(plans,"YouTube",objective)

    def _save_ranked(self,plans,platform,objective):
        ranked=sorted(plans,key=lambda x:x["score"],reverse=True)[:25]
        run_id=self.db.execute("""INSERT INTO recommendation_runs
            (created_at,objective,recommendations_json) VALUES(?,?,?)""",
            (datetime.now().isoformat(),f"{platform}:{objective}",json.dumps(ranked,default=str)))
        for rank,item in enumerate(ranked,1):
            self.db.execute("""INSERT INTO recommendation_candidates
                (recommendation_run_id,rank,platform,objective,plan_json,prediction_json,score,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",(
                    run_id,rank,platform,objective,json.dumps(item["plan"]),
                    json.dumps(item["prediction"],default=str),item["score"],datetime.now().isoformat()
                ))
            item["rank"]=rank
            item["run_id"]=run_id
        return ranked

    def history(self):
        return self.db.frame("""SELECT id,created_at,objective,recommendations_json
            FROM recommendation_runs ORDER BY created_at DESC LIMIT 100""")
