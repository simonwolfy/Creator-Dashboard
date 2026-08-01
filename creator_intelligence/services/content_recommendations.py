from __future__ import annotations
from datetime import datetime
import json, math

class ContentRecommendationService:
    def __init__(self, db, highlight_scoring, production=None, creator_planner=None, notifications=None):
        self.db=db; self.highlight_scoring=highlight_scoring; self.production=production
        self.creator_planner=creator_planner; self.notifications=notifications
        self._ensure_schema()

    def _ensure_schema(self):
        for sql in [
            """CREATE TABLE IF NOT EXISTS content_recommendation_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,transcript_id INTEGER NOT NULL,
                status TEXT DEFAULT 'Running',settings_json TEXT,candidate_count INTEGER DEFAULT 0,
                started_at TEXT NOT NULL,completed_at TEXT,error_message TEXT)""",
            """CREATE TABLE IF NOT EXISTS content_recommendations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,transcript_id INTEGER NOT NULL,
                recommendation_key TEXT NOT NULL UNIQUE,recommendation_type TEXT NOT NULL,
                title TEXT NOT NULL,description TEXT,start_seconds REAL,end_seconds REAL,
                estimated_duration_seconds REAL,score REAL NOT NULL,confidence REAL NOT NULL,
                priority INTEGER DEFAULT 100,source_highlight_ids_json TEXT,
                categories_json TEXT,editor_work_minutes REAL DEFAULT 0,
                recommended_platform TEXT,recommended_format TEXT,review_status TEXT DEFAULT 'Unreviewed',
                production_project_id INTEGER,notes TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS episode_outline_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,recommendation_id INTEGER NOT NULL,
                sequence_number INTEGER NOT NULL,highlight_id INTEGER,start_seconds REAL,end_seconds REAL,
                role TEXT,title TEXT,reason TEXT,created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS editor_packets(
                id INTEGER PRIMARY KEY AUTOINCREMENT,transcript_id INTEGER NOT NULL,title TEXT NOT NULL,
                status TEXT DEFAULT 'Draft',summary_json TEXT,estimated_editor_hours REAL DEFAULT 0,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""",
            """CREATE INDEX IF NOT EXISTS idx_content_recommendations_score
               ON content_recommendations(transcript_id,score DESC,priority)""",
        ]: self.db.execute(sql)

    def generate(self, transcript_id, max_shorts=12, max_episodes=3, replace=True):
        now=datetime.now().isoformat()
        run_id=int(self.db.execute("""INSERT INTO content_recommendation_runs(
            transcript_id,status,settings_json,started_at) VALUES(?,?,?,?)""",
            (int(transcript_id),'Running',json.dumps({'max_shorts':max_shorts,'max_episodes':max_episodes}),now)))
        try:
            if replace:
                ids=self.db.frame("SELECT id FROM content_recommendations WHERE transcript_id=? AND review_status='Unreviewed'",(int(transcript_id),))
                for rid in ids['id'].tolist() if not ids.empty else []:
                    self.db.execute('DELETE FROM episode_outline_items WHERE recommendation_id=?',(int(rid),))
                self.db.execute("DELETE FROM content_recommendations WHERE transcript_id=? AND review_status='Unreviewed'",(int(transcript_id),))
            highlights=self.highlight_scoring.highlights(transcript_id)
            if highlights.empty:
                raise ValueError('Generate scored highlights first.')
            created=[]
            short_pool=highlights[highlights['recommended_output'].str.contains('Short',case=False,na=False)].copy()
            short_pool=short_pool.sort_values(['effective_score','confidence'],ascending=False).head(int(max_shorts))
            for rank,(_,h) in enumerate(short_pool.iterrows(),1):
                created.append(self._create_short(transcript_id,h,rank))
            created.extend(self._create_episode_recommendations(transcript_id,highlights,int(max_episodes)))
            packet=self.build_editor_packet(transcript_id)
            self.db.execute("UPDATE content_recommendation_runs SET status='Completed',candidate_count=?,completed_at=? WHERE id=?",
                            (len(created),datetime.now().isoformat(),run_id))
            if self.notifications:
                self.notifications.create('System','Success','Content recommendations ready',
                    f'{len(created)} Shorts and episode recommendations were generated.','transcript',transcript_id)
            return self.recommendations(transcript_id)
        except Exception as exc:
            self.db.execute("UPDATE content_recommendation_runs SET status='Failed',error_message=?,completed_at=? WHERE id=?",
                            (str(exc),datetime.now().isoformat(),run_id))
            raise

    def _create_short(self, transcript_id, h, rank):
        score=float(h['effective_score']); conf=float(h['confidence'])
        start=float(h['recommended_short_start']); end=float(h['recommended_short_end'])
        duration=max(1,end-start)
        editor=max(5,min(35,8+duration*0.22+(100-score)*0.08))
        categories=json.loads(h['categories_json'] or '[]')
        title=f"Short #{rank}: {h['title']}"
        key=f"short:{transcript_id}:{int(h['id'])}"
        rid=self._insert({
            'transcript_id':int(transcript_id),'recommendation_key':key,'recommendation_type':'Short',
            'title':title,'description':f"Use highlight #{int(h['id'])}; hook near {float(h['peak_seconds']):.1f}s.",
            'start_seconds':start,'end_seconds':end,'estimated_duration_seconds':duration,
            'score':min(100,score+4 if duration<=60 else score),'confidence':conf,
            'priority':rank,'source_highlight_ids_json':json.dumps([int(h['id'])]),
            'categories_json':json.dumps(categories),'editor_work_minutes':editor,
            'recommended_platform':'YouTube Shorts + TikTok','recommended_format':'9:16 vertical',
            'review_status':'Unreviewed','created_at':datetime.now().isoformat(),'updated_at':datetime.now().isoformat()})
        return rid

    def _create_episode_recommendations(self, transcript_id, highlights, max_episodes):
        long_pool=highlights[highlights['recommended_output'].str.contains('long-form',case=False,na=False)].copy()
        if long_pool.empty:
            long_pool=highlights[highlights['effective_score']>=60].copy()
        long_pool=long_pool.sort_values('start_seconds')
        clusters=[]
        current=[]
        for _,h in long_pool.iterrows():
            if not current or float(h['start_seconds'])-float(current[-1]['end_seconds'])<=1800:
                current.append(h.to_dict())
            else:
                clusters.append(current); current=[h.to_dict()]
        if current: clusters.append(current)
        clusters=sorted(clusters,key=lambda g:sum(float(x['effective_score']) for x in g),reverse=True)[:max_episodes]
        created=[]
        for idx,group in enumerate(clusters,1):
            start=max(0,min(float(x['recommended_long_start']) for x in group))
            end=max(float(x['recommended_long_end']) for x in group)
            scores=[float(x['effective_score']) for x in group]
            confidence=sum(float(x['confidence']) for x in group)/len(group)
            score=min(100,sum(scores)/len(scores)+min(12,len(group)*2))
            ids=[int(x['id']) for x in group]
            categories=[]
            for x in group:
                for c in json.loads(x['categories_json'] or '[]'):
                    if c not in categories: categories.append(c)
            duration=end-start
            editor=max(45,duration/60*2.2+len(group)*8)
            title=f"Episode Recommendation #{idx}: {group[0]['title']}"
            key=f"episode:{transcript_id}:{start:.1f}:{end:.1f}:{idx}"
            rid=self._insert({'transcript_id':int(transcript_id),'recommendation_key':key,
                'recommendation_type':'Long-form Episode','title':title,
                'description':f'{len(group)} ranked moments form a coherent episode arc.',
                'start_seconds':start,'end_seconds':end,'estimated_duration_seconds':duration,
                'score':score,'confidence':confidence,'priority':idx,'source_highlight_ids_json':json.dumps(ids),
                'categories_json':json.dumps(categories),'editor_work_minutes':editor,
                'recommended_platform':'YouTube','recommended_format':'16:9 edited VOD episode',
                'review_status':'Unreviewed','created_at':datetime.now().isoformat(),'updated_at':datetime.now().isoformat()})
            roles=['Hook']+['Main moment']*max(0,len(group)-2)+(['Payoff'] if len(group)>1 else [])
            for seq,x in enumerate(group,1):
                role=roles[seq-1] if seq-1<len(roles) else 'Main moment'
                self.db.execute("""INSERT INTO episode_outline_items(
                    recommendation_id,sequence_number,highlight_id,start_seconds,end_seconds,role,title,reason,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (rid,seq,int(x['id']),float(x['recommended_long_start']),float(x['recommended_long_end']),
                     role,x['title'],f"Highlight score {float(x['effective_score']):.1f}",datetime.now().isoformat()))
            created.append(rid)
        return created

    def _insert(self, values):
        cols=list(values)
        return int(self.db.execute(f"INSERT OR REPLACE INTO content_recommendations({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",
                                   [values[c] for c in cols]))

    def recommendations(self, transcript_id=None, recommendation_type=None):
        clauses=[]; params=[]
        if transcript_id is not None: clauses.append('transcript_id=?'); params.append(int(transcript_id))
        if recommendation_type: clauses.append('recommendation_type=?'); params.append(recommendation_type)
        sql='SELECT * FROM content_recommendations'
        if clauses: sql+=' WHERE '+' AND '.join(clauses)
        sql+=' ORDER BY CASE recommendation_type WHEN \'Short\' THEN 1 ELSE 2 END,priority,score DESC'
        return self.db.frame(sql,params)

    def outline(self,recommendation_id):
        return self.db.frame('SELECT * FROM episode_outline_items WHERE recommendation_id=? ORDER BY sequence_number',(int(recommendation_id),))

    def set_review(self,recommendation_id,status,notes=None):
        if status not in {'Unreviewed','Approved','Rejected','Needs changes'}: raise ValueError(status)
        self.db.execute('UPDATE content_recommendations SET review_status=?,notes=COALESCE(?,notes),updated_at=? WHERE id=?',
                        (status,notes,datetime.now().isoformat(),int(recommendation_id)))

    def send_to_production(self,recommendation_id,editor_id=None):
        if not self.production: raise RuntimeError('Production service unavailable.')
        row=self.db.frame('SELECT * FROM content_recommendations WHERE id=?',(int(recommendation_id),))
        if row.empty: raise KeyError(recommendation_id)
        r=row.iloc[0].to_dict()
        if r['review_status']!='Approved': raise ValueError('Approve recommendation first.')
        content_type='Short' if r['recommendation_type']=='Short' else 'Long-form'
        project_id=self.production.create_project({'title':r['title'],'platform':'YouTube','content_type':content_type,
            'status':'Assets ready','priority':'High' if float(r['score'])>=80 else 'Normal','editor_id':editor_id,
            'notes':f"Recommendation #{recommendation_id}. Range {r['start_seconds']:.1f}-{r['end_seconds']:.1f}s. Estimated editor work {r['editor_work_minutes']:.0f} minutes. Highlights {r['source_highlight_ids_json']}."})
        self.db.execute('UPDATE content_recommendations SET production_project_id=?,updated_at=? WHERE id=?',
                        (project_id,datetime.now().isoformat(),int(recommendation_id)))
        return int(project_id)

    def build_editor_packet(self,transcript_id):
        recs=self.recommendations(transcript_id)
        shorts=recs[recs['recommendation_type']=='Short']
        episodes=recs[recs['recommendation_type']=='Long-form Episode']
        summary={'transcript_id':int(transcript_id),'short_count':len(shorts),'episode_count':len(episodes),
                 'estimated_editor_hours':float(recs['editor_work_minutes'].sum()/60) if not recs.empty else 0,
                 'top_shorts':shorts.head(10)[['id','title','start_seconds','end_seconds','score']].to_dict('records') if not shorts.empty else [],
                 'episodes':episodes[['id','title','start_seconds','end_seconds','score']].to_dict('records') if not episodes.empty else []}
        now=datetime.now().isoformat()
        existing=self.db.frame('SELECT id FROM editor_packets WHERE transcript_id=? ORDER BY id DESC LIMIT 1',(int(transcript_id),))
        if existing.empty:
            pid=int(self.db.execute('INSERT INTO editor_packets(transcript_id,title,status,summary_json,estimated_editor_hours,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                (int(transcript_id),f'Editor Packet — Transcript {transcript_id}','Draft',json.dumps(summary),summary['estimated_editor_hours'],now,now)))
        else:
            pid=int(existing.iloc[0]['id']); self.db.execute('UPDATE editor_packets SET summary_json=?,estimated_editor_hours=?,updated_at=? WHERE id=?',
                (json.dumps(summary),summary['estimated_editor_hours'],now,pid))
        return {'id':pid,**summary}

    def summary(self,transcript_id):
        recs=self.recommendations(transcript_id)
        if recs.empty: return {'recommendations':0,'shorts':0,'episodes':0,'editor_hours':0,'top_score':0}
        return {'recommendations':len(recs),'shorts':int((recs['recommendation_type']=='Short').sum()),
                'episodes':int((recs['recommendation_type']=='Long-form Episode').sum()),
                'editor_hours':round(float(recs['editor_work_minutes'].sum()/60),2),
                'top_score':round(float(recs['score'].max()),2)}
