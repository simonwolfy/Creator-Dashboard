from __future__ import annotations
from datetime import datetime
from creator_intelligence.repositories.base import BaseRepository

class GoalsRepository(BaseRepository):
    def upsert(self, period, metric, target, platform):
        self.db.execute(
            """INSERT INTO creator_goals(period,metric,target,platform,created_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(period,metric,platform)
               DO UPDATE SET target=excluded.target""",
            (period, metric, float(target), platform, datetime.now().isoformat())
        )

    def list(self):
        return self.db.frame(
            "SELECT * FROM creator_goals ORDER BY period DESC, platform, metric"
        )

    def delete(self, goal_id):
        self.db.execute("DELETE FROM creator_goals WHERE id=?", (int(goal_id),))
