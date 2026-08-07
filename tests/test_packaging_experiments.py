from __future__ import annotations

import sqlite3
import pandas as pd

from creator_intelligence.services.packaging_experiments import PackagingExperimentService
from creator_intelligence.services.publishing_outcomes import PublishingOutcomeService
from creator_intelligence.services.social_platforms import SocialPlatformService


class DB:
    def __init__(self, path): self.connection=sqlite3.connect(str(path))
    def execute(self,sql,params=()):
        cursor=self.connection.execute(sql,tuple(params)); self.connection.commit(); return cursor.lastrowid
    def frame(self,sql,params=()): return pd.read_sql_query(sql,self.connection,params=tuple(params))


def setup(tmp_path):
    db=DB(tmp_path/"experiments.db"); SocialPlatformService(db)
    outcomes=PublishingOutcomeService(db); experiments=PackagingExperimentService(db,outcomes)
    package_id=outcomes.snapshot_packages(11,{"youtube_shorts":{
        "title":"Can They Wear Pants?","description":"A strange RimWorld debate","hook":"Wait, what?",
        "hashtags":["#RimWorld"]}}, {"topic":"RimWorld","clip_type":"Funny discussion"},"High",78)["youtube_shorts"]
    return db,outcomes,experiments,package_id


def variants():
    return [
        {"label":"Question","title":"Can They Wear Pants?"},
        {"label":"Story","title":"We Somehow Debated Pants"},
        {"label":"Direct","title":"The RimWorld Pants Debate"},
    ]


def test_experiment_recommends_without_claiming_high_confidence(tmp_path):
    _,_,service,package_id=setup(tmp_path)
    experiment_id=service.create(package_id,variants())
    experiment=service.experiment(experiment_id)
    frame=service.variants(experiment_id)
    assert len(frame)==3
    assert experiment["recommended_variant_id"] in frame["id"].tolist()
    assert experiment["recommendation_confidence"]=="Low"
    assert "duplicate" in frame.iloc[0]["recommendation_reason"]


def test_selecting_variant_records_exact_used_copy_without_mutating_snapshot(tmp_path):
    _,outcomes,service,package_id=setup(tmp_path)
    experiment_id=service.create(package_id,variants())
    selected=service.variants(experiment_id).iloc[1]
    service.select(selected["id"])
    package=outcomes.package(package_id)
    assert package["generated_title"]=="Can They Wear Pants?"
    assert package["used_title"]==selected["title"]
    assert package["decision_status"]=="Approved"
    assert package["edit_status"] in {"Edited","Unchanged"}


def test_winner_requires_three_mature_results_and_meaningful_lead(tmp_path):
    _,_,service,package_id=setup(tmp_path)
    experiment_id=service.create(package_id,variants())
    rows=service.variants(experiment_id).to_dict("records")
    service.record_result(rows[0]["id"],{"views":10000,"likes":1000,"comments":100,"shares":100},168)
    service.record_result(rows[1]["id"],{"views":5000,"likes":250,"comments":20,"shares":10},168)
    assert service.experiment(experiment_id)["result_confidence"]=="Insufficient"
    service.record_result(rows[2]["id"],{"views":2000,"likes":50,"comments":5,"shares":2},168)
    result=service.experiment(experiment_id)
    assert result["status"]=="Completed"
    assert result["winner_variant_id"]==rows[0]["id"]
    assert result["result_confidence"]=="Medium"


def test_close_results_are_reported_as_inconclusive(tmp_path):
    _,_,service,package_id=setup(tmp_path)
    experiment_id=service.create(package_id,variants())
    for row,views in zip(service.variants(experiment_id).to_dict("records"),(1000,1050,1100)):
        service.record_result(row["id"],{"views":views,"likes":100},24)
    result=service.experiment(experiment_id)
    assert result["status"]=="Inconclusive"
    assert result["winner_variant_id"] is None


def test_auto_generated_experiment_has_distinct_variants(tmp_path):
    _,_,service,package_id=setup(tmp_path)
    experiment_id=service.ensure_for_package(package_id,{"title":"Can They Wear Pants?"},[
        "Can They Wear Pants?","We Somehow Debated Pants","The Pants Question Got Weird"])
    frame=service.variants(experiment_id)
    assert 3 <= len(frame) <= 4
    assert frame["title"].nunique()==len(frame)
