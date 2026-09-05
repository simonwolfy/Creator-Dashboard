from __future__ import annotations

import json

import pytest

from creator_intelligence.data.database import Database
from creator_intelligence.services.import_center import ImportCenterService


def make_service(tmp_path):
    db = Database(tmp_path / "imports.db")
    db.execute(
        """CREATE TABLE twitch_daily(
            date TEXT PRIMARY KEY,
            average_viewers REAL,
            max_viewers INTEGER,
            unique_viewers INTEGER,
            follows INTEGER,
            minutes_streamed INTEGER,
            minutes_watched INTEGER,
            chat_messages INTEGER,
            total_revenue REAL
        )"""
    )
    return ImportCenterService(db)


def staged_row(service, csv_path):
    batch = service.stage(csv_path)
    rows = service.staging_rows(batch["batch_id"])
    assert len(rows) == 1
    return json.loads(rows.iloc[0]["normalized_json"])


def test_twitch_export_revenue_components_are_summed(tmp_path):
    service = make_service(tmp_path)
    csv_path = tmp_path / "twitch-daily.csv"
    csv_path.write_text(
        "Date,Average Viewers,Max Viewers,Minutes Streamed,Sub Revenue,"
        "Prime Revenue,Gifted Subs Revenue,Bits Revenue,Ad Revenue,"
        "Turbo Revenue,Game Sales Revenue,Extensions Revenue,Bounties Revenue,"
        "Experimental Revenue,Other Bits Interactions Revenue\n"
        "Fri Sep 04 2026,3.2,7,800,2.83,0,61.8,0.01,0.07,0.01,0,0,0,0,0\n",
        encoding="utf-8",
    )

    row = staged_row(service, csv_path)

    assert row["total_revenue"] == pytest.approx(64.72)


def test_explicit_twitch_total_revenue_takes_precedence(tmp_path):
    service = make_service(tmp_path)
    csv_path = tmp_path / "twitch-total.csv"
    csv_path.write_text(
        "Date,Average Viewers,Max Viewers,Total Revenue,Sub Revenue,Gifted Subs Revenue\n"
        "Thu Sep 03 2026,4.0,9,9.25,5,6\n",
        encoding="utf-8",
    )

    row = staged_row(service, csv_path)

    assert row["total_revenue"] == pytest.approx(9.25)


def test_corrected_importer_can_reprocess_a_legacy_import(tmp_path):
    service = make_service(tmp_path)
    csv_path = tmp_path / "already-imported.csv"
    csv_path.write_text(
        "Date,Average Viewers,Max Viewers,Minutes Streamed,Sub Revenue,Ad Revenue\n"
        "Wed Sep 02 2026,3.0,8,120,4.5,0.5\n",
        encoding="utf-8",
    )
    file_hash = service._file_hash(csv_path)
    service.db.execute(
        """INSERT INTO import_jobs(
            batch_id,source_path,file_name,file_hash,importer_id,status,started_at
        ) VALUES(?,?,?,?,?,'Completed','2026-09-02T00:00:00')""",
        (
            "legacy-batch",
            str(csv_path),
            csv_path.name,
            file_hash,
            "twitch_daily",
        ),
    )

    inspection = service.inspect_file(csv_path)
    assert inspection["duplicate_file"] is False
    batch = service.stage(csv_path)
    completed = service.commit(batch["batch_id"], archive_source=False)

    assert completed["status"] == "Completed"
    assert service.db.scalar(
        "SELECT total_revenue FROM twitch_daily WHERE date='Wed Sep 02 2026'"
    ) == pytest.approx(5.0)
    assert service.db.scalar(
        "SELECT COUNT(*) FROM import_jobs WHERE status='Superseded'"
    ) == 1


def test_monthly_twitch_revenue_summary_cannot_overwrite_daily_data(tmp_path):
    service = make_service(tmp_path)
    csv_path = tmp_path / "monthly-revenue.csv"
    csv_path.write_text(
        "Date,Ad Breaks (Minutes),Minutes Streamed,Sub Revenue,Ad Revenue,"
        "Gifted Subs Revenue,Total Paid Subs,Total Gifted Subs\n"
        "Sat Aug 01 2026,0,6186,20.8,1.09,51.83,4,23\n",
        encoding="utf-8",
    )

    assert service.detect(csv_path).export_type == "twitch_monthly_revenue"
    with pytest.raises(ValueError, match="monthly Twitch revenue summary"):
        service.stage(csv_path)
