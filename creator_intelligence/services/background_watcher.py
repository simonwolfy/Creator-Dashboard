from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import threading
import time

@dataclass
class WatcherSettings:
    interval_seconds: int = 60
    auto_commit: bool = False
    enabled: bool = True

class BackgroundWatcherService:
    def __init__(self, db, import_center, notifications):
        self.db=db
        self.import_center=import_center
        self.notifications=notifications
        self._thread=None
        self._stop_event=threading.Event()
        self._lock=threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS watcher_settings(
            id INTEGER PRIMARY KEY CHECK(id=1),
            enabled INTEGER DEFAULT 1,
            interval_seconds INTEGER DEFAULT 60,
            auto_commit INTEGER DEFAULT 0,
            last_started_at TEXT,
            last_stopped_at TEXT,
            last_cycle_at TEXT,
            last_error TEXT
        )""")
        self.db.execute("""INSERT OR IGNORE INTO watcher_settings(
            id,enabled,interval_seconds,auto_commit
        ) VALUES(1,1,60,0)""")

    def settings(self):
        frame=self.db.frame("SELECT * FROM watcher_settings WHERE id=1")
        row=frame.iloc[0]
        return WatcherSettings(
            enabled=bool(row["enabled"]),
            interval_seconds=max(10,int(row["interval_seconds"] or 60)),
            auto_commit=bool(row["auto_commit"])
        )

    def update_settings(self,enabled=None,interval_seconds=None,auto_commit=None):
        current=self.settings()
        self.db.execute("""UPDATE watcher_settings SET
            enabled=?,interval_seconds=?,auto_commit=? WHERE id=1""",(
            int(current.enabled if enabled is None else bool(enabled)),
            max(10,int(current.interval_seconds if interval_seconds is None else interval_seconds)),
            int(current.auto_commit if auto_commit is None else bool(auto_commit))
        ))

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.is_running():
            return False
        settings=self.settings()
        if not settings.enabled:
            return False
        self._stop_event.clear()
        self._thread=threading.Thread(
            target=self._run_loop,
            name="CreatorIntelligenceImportWatcher",
            daemon=True
        )
        self._thread.start()
        self.db.execute("""UPDATE watcher_settings SET last_started_at=?,
            last_error=NULL WHERE id=1""",(datetime.now().isoformat(),))
        self.notifications.create(
            "System","Info","Background watcher started",
            f"Watched folders will be checked every {settings.interval_seconds} seconds.",
            "watcher","main"
        )
        return True

    def stop(self,wait_seconds=3):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=wait_seconds)
        self.db.execute("""UPDATE watcher_settings SET last_stopped_at=?
            WHERE id=1""",(datetime.now().isoformat(),))
        return True

    def run_cycle(self):
        if not self._lock.acquire(blocking=False):
            return []
        try:
            settings=self.settings()
            folders=self.import_center.watch_folders()
            all_results=[]
            for _,folder in folders.iterrows():
                if not bool(folder["enabled"]):
                    continue
                try:
                    results=self.import_center.scan_watch_folder(
                        int(folder["id"]),
                        auto_commit=settings.auto_commit
                    )
                    for result in results:
                        result["watch_folder_id"]=int(folder["id"])
                        all_results.append(result)
                        if result.get("status") in {
                            "Completed","Completed with warnings",
                            "Already imported","Failed"
                        }:
                            self.notifications.emit_import_result(result)
                        elif result.get("status")=="Ready":
                            self.notifications.create(
                                "Import","Info","Import ready for review",
                                f'{Path(result["file"]).name} was staged and is ready to commit.',
                                "import_batch",result.get("batch_id"),
                                "Review staged import",{"batch_id":result.get("batch_id")}
                            )
                except Exception as exc:
                    all_results.append({
                        "folder":str(folder["path"]),
                        "status":"Failed",
                        "error":str(exc)
                    })
                    self.notifications.create(
                        "Import","Error","Watched folder scan failed",
                        f'{folder["path"]}: {exc}',
                        "watch_folder",folder["id"]
                    )
            self.notifications.generate_operational_alerts()
            self.db.execute("""UPDATE watcher_settings SET last_cycle_at=?,
                last_error=NULL WHERE id=1""",(datetime.now().isoformat(),))
            return all_results
        except Exception as exc:
            self.db.execute("""UPDATE watcher_settings SET last_cycle_at=?,
                last_error=? WHERE id=1""",
                (datetime.now().isoformat(),str(exc))
            )
            self.notifications.create(
                "System","Error","Background watcher cycle failed",
                str(exc),"watcher","main"
            )
            return [{"status":"Failed","error":str(exc)}]
        finally:
            self._lock.release()

    def _run_loop(self):
        while not self._stop_event.is_set():
            settings=self.settings()
            if settings.enabled:
                self.run_cycle()
            self._stop_event.wait(max(10,settings.interval_seconds))

    def status(self):
        frame=self.db.frame("SELECT * FROM watcher_settings WHERE id=1")
        row=frame.iloc[0].to_dict()
        row["running"]=self.is_running()
        return row
