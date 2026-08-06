from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from creator_intelligence.services.packaging_review import PackagingReviewService
from creator_intelligence.services.publishing_planner import PublishingPlannerService
from creator_intelligence.services.social_platforms import SocialPlatformService


class DB:
    def __init__(self,path):self.connection=sqlite3.connect(str(path))
    def execute(self,sql,params=()):
        cursor=self.connection.execute(sql,tuple(params));self.connection.commit();return cursor.lastrowid
    def frame(self,sql,params=()):return pd.read_sql_query(sql,self.connection,params=tuple(params))


class Transcripts:
    def __init__(self):self.regenerated=[]
    def analyze_clip_candidate(self,clip_id):self.regenerated.append(clip_id);return {"id":clip_id,"fresh":True}


def setup(tmp_path,platform="youtube",title="Can They Wear Pants?"):
    db=DB(tmp_path/"review.db");SocialPlatformService(db)
    db.execute("CREATE TABLE transcripts(id INTEGER PRIMARY KEY,title TEXT,source_path TEXT)")
    db.execute("""CREATE TABLE transcript_segments(id INTEGER PRIMARY KEY,transcript_id INTEGER,
        start_seconds REAL,end_seconds REAL,text TEXT)""")
    db.execute("""CREATE TABLE transcript_clip_candidates(id INTEGER PRIMARY KEY,transcript_id INTEGER,
        start_seconds REAL,end_seconds REAL,title TEXT)""")
    db.execute("INSERT INTO transcripts VALUES(1,'Stream','C:/missing/video.mp4')")
    db.execute("INSERT INTO transcript_segments VALUES(1,1,10,20,'Can colonists even wear pants?')")
    db.execute("INSERT INTO transcript_clip_candidates VALUES(5,1,10,20,'Pants debate')")
    transcripts=Transcripts();planner=PublishingPlannerService(db)
    package_id=planner.outcomes.snapshot_packages(5,{platform:{
        "title":title if platform in {"youtube","twitch"} else None,
        "caption":title if platform in {"tiktok","instagram"} else None,
        "description":"A strange discussion","hook":"Wait, what?","hashtags":["#Gaming"]}},
        {"topic":"RimWorld","clip_type":"Funny discussion"},"High",80)[platform]
    return db,planner,PackagingReviewService(db,planner,transcripts),transcripts,package_id


def test_review_detail_combines_package_transcript_and_validation(tmp_path):
    _,planner,service,_,package_id=setup(tmp_path)
    planner.experiments.ensure_for_package(package_id,{"title":"Can They Wear Pants?"},["Can They Wear Pants?","We Debated Pants"])
    detail=service.detail(package_id)
    assert detail["transcript"]=="Can colonists even wear pants?"
    assert len(detail["variants"])>=2
    assert detail["validation"]["valid"] is True
    assert service.queue().iloc[0]["review_copy"]=="Can They Wear Pants?"


def test_edits_are_validated_and_original_ai_copy_is_preserved(tmp_path):
    _,planner,service,_,package_id=setup(tmp_path)
    edits={"title":"We Somehow Debated Pants","description":"Final description",
           "hook":"This got weird","hashtags":["#RimWorld"]}
    service.approve(package_id,edits)
    package=planner.outcomes.package(package_id)
    assert package["generated_title"]=="Can They Wear Pants?"
    assert package["used_title"]=="We Somehow Debated Pants"
    assert package["edit_status"]=="Edited"
    assert package["decision_status"]=="Approved"


def test_platform_limits_and_hashtags_block_approval(tmp_path):
    _,_,service,_,package_id=setup(tmp_path,title="X"*101)
    result=service.validate(package_id,{"hashtags":["Gaming"]})
    assert result["valid"] is False
    assert any("character limit" in issue for issue in result["issues"])
    assert any("begin with #" in issue for issue in result["issues"])
    with pytest.raises(ValueError):service.approve(package_id,{"hashtags":["Gaming"]})


def test_approved_package_handoff_is_idempotent(tmp_path):
    db,_,service,_,package_id=setup(tmp_path)
    service.approve(package_id)
    first=service.send_to_publishing(package_id);second=service.send_to_publishing(package_id)
    assert first==second
    row=db.frame("SELECT * FROM publishing_items WHERE id=?",(first,)).iloc[0]
    assert row["status"]=="Ready"
    assert row["platform"]=="YouTube Shorts"


def test_bulk_review_export_and_regeneration(tmp_path):
    _,planner,service,transcripts,package_id=setup(tmp_path)
    second=planner.outcomes.snapshot_packages(5,{"tiktok":{"caption":"This got weird","hashtags":["#Gaming"]}},
        {},"Moderate",60)["tiktok"]
    result=service.bulk_approve([package_id,second])
    assert len(result["approved"])==2
    payload=service.export_payload([package_id,second])
    assert {item["platform"] for item in payload}=={"youtube","tiktok"}
    fresh=service.regenerate(package_id)
    assert fresh["fresh"] is True
    assert transcripts.regenerated==[5]
    assert planner.outcomes.package(package_id)["decision_status"]=="Rejected"


def test_applying_alternative_requires_separate_explicit_approval(tmp_path):
    _,planner,service,_,package_id=setup(tmp_path)
    experiment_id=planner.experiments.ensure_for_package(
        package_id,{"title":"Can They Wear Pants?"},
        ["Can They Wear Pants?","We Somehow Debated Pants"])
    variants=planner.experiments.variants(experiment_id)
    variant_id=str(variants[variants["title"]=="We Somehow Debated Pants"].iloc[0]["id"])

    service.apply_variant(package_id,variant_id)
    applied=planner.outcomes.package(package_id)
    assert applied["used_title"]=="We Somehow Debated Pants"
    assert applied["decision_status"]=="Generated"

    service.approve(package_id)
    assert planner.outcomes.package(package_id)["decision_status"]=="Approved"

    service.save_edits(package_id,{"title":"A Final Manual Edit"})
    edited=planner.outcomes.package(package_id)
    assert edited["used_title"]=="A Final Manual Edit"
    assert edited["decision_status"]=="Generated"
    with pytest.raises(ValueError):service.send_to_publishing(package_id)
