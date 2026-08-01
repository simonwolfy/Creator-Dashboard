from __future__ import annotations
from datetime import datetime, timedelta
import json, math

class OpportunityWorkloadService:
    def __init__(self, db, content_recommendations, production, creator_planner=None, notifications=None):
        self.db=db; self.content_recommendations=content_recommendations
        self.production=production; self.creator_planner=creator_planner; self.notifications=notifications
        self._ensure_schema()

    def _ensure_schema(self):
        for sql in [
            """CREATE TABLE IF NOT EXISTS vod_opportunity_scores(
                id INTEGER PRIMARY KEY AUTOINCREMENT,transcript_id INTEGER NOT NULL UNIQUE,
                media_asset_id INTEGER,source_id INTEGER,highlight_count INTEGER DEFAULT 0,
                short_count INTEGER DEFAULT 0,episode_count INTEGER DEFAULT 0,
                high_score_count INTEGER DEFAULT 0,average_highlight_score REAL DEFAULT 0,
                top_highlight_score REAL DEFAULT 0,content_density REAL DEFAULT 0,
                expected_editor_hours REAL DEFAULT 0,expected_output_count INTEGER DEFAULT 0,
                historical_value_score REAL DEFAULT 0,opportunity_score REAL DEFAULT 0,
                capacity_fit_score REAL DEFAULT 0,priority_score REAL DEFAULT 0,
                rationale_json TEXT,status TEXT DEFAULT 'Active',calculated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS editor_workload_forecasts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,editor_id INTEGER NOT NULL,
                editor_name TEXT NOT NULL,active_projects INTEGER DEFAULT 0,
                queued_editor_hours REAL DEFAULT 0,weekly_capacity_hours REAL DEFAULT 0,
                available_capacity_hours REAL DEFAULT 0,utilization_percent REAL DEFAULT 0,
                estimated_clear_date TEXT,overdue_projects INTEGER DEFAULT 0,
                risk_level TEXT DEFAULT 'Low',recommendation TEXT,calculated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS vod_assignment_recommendations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,transcript_id INTEGER NOT NULL,
                editor_id INTEGER,rank INTEGER NOT NULL,priority_score REAL NOT NULL,
                recommended_action TEXT NOT NULL,reason TEXT NOT NULL,
                estimated_editor_hours REAL DEFAULT 0,expected_deliverables INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Active',production_project_id INTEGER,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS workload_settings(
                id INTEGER PRIMARY KEY CHECK(id=1),default_weekly_editor_hours REAL DEFAULT 20,
                short_edit_minutes REAL DEFAULT 20,long_form_edit_minutes_per_source_hour REAL DEFAULT 25,
                reserve_capacity_percent REAL DEFAULT 15,max_utilization_percent REAL DEFAULT 90,
                updated_at TEXT)""",
            """INSERT OR IGNORE INTO workload_settings(id,updated_at) VALUES(1,datetime('now'))""",
            """CREATE INDEX IF NOT EXISTS idx_vod_opportunity_priority ON vod_opportunity_scores(priority_score DESC)""",
            """CREATE INDEX IF NOT EXISTS idx_assignment_rank ON vod_assignment_recommendations(status,rank)""",
        ]: self.db.execute(sql)

    def settings(self):
        return self.db.frame('SELECT * FROM workload_settings WHERE id=1').iloc[0].to_dict()

    def update_settings(self, **changes):
        allowed={'default_weekly_editor_hours','short_edit_minutes','long_form_edit_minutes_per_source_hour','reserve_capacity_percent','max_utilization_percent'}
        values={k:v for k,v in changes.items() if k in allowed}
        if not values:return
        values['updated_at']=datetime.now().isoformat(); cols=list(values)
        self.db.execute('UPDATE workload_settings SET '+','.join(f'{c}=?' for c in cols)+' WHERE id=1',[values[c] for c in cols])

    def calculate_vod(self, transcript_id, media_asset_id=None, source_id=None):
        highlights=self.content_recommendations.highlight_scoring.highlights(transcript_id)
        recs=self.content_recommendations.recommendations(transcript_id)
        if highlights.empty and recs.empty: raise ValueError('Generate highlights and content recommendations first.')
        short_count=int((recs['recommendation_type']=='Short').sum()) if not recs.empty else 0
        episode_count=int((recs['recommendation_type']=='Long-form Episode').sum()) if not recs.empty else 0
        scores=highlights['effective_score'] if not highlights.empty else []
        highlight_count=len(highlights); high_count=int((scores>=80).sum()) if highlight_count else 0
        avg=float(scores.mean()) if highlight_count else 0; top=float(scores.max()) if highlight_count else 0
        editor_hours=float(recs['editor_work_minutes'].sum()/60) if not recs.empty else 0
        output_count=short_count+episode_count
        duration_hours=self._duration_hours(transcript_id,media_asset_id)
        density=(highlight_count/max(duration_hours,0.5)) if highlight_count else 0
        historical=self._historical_score(source_id)
        raw=(min(100,avg)*.24 + min(100,top)*.18 + min(100,high_count*12)*.14 +
             min(100,output_count*9)*.18 + min(100,density*12)*.14 + historical*.12)
        efficiency=output_count/max(editor_hours,0.5)
        efficiency_bonus=min(12,efficiency*3)
        opportunity=max(0,min(100,raw+efficiency_bonus))
        capacity_fit=self._capacity_fit(editor_hours)
        priority=opportunity*.75+capacity_fit*.25
        rationale={
            'duration_hours':round(duration_hours,2),'highlights_per_hour':round(density,2),
            'outputs_per_editor_hour':round(efficiency,2),'historical_value_score':round(historical,2),
            'components':{'quality':round(avg,2),'peak':round(top,2),'high_score_count':high_count,
                          'expected_outputs':output_count,'editor_hours':round(editor_hours,2)}
        }
        now=datetime.now().isoformat()
        self.db.execute("""INSERT INTO vod_opportunity_scores(
            transcript_id,media_asset_id,source_id,highlight_count,short_count,episode_count,
            high_score_count,average_highlight_score,top_highlight_score,content_density,
            expected_editor_hours,expected_output_count,historical_value_score,opportunity_score,
            capacity_fit_score,priority_score,rationale_json,calculated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(transcript_id) DO UPDATE SET media_asset_id=excluded.media_asset_id,
            source_id=excluded.source_id,highlight_count=excluded.highlight_count,short_count=excluded.short_count,
            episode_count=excluded.episode_count,high_score_count=excluded.high_score_count,
            average_highlight_score=excluded.average_highlight_score,top_highlight_score=excluded.top_highlight_score,
            content_density=excluded.content_density,expected_editor_hours=excluded.expected_editor_hours,
            expected_output_count=excluded.expected_output_count,historical_value_score=excluded.historical_value_score,
            opportunity_score=excluded.opportunity_score,capacity_fit_score=excluded.capacity_fit_score,
            priority_score=excluded.priority_score,rationale_json=excluded.rationale_json,
            calculated_at=excluded.calculated_at""",
            (int(transcript_id),media_asset_id,source_id,highlight_count,short_count,episode_count,
             high_count,avg,top,density,editor_hours,output_count,historical,opportunity,
             capacity_fit,priority,json.dumps(rationale),now))
        return self.opportunity(transcript_id)

    def _duration_hours(self,transcript_id,media_asset_id):
        try:
            t=self.content_recommendations.highlight_scoring.transcript_service.transcript(transcript_id)
            duration=float(t.get('duration_seconds') or 0)
            if duration:return duration/3600
        except Exception:pass
        return 1.0

    def _historical_score(self,source_id):
        if not source_id or not self.creator_planner:return 50.0
        try:
            frame=self.creator_planner.source_yield()
            row=frame[frame['id']==int(source_id)]
            if row.empty:return 50.0
            r=row.iloc[0]
            return min(100,math.log10(max(float(r['total_views']),1))*18 + min(float(r['subscribers_gained']),50))
        except Exception:return 50.0

    def _capacity_fit(self,required_hours):
        forecast=self.forecast_editors()
        if forecast.empty:return 60.0
        best=float(forecast['available_capacity_hours'].max())
        if required_hours<=best:return min(100,70+(best-required_hours)*2)
        return max(0,70-(required_hours-best)*8)

    def forecast_editors(self):
        workload=self.production.workload()
        settings=self.settings(); now=datetime.now(); rows=[]
        self.db.execute('DELETE FROM editor_workload_forecasts')
        for _,r in workload.iterrows():
            weekly=float(r.get('target_weekly_capacity') or 0)
            default_hours=float(settings['default_weekly_editor_hours'])
            capacity=default_hours if weekly<=0 else max(default_hours,weekly*8)
            active=int(r.get('active_projects') or 0)
            turnaround=float(r.get('average_turnaround_days') or r.get('default_turnaround_days') or 4)
            queued=max(0,active*max(2,turnaround*1.5))
            reserve=capacity*float(settings['reserve_capacity_percent'])/100
            available=max(0,capacity-reserve-queued)
            utilization=(queued/max(capacity,1))*100
            weeks=queued/max(capacity,1); clear=now+timedelta(days=weeks*7)
            overdue=int(r.get('overdue_projects') or 0)
            risk='Critical' if utilization>=110 or overdue>=3 else 'High' if utilization>=90 or overdue else 'Moderate' if utilization>=70 else 'Low'
            recommendation=('Do not assign additional long-form work.' if risk in {'Critical','High'} else
                            'Assign Shorts only if deadlines are flexible.' if risk=='Moderate' else
                            'Capacity is available for new work.')
            vals=(int(r['id']),r['name'],active,queued,capacity,available,utilization,clear.isoformat(),overdue,risk,recommendation,datetime.now().isoformat())
            self.db.execute("""INSERT INTO editor_workload_forecasts(editor_id,editor_name,active_projects,
                queued_editor_hours,weekly_capacity_hours,available_capacity_hours,utilization_percent,
                estimated_clear_date,overdue_projects,risk_level,recommendation,calculated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",vals)
            rows.append(vals)
        return self.db.frame('SELECT * FROM editor_workload_forecasts ORDER BY utilization_percent,overdue_projects')

    def opportunities(self):
        return self.db.frame('SELECT * FROM vod_opportunity_scores WHERE status=\'Active\' ORDER BY priority_score DESC')

    def opportunity(self,transcript_id):
        frame=self.db.frame('SELECT * FROM vod_opportunity_scores WHERE transcript_id=?',(int(transcript_id),))
        if frame.empty:raise KeyError(transcript_id)
        return frame.iloc[0].to_dict()

    def generate_assignments(self):
        self.db.execute("UPDATE vod_assignment_recommendations SET status='Expired' WHERE status='Active'")
        opportunities=self.opportunities(); editors=self.forecast_editors(); now=datetime.now().isoformat(); created=[]
        if opportunities.empty:return []
        for rank,(_,opp) in enumerate(opportunities.iterrows(),1):
            editor_id=None; editor_name='Unassigned'; capacity=0
            if not editors.empty:
                eligible=editors[editors['available_capacity_hours']>=float(opp['expected_editor_hours'])]
                choice=(eligible if not eligible.empty else editors).sort_values(['risk_level','utilization_percent']).iloc[0]
                editor_id=int(choice['editor_id']); editor_name=choice['editor_name']; capacity=float(choice['available_capacity_hours'])
            action='Assign now' if capacity>=float(opp['expected_editor_hours']) else 'Hold or reduce scope'
            reason=(f"Opportunity {float(opp['opportunity_score']):.1f}/100; {int(opp['expected_output_count'])} expected outputs; "
                    f"{float(opp['expected_editor_hours']):.1f} editor hours. Best fit: {editor_name}.")
            rid=int(self.db.execute("""INSERT INTO vod_assignment_recommendations(
                transcript_id,editor_id,rank,priority_score,recommended_action,reason,
                estimated_editor_hours,expected_deliverables,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (int(opp['transcript_id']),editor_id,rank,float(opp['priority_score']),action,reason,
                 float(opp['expected_editor_hours']),int(opp['expected_output_count']),'Active',now,now)))
            created.append(rid)
        if self.notifications:
            self.notifications.create('Production','Success','VOD priorities recalculated',
                f'{len(created)} capacity-aware assignment recommendations were generated.','system','opportunity-workload')
        return created

    def assignments(self):
        return self.db.frame("""SELECT a.*,e.name AS editor_name FROM vod_assignment_recommendations a
            LEFT JOIN editors e ON e.id=a.editor_id WHERE a.status='Active' ORDER BY a.rank""")

    def dashboard(self):
        opp=self.opportunities(); editors=self.forecast_editors(); assignments=self.assignments()
        return {
            'vods_ranked':len(opp),'top_opportunity_score':float(opp['opportunity_score'].max()) if not opp.empty else 0,
            'expected_outputs':int(opp['expected_output_count'].sum()) if not opp.empty else 0,
            'expected_editor_hours':round(float(opp['expected_editor_hours'].sum()),2) if not opp.empty else 0,
            'editors_over_capacity':int((editors['utilization_percent']>100).sum()) if not editors.empty else 0,
            'assignments_ready':int((assignments['recommended_action']=='Assign now').sum()) if not assignments.empty else 0
        }
