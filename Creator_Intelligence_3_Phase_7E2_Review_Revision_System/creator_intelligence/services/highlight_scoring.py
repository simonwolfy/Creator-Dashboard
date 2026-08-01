from __future__ import annotations
from datetime import datetime
import json, re

RULES={
"Boss Fight":r"\b(boss|boss fight|tagilla|killa|reshala|glukhar|shturman)\b",
"Death / Failure":r"\b(died|death|killed|failed|lost|wipe|game over)\b",
"Clutch / Escape":r"\b(clutch|escaped|survived|barely|last second)\b",
"Rare Loot":r"\b(rare loot|legendary|keycard|gpu|ledx|shiny|rare item)\b",
"Funny":r"\b(funny|laughed|laughing|hilarious|joke|meme)\b",
"Scary / Jump Scare":r"\b(scared|jump scare|jumpscare|screamed|terrified)\b",
"Raid / Community":r"\b(raid|raided|gift subs?|donation|bits|community)\b",
"Progression":r"\b(built|finished|completed|upgraded|expanded|unlocked|crafted)\b",
"Tutorial / Explanation":r"\b(tutorial|guide|how to|explain|strategy|tip)\b",
"Victory / Achievement":r"\b(victory|won|achievement|defeated|completed quest)\b",
"Strong Reaction":r"\b(no way|oh my god|holy|insane|crazy|what the)\b",
}

class HighlightScoringService:
    def __init__(self,db,scene_service=None,transcript_service=None,live_service=None,production_service=None,creator_planner=None,notifications=None):
        self.db=db; self.scene_service=scene_service; self.transcript_service=transcript_service
        self.live_service=live_service; self.production_service=production_service
        self.creator_planner=creator_planner; self.notifications=notifications
        self._schema()

    def _schema(self):
        for sql in [
        """CREATE TABLE IF NOT EXISTS scored_highlights(id INTEGER PRIMARY KEY AUTOINCREMENT,media_asset_id INTEGER,transcript_id INTEGER,live_session_id INTEGER,source_scene_id INTEGER,candidate_key TEXT UNIQUE NOT NULL,title TEXT NOT NULL,start_seconds REAL NOT NULL,peak_seconds REAL NOT NULL,end_seconds REAL NOT NULL,duration_seconds REAL NOT NULL,score REAL NOT NULL,confidence REAL NOT NULL,primary_category TEXT,categories_json TEXT,signal_breakdown_json TEXT,evidence_json TEXT,recommended_output TEXT,recommended_short_start REAL,recommended_short_end REAL,recommended_long_start REAL,recommended_long_end REAL,review_status TEXT DEFAULT 'Unreviewed',editor_status TEXT DEFAULT 'Not sent',production_project_id INTEGER,override_score REAL,reviewer_notes TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS highlight_signal_events(id INTEGER PRIMARY KEY AUTOINCREMENT,transcript_id INTEGER,media_asset_id INTEGER,live_session_id INTEGER,occurred_at_seconds REAL NOT NULL,signal_type TEXT NOT NULL,strength REAL NOT NULL,confidence REAL,title TEXT,payload_json TEXT,source_record_type TEXT,source_record_id INTEGER,created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS highlight_scoring_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,transcript_id INTEGER,media_asset_id INTEGER,live_session_id INTEGER,status TEXT,candidate_count INTEGER DEFAULT 0,settings_json TEXT,error_message TEXT,started_at TEXT,completed_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS highlight_review_actions(id INTEGER PRIMARY KEY AUTOINCREMENT,highlight_id INTEGER NOT NULL,action_type TEXT NOT NULL,payload_json TEXT,created_at TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_scored_highlights_score ON scored_highlights(transcript_id,score DESC,start_seconds)",
        "CREATE INDEX IF NOT EXISTS idx_highlight_signals_time ON highlight_signal_events(transcript_id,occurred_at_seconds)"
        ]: self.db.execute(sql)

    def generate(self,transcript_id,media_asset_id=None,live_session_id=None,grouping_window_seconds=90,minimum_score=35,replace_unreviewed=True):
        started=datetime.now().isoformat()
        run_id=int(self.db.execute("INSERT INTO highlight_scoring_runs(transcript_id,media_asset_id,live_session_id,status,settings_json,started_at) VALUES(?,?,?,?,?,?)",(int(transcript_id),media_asset_id,live_session_id,'Running',json.dumps({'grouping_window_seconds':grouping_window_seconds,'minimum_score':minimum_score}),started)))
        try:
            if replace_unreviewed:
                self.db.execute("DELETE FROM scored_highlights WHERE transcript_id=? AND review_status='Unreviewed' AND editor_status='Not sent'",(int(transcript_id),))
            signals=self._signals(transcript_id,media_asset_id,live_session_id)
            groups=self._group(signals,float(grouping_window_seconds)); made=[]
            for i,g in enumerate(groups):
                c=self._score(transcript_id,media_asset_id,live_session_id,i,g)
                if c['score']>=float(minimum_score): self._insert(c); made.append(c)
            self.db.execute("UPDATE highlight_scoring_runs SET status='Completed',candidate_count=?,completed_at=? WHERE id=?",(len(made),datetime.now().isoformat(),run_id))
            if self.notifications and made: self.notifications.create('System','Success','Highlight scoring complete',f'{len(made)} ranked highlights were generated.','transcript',transcript_id)
            return self.highlights(transcript_id)
        except Exception as e:
            self.db.execute("UPDATE highlight_scoring_runs SET status='Failed',error_message=?,completed_at=? WHERE id=?",(str(e),datetime.now().isoformat(),run_id)); raise

    def _signals(self,tid,mid,lid):
        self.db.execute('DELETE FROM highlight_signal_events WHERE transcript_id=?',(int(tid),)); out=[]
        if self.scene_service:
            for _,r in self.scene_service.scene_segments(tid).iterrows():
                text=f"{r.get('title') or ''} {r.get('summary') or ''}"
                out.append(dict(time=(float(r['start_seconds'])+float(r['end_seconds']))/2,start=float(r['start_seconds']),end=float(r['end_seconds']),type='scene',strength=max(float(r['content_value_score'] or 0),float(r['activity_score'] or 0)),confidence=float(r['confidence'] or .5),title=r['title'],text=text,payload={'scene_type':r['segment_type'],'content_value_score':float(r['content_value_score'] or 0),'activity_score':float(r['activity_score'] or 0),'silence_ratio':float(r['silence_ratio'] or 0)},source_record_type='scene_segment',source_record_id=int(r['id'])))
        if self.transcript_service:
            for _,r in self.transcript_service.segments(tid).iterrows():
                text=str(r['text']); cats=self._cats(text); ex=self._excitement(text)
                if ex<12 and not cats: continue
                out.append(dict(time=(float(r['start_seconds'])+float(r['end_seconds']))/2,start=float(r['start_seconds']),end=float(r['end_seconds']),type='transcript',strength=min(100,ex),confidence=float(r['confidence'] or .65),title=text[:80],text=text,payload={'categories':cats},source_record_type='transcript_segment',source_record_id=int(r['id'])))
        if self.live_service and lid:
            try:
                for _,r in self.live_service.markers(lid).iterrows():
                    out.append(dict(time=float(r['elapsed_seconds']),start=max(0,float(r['elapsed_seconds'])-15),end=float(r['elapsed_seconds'])+30,type='marker',strength=float(r['strength_score'] or 0),confidence=float(r['confidence'] or .8),title=r['label'],text=str(r['label']),payload={'marker_type':r['marker_type']},source_record_type='stream_marker',source_record_id=int(r['id'])))
                weights={'raid':95,'new_peak':70,'follow':35,'game_change':20,'manual_marker':90}
                for _,r in self.live_service.events(lid).iterrows():
                    t=str(r['event_type'])
                    if t not in weights: continue
                    out.append(dict(time=float(r['elapsed_seconds']),start=max(0,float(r['elapsed_seconds'])-20),end=float(r['elapsed_seconds'])+40,type=t,strength=weights[t],confidence=.9,title=r['title'],text=f"{r.get('title') or ''} {r.get('description') or ''}",payload=json.loads(r.get('payload_json') or '{}'),source_record_type='live_event',source_record_id=int(r['id'])))
            except Exception: pass
        low=[]
        if self.scene_service:
            f=self.scene_service.low_value_intervals(transcript_id=tid,media_asset_id=mid); low=f.to_dict('records') if not f.empty else []
        for s in out:
            penalty=0
            for x in low:
                if float(x['start_seconds'])<=s['time']<=float(x['end_seconds']): penalty=max(penalty,float(x['score'] or 0))
            s['payload']['low_value_penalty']=penalty
            self.db.execute("INSERT INTO highlight_signal_events(transcript_id,media_asset_id,live_session_id,occurred_at_seconds,signal_type,strength,confidence,title,payload_json,source_record_type,source_record_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(int(tid),mid,lid,s['time'],s['type'],s['strength'],s['confidence'],s['title'],json.dumps(s['payload'],default=str),s['source_record_type'],s['source_record_id'],datetime.now().isoformat()))
        return sorted(out,key=lambda x:x['time'])

    def _group(self,signals,window):
        if not signals:return []
        groups=[[signals[0]]]
        for s in signals[1:]:
            if s['time']-groups[-1][-1]['time']<=window:
                groups[-1].append(s)
            else:
                groups.append([s])
        return groups

    def _score(self,tid,mid,lid,index,g):
        text=' '.join(str(x.get('text') or '') for x in g); cats=self._cats(text) or ['General Highlight']
        mx=lambda typ:max([x['strength'] for x in g if x['type']==typ] or [0])
        penalty=max([float(x['payload'].get('low_value_penalty') or 0) for x in g] or [0])
        b={'scene_value':mx('scene')*.30,'transcript_excitement':mx('transcript')*.20,'stream_marker':mx('marker')*.18,'raid':mx('raid')*.20,'new_peak':mx('new_peak')*.10,'manual_marker':mx('manual_marker')*.18,'signal_density':min(15,max(0,len(g)-1)*3),'category_bonus':min(12,max(0,len(cats)-1)*3),'low_value_penalty':-min(30,penalty*.35)}
        score=max(0,min(100,sum(b.values()))); conf=min(.99,sum(float(x['confidence']) for x in g)/len(g)+min(.15,len(g)*.02))
        strongest=max(g,key=lambda x:x['strength']); peak=float(strongest['time']); start=min(float(x['start']) for x in g); end=max(float(x['end']) for x in g)
        ss=max(0,min(start,peak-12)); se=max(peak+15,min(end,peak+48)); se=min(se,ss+60)
        output=self._output(cats,score,se-ss)
        now=datetime.now().isoformat()
        evidence=[{'type':x['type'],'time':x['time'],'strength':x['strength'],'title':x['title'],'source_record_type':x['source_record_type'],'source_record_id':x['source_record_id']} for x in g]
        return dict(media_asset_id=mid,transcript_id=int(tid),live_session_id=lid,source_scene_id=next((x['source_record_id'] for x in g if x['source_record_type']=='scene_segment'),None),candidate_key=f"{tid}:{round(start,1)}:{round(end,1)}:{index}",title=cats[0] if cats[0]!='General Highlight' else (str(strongest['title'])[:90] or 'Potential highlight'),start_seconds=start,peak_seconds=peak,end_seconds=end,duration_seconds=end-start,score=round(score,2),confidence=round(conf,3),primary_category=cats[0],categories_json=json.dumps(cats),signal_breakdown_json=json.dumps(b),evidence_json=json.dumps(evidence,default=str),recommended_output=output,recommended_short_start=ss,recommended_short_end=se,recommended_long_start=max(0,start-30),recommended_long_end=end+60,review_status='Unreviewed',editor_status='Not sent',created_at=now,updated_at=now)

    def _cats(self,text):
        lower=str(text).lower(); cats=[k for k,p in RULES.items() if re.search(p,lower)]
        order=['Raid / Community','Boss Fight','Death / Failure','Clutch / Escape','Rare Loot','Scary / Jump Scare','Funny','Victory / Achievement','Progression','Tutorial / Explanation','Strong Reaction']
        return sorted(cats,key=lambda x:order.index(x) if x in order else 999)
    def _excitement(self,text):
        lower=text.lower(); return min(100,len(re.findall(r'[!?]{2,}',text))*6+len(re.findall(r'\b(no way|oh my god|holy|insane|crazy|clutch|boss|died|death|rare|shiny|raid|scared|scream|won|victory|finally)\b',lower))*9+min(15,len(re.findall(r'\b[A-Z]{3,}\b',text))*3))
    def _output(self,cats,score,dur):
        long={'Boss Fight','Progression','Tutorial / Explanation','Victory / Achievement'}; short={'Funny','Death / Failure','Clutch / Escape','Rare Loot','Scary / Jump Scare','Raid / Community','Strong Reaction'}
        hl=any(x in long for x in cats); hs=any(x in short for x in cats)
        if score>=85 and hl and hs:return 'Short + long-form segment'
        if hs or dur<=75:return 'YouTube Short / TikTok'
        if hl:return 'Long-form episode segment'
        return 'Editor review'
    def _insert(self,c):
        cols=list(c); self.db.execute(f"INSERT OR REPLACE INTO scored_highlights({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",[c[x] for x in cols])
    def highlights(self,transcript_id=None,status=None):
        clauses=[];params=[]
        if transcript_id is not None: clauses.append('transcript_id=?');params.append(int(transcript_id))
        if status: clauses.append('review_status=?');params.append(status)
        sql="SELECT id,transcript_id,media_asset_id,title,start_seconds,peak_seconds,end_seconds,duration_seconds,COALESCE(override_score,score) AS effective_score,score,override_score,confidence,primary_category,categories_json,recommended_output,recommended_short_start,recommended_short_end,recommended_long_start,recommended_long_end,review_status,editor_status,production_project_id,reviewer_notes,updated_at FROM scored_highlights"
        if clauses:sql+=' WHERE '+' AND '.join(clauses)
        return self.db.frame(sql+' ORDER BY effective_score DESC,start_seconds',params)
    def highlight(self,hid):
        f=self.db.frame('SELECT * FROM scored_highlights WHERE id=?',(int(hid),));
        if f.empty:raise KeyError(hid)
        return f.iloc[0].to_dict()
    def set_review(self,hid,status,notes=None,override_score=None):
        if status not in {'Unreviewed','Approved','Rejected','Needs changes'}:raise ValueError(status)
        self.db.execute("UPDATE scored_highlights SET review_status=?,reviewer_notes=COALESCE(?,reviewer_notes),override_score=COALESCE(?,override_score),updated_at=? WHERE id=?",(status,notes,override_score,datetime.now().isoformat(),int(hid)));self._log(hid,'review',{'status':status,'notes':notes,'override_score':override_score});return self.highlight(hid)
    def update_boundaries(self,hid,start,peak,end):
        if not float(start)<=float(peak)<=float(end):raise ValueError('Peak must fall between start and end.')
        self.db.execute('UPDATE scored_highlights SET start_seconds=?,peak_seconds=?,end_seconds=?,duration_seconds=?,updated_at=? WHERE id=?',(float(start),float(peak),float(end),float(end)-float(start),datetime.now().isoformat(),int(hid)));self._log(hid,'boundary_update',{'start':start,'peak':peak,'end':end});return self.highlight(hid)
    def merge(self,ids):
        ids=[int(x) for x in ids]
        if len(ids)<2:raise ValueError('Select at least two highlights.')
        f=self.db.frame(f"SELECT * FROM scored_highlights WHERE id IN ({','.join('?' for _ in ids)})",ids)
        if len(f)!=len(ids) or f['transcript_id'].nunique()!=1:raise ValueError('Highlights must exist in the same transcript.')
        cats=[]
        for raw in f['categories_json']:
            for c in json.loads(raw or '[]'):
                if c not in cats:cats.append(c)
        start=float(f['start_seconds'].min());end=float(f['end_seconds'].max());peak=float(f.sort_values('score',ascending=False).iloc[0]['peak_seconds']);now=datetime.now().isoformat()
        c=dict(media_asset_id=f.iloc[0]['media_asset_id'],transcript_id=int(f.iloc[0]['transcript_id']),live_session_id=f.iloc[0]['live_session_id'],source_scene_id=None,candidate_key=f'merge:{f.iloc[0]["transcript_id"]}:{start}:{end}:{now}',title=' + '.join(f['title'].tolist()[:2]),start_seconds=start,peak_seconds=peak,end_seconds=end,duration_seconds=end-start,score=min(100,float(f['score'].max())+8),confidence=min(.99,float(f['confidence'].mean())+.05),primary_category=cats[0] if cats else 'General Highlight',categories_json=json.dumps(cats),signal_breakdown_json=json.dumps({'merged_highlights':ids}),evidence_json=json.dumps({'merged_highlights':ids}),recommended_output='Short + long-form segment',recommended_short_start=max(start,peak-15),recommended_short_end=min(end,peak+45),recommended_long_start=start,recommended_long_end=end,review_status='Needs changes',editor_status='Not sent',created_at=now,updated_at=now)
        self._insert(c);m=self.db.frame('SELECT * FROM scored_highlights WHERE candidate_key=?',(c['candidate_key'],)).iloc[0].to_dict()
        for i in ids:self.set_review(i,'Rejected','Merged into another highlight.')
        self._log(m['id'],'merge',{'highlight_ids':ids});return m
    def send_to_production(self,hid,editor_id=None):
        if not self.production_service:raise RuntimeError('Production service is unavailable.')
        h=self.highlight(hid)
        if h['review_status']!='Approved':raise ValueError('Approve the highlight before sending it to production.')
        project=int(self.production_service.create_project({'title':h['title'],'platform':'YouTube','content_type':'Short' if 'Short' in str(h['recommended_output']) else 'Long-form','status':'Assets ready','priority':'High' if float(h.get('override_score') or h['score'])>=80 else 'Normal','editor_id':editor_id,'source_stream_id':str(h.get('live_session_id') or ''),'notes':f"Highlight #{hid}. Start {h['start_seconds']:.1f}s, peak {h['peak_seconds']:.1f}s, end {h['end_seconds']:.1f}s. Recommended output: {h['recommended_output']}. Categories: {h['categories_json']}."}))
        self.db.execute("UPDATE scored_highlights SET editor_status='Sent',production_project_id=?,updated_at=? WHERE id=?",(project,datetime.now().isoformat(),int(hid)));self._log(hid,'send_to_production',{'production_project_id':project});return project
    def opportunity_summary(self,tid):
        f=self.highlights(tid)
        if f.empty:return {'highlight_count':0,'high_confidence_count':0,'short_candidates':0,'long_form_candidates':0,'opportunity_score':0}
        high=int((f['effective_score']>=80).sum());shorts=int(f['recommended_output'].str.contains('Short',case=False).sum());longs=int(f['recommended_output'].str.contains('long-form',case=False).sum());opp=min(100,float(f['effective_score'].head(12).sum())/12+high*2+shorts*1.5+longs*2)
        return {'highlight_count':len(f),'high_confidence_count':high,'short_candidates':shorts,'long_form_candidates':longs,'average_score':float(f['effective_score'].mean()),'top_score':float(f['effective_score'].max()),'opportunity_score':round(opp,2)}
    def _log(self,hid,typ,payload=None):self.db.execute('INSERT INTO highlight_review_actions(highlight_id,action_type,payload_json,created_at) VALUES(?,?,?,?)',(int(hid),typ,json.dumps(payload or {},default=str),datetime.now().isoformat()))
