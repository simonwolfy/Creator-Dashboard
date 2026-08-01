from __future__ import annotations

class BaseRepository:
    def __init__(self, db):
        self.db = db
