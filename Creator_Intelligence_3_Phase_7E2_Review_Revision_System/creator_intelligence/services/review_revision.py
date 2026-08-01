from __future__ import annotations
from datetime import datetime
import json

REVIEW_STATES = [
    "Draft","Needs review","Revision requested","Revision in progress",
    "Revision submitted","Approved","Ready to publish","Published"
]
COMMENT_CATEGORIES = [
    "Pacing","Audio","Video","Subtitle","Thumbnail","Music","Meme",
    "Crop","Transition","Color","AI suggestion","General"
]

class ReviewRevisionService:
    def __init__(self, db, production=None, editor_workspace=None, notifications=None):
        self.db=db; self.production=production; self.editor_workspace=editor_workspace
        self.notifications=notifications; self._ensure_schema()

    def _ensure_schema(self):
        for sql in [
            """CREATE TABLE IF NOT EXISTS review_versions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER NOT NULL,
                production_project_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                parent_version_id INTEGER,
                version_label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Draft',
                file_location TEXT,
                thumbnail_location TEXT,
                duration_seconds REAL,
                file_size_mb REAL,
                width INTEGER,height INTEGER,frame_rate REAL,
                export_preset TEXT,change_summary TEXT,editor_notes TEXT,
                submitted_by TEXT,submitted_at TEXT,review_started_at TEXT,
                reviewed_at TEXT,approved_at TEXT,published_at TEXT,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                UNIQUE(workspace_project_id,version_number)
            )""",
            """CREATE TABLE IF NOT EXISTS review_comments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER NOT NULL,
                version_id INTEGER NOT NULL,
                parent_comment_id INTEGER,
                timestamp_seconds REAL,
                frame_number INTEGER,
                category TEXT NOT NULL DEFAULT 'General',
                priority TEXT NOT NULL DEFAULT 'Normal',
                author_role TEXT NOT NULL,
                author_name TEXT,
                body TEXT NOT NULL,
                assigned_to TEXT,
                status TEXT NOT NULL DEFAULT 'Open',
                resolution_note TEXT,
                created_at TEXT NOT NULL,resolved_at TEXT,updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS revision_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER NOT NULL,
                source_version_id INTEGER NOT NULL,
                target_version_id INTEGER,
                request_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                reason TEXT,
                priority TEXT DEFAULT 'Normal',
                due_at TEXT,status TEXT DEFAULT 'Open',
                requested_by TEXT,assigned_editor_id INTEGER,
                created_at TEXT NOT NULL,started_at TEXT,submitted_at TEXT,
                completed_at TEXT,updated_at TEXT NOT NULL,
                UNIQUE(workspace_project_id,request_number)
            )""",
            """CREATE TABLE IF NOT EXISTS revision_request_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                revision_request_id INTEGER NOT NULL,
                comment_id INTEGER,
                timestamp_seconds REAL,
                instruction TEXT NOT NULL,
                status TEXT DEFAULT 'Open',
                editor_response TEXT,completed_at TEXT,created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS review_approval_checks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER NOT NULL,
                version_id INTEGER NOT NULL,
                check_key TEXT NOT NULL,label TEXT NOT NULL,
                required INTEGER DEFAULT 1,status TEXT DEFAULT 'Open',
                notes TEXT,checked_by TEXT,checked_at TEXT,created_at TEXT NOT NULL,
                UNIQUE(version_id,check_key)
            )""",
            """CREATE TABLE IF NOT EXISTS thumbnail_versions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                file_location TEXT NOT NULL,
                label TEXT,status TEXT DEFAULT 'Candidate',favorite INTEGER DEFAULT 0,
                notes TEXT,created_at TEXT NOT NULL,approved_at TEXT,
                UNIQUE(workspace_project_id,version_number)
            )""",
            """CREATE TABLE IF NOT EXISTS review_activity(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_project_id INTEGER,version_id INTEGER,
                action_type TEXT NOT NULL,detail_json TEXT,created_at TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_review_versions_project ON review_versions(workspace_project_id,version_number DESC)",
            "CREATE INDEX IF NOT EXISTS idx_review_comments_version ON review_comments(version_id,status,timestamp_seconds)",
            "CREATE INDEX IF NOT EXISTS idx_revision_requests_project ON revision_requests(workspace_project_id,status,due_at)"
        ]: self.db.execute(sql)

    def create_version(self, workspace_id, file_location=None, label=None, change_summary=None,
                       editor_notes=None, duration_seconds=None, file_size_mb=None,
                       width=None,height=None,frame_rate=None,export_preset=None,submitted_by='Editor'):
        ws=self.editor_workspace.workspace_project(workspace_id) if self.editor_workspace else None
        if not ws: raise ValueError('Editor Workspace project is required.')
        latest=self.db.frame('SELECT MAX(version_number) AS n FROM review_versions WHERE workspace_project_id=?',(int(workspace_id),))
        n=int(latest.iloc[0]['n'] or 0)+1
        parent=self.latest_version(workspace_id)
        now=datetime.now().isoformat()
        vid=int(self.db.execute("""INSERT INTO review_versions(
            workspace_project_id,production_project_id,version_number,parent_version_id,
            version_label,status,file_location,duration_seconds,file_size_mb,width,height,
            frame_rate,export_preset,change_summary,editor_notes,submitted_by,submitted_at,
            created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(workspace_id),int(ws['production_project_id']),n,parent['id'] if parent else None,
             label or f'Version {n}','Needs review',file_location,duration_seconds,file_size_mb,
             width,height,frame_rate,export_preset,change_summary,editor_notes,submitted_by,now,now,now)))
        self._seed_checks(workspace_id,vid)
        self.db.execute("UPDATE editor_workspace_projects SET workspace_status='Ready for creator review',updated_at=? WHERE id=?",(now,int(workspace_id)))
        if self.production: self.production.update_project(ws['production_project_id'],status='Ready for review',progress_percent=75)
        self._log(workspace_id,vid,'version_created',{'version_number':n})
        return self.version(vid)

    def version(self,version_id):
        f=self.db.frame('SELECT * FROM review_versions WHERE id=?',(int(version_id),))
        if f.empty: raise KeyError(version_id)
        return f.iloc[0].to_dict()

    def latest_version(self,workspace_id):
        f=self.db.frame('SELECT * FROM review_versions WHERE workspace_project_id=? ORDER BY version_number DESC LIMIT 1',(int(workspace_id),))
        return f.iloc[0].to_dict() if not f.empty else None

    def versions(self,workspace_id=None):
        sql='SELECT * FROM review_versions'; p=[]
        if workspace_id is not None: sql+=' WHERE workspace_project_id=?'; p=[int(workspace_id)]
        return self.db.frame(sql+' ORDER BY workspace_project_id,version_number DESC',p)

    def compare_versions(self,left_id,right_id):
        left=self.version(left_id); right=self.version(right_id)
        fields=['duration_seconds','file_size_mb','width','height','frame_rate','export_preset','status','change_summary']
        return [{'field':k,'left':left.get(k),'right':right.get(k),'changed':left.get(k)!=right.get(k)} for k in fields]

    def add_comment(self,workspace_id,version_id,body,timestamp_seconds=None,frame_number=None,
                    category='General',priority='Normal',author_role='Creator',author_name=None,
                    assigned_to='Editor',parent_comment_id=None):
        if category not in COMMENT_CATEGORIES: category='General'
        now=datetime.now().isoformat()
        cid=int(self.db.execute("""INSERT INTO review_comments(
            workspace_project_id,version_id,parent_comment_id,timestamp_seconds,frame_number,
            category,priority,author_role,author_name,body,assigned_to,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(workspace_id),int(version_id),parent_comment_id,timestamp_seconds,frame_number,
             category,priority,author_role,author_name,body,assigned_to,'Open',now,now)))
        self._log(workspace_id,version_id,'comment_added',{'comment_id':cid})
        return cid

    def reply(self,comment_id,body,author_role='Editor',author_name=None):
        parent=self.db.frame('SELECT * FROM review_comments WHERE id=?',(int(comment_id),))
        if parent.empty: raise KeyError(comment_id)
        row=parent.iloc[0]
        return self.add_comment(row['workspace_project_id'],row['version_id'],body,
            timestamp_seconds=row['timestamp_seconds'],frame_number=row['frame_number'],
            category=row['category'],priority=row['priority'],author_role=author_role,
            author_name=author_name,assigned_to=None,parent_comment_id=int(comment_id))

    def comments(self,version_id=None,workspace_id=None,status=None):
        c=[]; p=[]
        if version_id is not None: c.append('version_id=?'); p.append(int(version_id))
        if workspace_id is not None: c.append('workspace_project_id=?'); p.append(int(workspace_id))
        if status: c.append('status=?'); p.append(status)
        sql='SELECT * FROM review_comments'
        if c: sql+=' WHERE '+' AND '.join(c)
        return self.db.frame(sql+' ORDER BY COALESCE(timestamp_seconds,999999),created_at',p)

    def resolve_comment(self,comment_id,resolution_note=None,status='Resolved'):
        row=self.db.frame('SELECT * FROM review_comments WHERE id=?',(int(comment_id),))
        if row.empty: raise KeyError(comment_id)
        now=datetime.now().isoformat()
        self.db.execute('UPDATE review_comments SET status=?,resolution_note=?,resolved_at=?,updated_at=? WHERE id=?',
                        (status,resolution_note,now if status=='Resolved' else None,now,int(comment_id)))
        self._log(int(row.iloc[0]['workspace_project_id']),int(row.iloc[0]['version_id']),'comment_resolved',{'comment_id':comment_id})

    def create_revision_request(self,workspace_id,source_version_id,title,reason=None,priority='Normal',due_at=None,requested_by='Creator'):
        latest=self.db.frame('SELECT MAX(request_number) AS n FROM revision_requests WHERE workspace_project_id=?',(int(workspace_id),))
        n=int(latest.iloc[0]['n'] or 0)+1; now=datetime.now().isoformat()
        rid=int(self.db.execute("""INSERT INTO revision_requests(
            workspace_project_id,source_version_id,request_number,title,reason,priority,due_at,
            status,requested_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (int(workspace_id),int(source_version_id),n,title,reason,priority,due_at,'Open',requested_by,now,now)))
        open_comments=self.comments(version_id=source_version_id,status='Open')
        for _,r in open_comments.iterrows():
            self.db.execute("""INSERT INTO revision_request_items(
                revision_request_id,comment_id,timestamp_seconds,instruction,status,created_at)
                VALUES(?,?,?,?,?,?)""",(rid,int(r['id']),r['timestamp_seconds'],r['body'],'Open',now))
        self.db.execute("UPDATE editor_workspace_projects SET workspace_status='Revision',updated_at=? WHERE id=?",(now,int(workspace_id)))
        ws=self.editor_workspace.workspace_project(workspace_id) if self.editor_workspace else None
        if ws and self.production: self.production.request_revision(ws['production_project_id'],reason)
        self._log(workspace_id,source_version_id,'revision_requested',{'request_id':rid,'items':len(open_comments)})
        return self.revision_request(rid)

    def revision_request(self,request_id):
        f=self.db.frame('SELECT * FROM revision_requests WHERE id=?',(int(request_id),))
        if f.empty: raise KeyError(request_id)
        return f.iloc[0].to_dict()

    def revision_requests(self,workspace_id=None):
        sql='SELECT * FROM revision_requests'; p=[]
        if workspace_id is not None: sql+=' WHERE workspace_project_id=?'; p=[int(workspace_id)]
        return self.db.frame(sql+' ORDER BY request_number DESC',p)

    def revision_items(self,request_id):
        return self.db.frame('SELECT * FROM revision_request_items WHERE revision_request_id=? ORDER BY COALESCE(timestamp_seconds,999999),id',(int(request_id),))

    def start_revision(self,request_id):
        req=self.revision_request(request_id); now=datetime.now().isoformat()
        self.db.execute("UPDATE revision_requests SET status='In progress',started_at=?,updated_at=? WHERE id=?",(now,now,int(request_id)))
        self.db.execute("UPDATE editor_workspace_projects SET workspace_status='Revision',updated_at=? WHERE id=?",(now,int(req['workspace_project_id'])))

    def set_revision_item(self,item_id,status,editor_response=None):
        now=datetime.now().isoformat()
        self.db.execute('UPDATE revision_request_items SET status=?,editor_response=?,completed_at=? WHERE id=?',
                        (status,editor_response,now if status=='Complete' else None,int(item_id)))

    def submit_revision(self,request_id,new_version_id):
        req=self.revision_request(request_id); now=datetime.now().isoformat()
        self.db.execute("UPDATE revision_requests SET status='Submitted',target_version_id=?,submitted_at=?,updated_at=? WHERE id=?",(int(new_version_id),now,now,int(request_id)))
        self.db.execute("UPDATE review_versions SET status='Needs review',updated_at=? WHERE id=?",(now,int(new_version_id)))
        self.db.execute("UPDATE editor_workspace_projects SET workspace_status='Ready for creator review',updated_at=? WHERE id=?",(now,int(req['workspace_project_id'])))

    def approval_checks(self,version_id):
        return self.db.frame('SELECT * FROM review_approval_checks WHERE version_id=? ORDER BY id',(int(version_id),))

    def set_check(self,check_id,status,notes=None,checked_by='Creator'):
        now=datetime.now().isoformat()
        self.db.execute('UPDATE review_approval_checks SET status=?,notes=?,checked_by=?,checked_at=? WHERE id=?',
                        (status,notes,checked_by,now,int(check_id)))

    def _seed_checks(self,workspace_id,version_id):
        checks=[('intro','Intro/hook is present'),('audio','Audio level is acceptable'),('visual','No unintended black frames or missing media'),
                ('captions','Required captions are present'),('thumbnail','Thumbnail is attached or tracked separately'),
                ('resolution','Resolution/export preset is correct'),('comments','All required review comments are resolved')]
        now=datetime.now().isoformat()
        for key,label in checks:
            self.db.execute('INSERT OR IGNORE INTO review_approval_checks(workspace_project_id,version_id,check_key,label,required,status,created_at) VALUES(?,?,?,?,?,?,?)',
                            (int(workspace_id),int(version_id),key,label,1,'Open',now))

    def approve_version(self,version_id,approved_by='Creator'):
        v=self.version(version_id)
        checks=self.approval_checks(version_id)
        incomplete=checks[(checks['required']==1)&(checks['status']!='Complete')]
        open_comments=self.comments(version_id=version_id,status='Open')
        if not incomplete.empty: raise ValueError(f'{len(incomplete)} required approval checks are incomplete.')
        if not open_comments.empty: raise ValueError(f'{len(open_comments)} review comments remain open.')
        now=datetime.now().isoformat()
        self.db.execute("UPDATE review_versions SET status='Approved',approved_at=?,reviewed_at=?,updated_at=? WHERE id=?",(now,now,now,int(version_id)))
        self.db.execute("UPDATE review_versions SET status='Superseded',updated_at=? WHERE workspace_project_id=? AND id<>? AND status<>'Published'",(now,int(v['workspace_project_id']),int(version_id)))
        self.db.execute("UPDATE editor_workspace_projects SET workspace_status='Approved',creator_reviewed_at=?,updated_at=? WHERE id=?",(now,now,int(v['workspace_project_id'])))
        ws=self.editor_workspace.workspace_project(v['workspace_project_id']) if self.editor_workspace else None
        if ws and self.production: self.production.approve_final(ws['production_project_id'])
        self._log(v['workspace_project_id'],version_id,'version_approved',{'approved_by':approved_by})
        return self.version(version_id)

    def add_thumbnail(self,workspace_id,file_location,label=None,notes=None):
        latest=self.db.frame('SELECT MAX(version_number) AS n FROM thumbnail_versions WHERE workspace_project_id=?',(int(workspace_id),))
        n=int(latest.iloc[0]['n'] or 0)+1; now=datetime.now().isoformat()
        return int(self.db.execute('INSERT INTO thumbnail_versions(workspace_project_id,version_number,file_location,label,status,notes,created_at) VALUES(?,?,?,?,?,?,?)',
                                   (int(workspace_id),n,file_location,label or f'Thumbnail {n}','Candidate',notes,now)))

    def approve_thumbnail(self,thumbnail_id):
        row=self.db.frame('SELECT * FROM thumbnail_versions WHERE id=?',(int(thumbnail_id),))
        if row.empty: raise KeyError(thumbnail_id)
        wid=int(row.iloc[0]['workspace_project_id']); now=datetime.now().isoformat()
        self.db.execute("UPDATE thumbnail_versions SET status='Candidate',favorite=0,approved_at=NULL WHERE workspace_project_id=?",(wid,))
        self.db.execute("UPDATE thumbnail_versions SET status='Approved',favorite=1,approved_at=? WHERE id=?",(now,int(thumbnail_id)))

    def thumbnails(self,workspace_id):
        return self.db.frame('SELECT * FROM thumbnail_versions WHERE workspace_project_id=? ORDER BY version_number DESC',(int(workspace_id),))

    def review_queue(self):
        return self.db.frame("""SELECT w.id AS workspace_id,p.title,e.name AS editor,
            v.id AS version_id,v.version_number,v.version_label,v.status,v.submitted_at,
            p.priority,p.content_type,p.game_topic,
            (SELECT COUNT(*) FROM review_comments c WHERE c.version_id=v.id AND c.status='Open') AS open_comments
            FROM editor_workspace_projects w JOIN production_projects p ON p.id=w.production_project_id
            LEFT JOIN editors e ON e.id=p.editor_id
            JOIN review_versions v ON v.id=(SELECT id FROM review_versions x WHERE x.workspace_project_id=w.id ORDER BY version_number DESC LIMIT 1)
            WHERE v.status IN('Needs review','Revision submitted') ORDER BY CASE p.priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,v.submitted_at""")

    def analytics(self):
        return self.db.frame("""SELECT COALESCE(e.name,'Unassigned') AS editor,
            COUNT(DISTINCT w.id) AS projects,
            AVG((SELECT COUNT(*) FROM revision_requests r WHERE r.workspace_project_id=w.id)) AS average_revisions,
            AVG(CASE WHEN v.reviewed_at IS NOT NULL AND v.submitted_at IS NOT NULL THEN (julianday(v.reviewed_at)-julianday(v.submitted_at))*24 END) AS average_review_hours,
            AVG(CASE WHEN v.version_number=1 AND v.status IN('Approved','Published') THEN 1.0 ELSE 0.0 END)*100 AS first_pass_approval_percent,
            SUM(CASE WHEN c.status='Open' THEN 1 ELSE 0 END) AS open_comments
            FROM editor_workspace_projects w JOIN production_projects p ON p.id=w.production_project_id
            LEFT JOIN editors e ON e.id=p.editor_id
            LEFT JOIN review_versions v ON v.workspace_project_id=w.id
            LEFT JOIN review_comments c ON c.version_id=v.id GROUP BY e.id ORDER BY projects DESC""")

    def common_feedback(self):
        return self.db.frame("""SELECT category,COUNT(*) AS comments,
            SUM(CASE WHEN status='Resolved' THEN 1 ELSE 0 END) AS resolved,
            AVG(CASE WHEN resolved_at IS NOT NULL THEN (julianday(resolved_at)-julianday(created_at))*24 END) AS average_resolution_hours
            FROM review_comments GROUP BY category ORDER BY comments DESC""")

    def _log(self,workspace_id,version_id,action,detail):
        self.db.execute('INSERT INTO review_activity(workspace_project_id,version_id,action_type,detail_json,created_at) VALUES(?,?,?,?,?)',
                        (workspace_id,version_id,action,json.dumps(detail or {},default=str),datetime.now().isoformat()))
