from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
import json, os, shutil, subprocess, threading, time

JOB_TYPES=("Probe metadata","Extract audio","Generate thumbnails","Generate proxy")

@dataclass(frozen=True)
class ToolStatus:
    ffmpeg_path:str|None; ffprobe_path:str|None; available:bool; message:str

class VideoProcessingService:
    def __init__(self,db,creator_planner=None,notifications=None,output_root=None,ffmpeg_path=None,ffprobe_path=None):
        self.db=db; self.creator_planner=creator_planner; self.notifications=notifications
        self.output_root=Path(output_root or (Path(db.path).parent/'media_processing')); self.output_root.mkdir(parents=True,exist_ok=True)
        self.ffmpeg_path=ffmpeg_path or os.getenv('CREATOR_INTELLIGENCE_FFMPEG') or shutil.which('ffmpeg')
        self.ffprobe_path=ffprobe_path or os.getenv('CREATOR_INTELLIGENCE_FFPROBE') or shutil.which('ffprobe')
        self._cancel={}; self._processes={}; self._lock=threading.RLock(); self._ensure_schema(); self.recover_interrupted_jobs()

    def _ensure_schema(self):
        for sql in [
        """CREATE TABLE IF NOT EXISTS media_assets(id INTEGER PRIMARY KEY AUTOINCREMENT,content_source_id INTEGER,asset_type TEXT DEFAULT 'Video',display_name TEXT NOT NULL,source_path TEXT NOT NULL UNIQUE,file_size_bytes INTEGER,duration_seconds REAL,width INTEGER,height INTEGER,frame_rate REAL,video_codec TEXT,audio_codec TEXT,sample_rate INTEGER,channels INTEGER,container_format TEXT,bit_rate INTEGER,status TEXT DEFAULT 'Imported',probe_json TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS media_processing_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,media_asset_id INTEGER NOT NULL,job_type TEXT NOT NULL,status TEXT DEFAULT 'Queued',priority INTEGER DEFAULT 100,progress_percent REAL DEFAULT 0,progress_seconds REAL DEFAULT 0,expected_duration_seconds REAL,command_json TEXT,settings_json TEXT,output_directory TEXT,error_message TEXT,attempt_count INTEGER DEFAULT 0,queued_at TEXT NOT NULL,started_at TEXT,completed_at TEXT,cancelled_at TEXT,worker_id TEXT,updated_at TEXT NOT NULL,FOREIGN KEY(media_asset_id) REFERENCES media_assets(id))""",
        """CREATE TABLE IF NOT EXISTS media_artifacts(id INTEGER PRIMARY KEY AUTOINCREMENT,media_asset_id INTEGER NOT NULL,job_id INTEGER,artifact_type TEXT NOT NULL,file_path TEXT NOT NULL,timestamp_seconds REAL,file_size_bytes INTEGER,metadata_json TEXT,created_at TEXT NOT NULL,UNIQUE(job_id,file_path))""",
        """CREATE TABLE IF NOT EXISTS media_processing_events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER,event_type TEXT NOT NULL,message TEXT,detail_json TEXT,created_at TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_media_jobs_queue ON media_processing_jobs(status,priority,queued_at)",
        "CREATE INDEX IF NOT EXISTS idx_media_artifacts_asset ON media_artifacts(media_asset_id,artifact_type,timestamp_seconds)"]:
            self.db.execute(sql)

    def tool_status(self):
        ok=bool(self.ffmpeg_path and self.ffprobe_path)
        return ToolStatus(self.ffmpeg_path,self.ffprobe_path,ok,'FFmpeg and FFprobe are available.' if ok else 'FFmpeg/FFprobe were not found. Install FFmpeg or configure CREATOR_INTELLIGENCE_FFMPEG and CREATOR_INTELLIGENCE_FFPROBE.')

    def import_video(self,source_path,content_source_id=None,display_name=None,auto_probe=True):
        path=Path(source_path).expanduser().resolve()
        if not path.is_file(): raise FileNotFoundError(path)
        f=self.db.frame('SELECT id FROM media_assets WHERE source_path=?',(str(path),))
        if not f.empty:return int(f.iloc[0]['id'])
        now=datetime.now().isoformat(); aid=int(self.db.execute("INSERT INTO media_assets(content_source_id,display_name,source_path,file_size_bytes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(content_source_id,display_name or path.name,str(path),path.stat().st_size,'Imported',now,now)))
        self._event(None,'asset_imported',path.name,{'asset_id':aid})
        if auto_probe:self.queue_job(aid,'Probe metadata',priority=10)
        return aid

    def assets(self):
        return self.db.frame("""SELECT a.*,(SELECT COUNT(*) FROM media_processing_jobs j WHERE j.media_asset_id=a.id) job_count,(SELECT COUNT(*) FROM media_artifacts r WHERE r.media_asset_id=a.id) artifact_count FROM media_assets a ORDER BY created_at DESC""")
    def asset(self,aid):
        f=self.db.frame('SELECT * FROM media_assets WHERE id=?',(int(aid),));
        if f.empty:raise KeyError(aid)
        return f.iloc[0].to_dict()
    def jobs(self,status=None):
        sql="""SELECT j.id,j.media_asset_id,a.display_name,j.job_type,j.status,j.priority,ROUND(j.progress_percent,1) progress_percent,j.progress_seconds,j.expected_duration_seconds,j.attempt_count,j.error_message,j.queued_at,j.started_at,j.completed_at,j.output_directory FROM media_processing_jobs j JOIN media_assets a ON a.id=j.media_asset_id""";p=[]
        if status and status!='All':sql+=' WHERE j.status=?';p.append(status)
        return self.db.frame(sql+" ORDER BY CASE j.status WHEN 'Running' THEN 1 WHEN 'Queued' THEN 2 ELSE 3 END,j.priority,j.queued_at",p)
    def job(self,jid):
        f=self.db.frame('SELECT * FROM media_processing_jobs WHERE id=?',(int(jid),));
        if f.empty:raise KeyError(jid)
        return f.iloc[0].to_dict()
    def artifacts(self,aid=None):
        sql="SELECT r.*,a.display_name FROM media_artifacts r JOIN media_assets a ON a.id=r.media_asset_id";p=[]
        if aid:sql+=' WHERE r.media_asset_id=?';p.append(int(aid))
        return self.db.frame(sql+' ORDER BY r.created_at DESC,r.timestamp_seconds',p)

    def queue_job(self,aid,job_type,settings=None,priority=100):
        if job_type not in JOB_TYPES:raise ValueError(job_type)
        self.asset(aid);now=datetime.now().isoformat();out=self.output_root/f'asset_{int(aid)}';out.mkdir(parents=True,exist_ok=True)
        jid=int(self.db.execute("INSERT INTO media_processing_jobs(media_asset_id,job_type,status,priority,settings_json,output_directory,queued_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(int(aid),job_type,'Queued',int(priority),json.dumps(settings or {}),str(out),now,now)));self._event(jid,'queued',job_type,settings or {});return jid
    def retry_job(self,jid):
        now=datetime.now().isoformat();self.db.execute("UPDATE media_processing_jobs SET status='Queued',progress_percent=0,progress_seconds=0,error_message=NULL,started_at=NULL,completed_at=NULL,cancelled_at=NULL,worker_id=NULL,updated_at=? WHERE id=?",(now,int(jid)));return jid
    def recover_interrupted_jobs(self):
        return self.db.execute("UPDATE media_processing_jobs SET status='Queued',error_message='Recovered after application interruption.',worker_id=NULL,updated_at=? WHERE status='Running'",(datetime.now().isoformat(),))
    def cancel_job(self,jid):
        with self._lock:
            self._cancel.setdefault(int(jid),threading.Event()).set();p=self._processes.get(int(jid));
            if p and p.poll() is None:p.terminate()
        now=datetime.now().isoformat();self.db.execute("UPDATE media_processing_jobs SET status='Cancelled',cancelled_at=?,updated_at=? WHERE id=? AND status IN ('Queued','Running')",(now,now,int(jid)))

    def run_next(self,progress_callback=None):
        f=self.db.frame("SELECT id FROM media_processing_jobs WHERE status='Queued' ORDER BY priority,queued_at LIMIT 1")
        if f.empty:return None
        jid=int(f.iloc[0]['id']);self.run_job(jid,progress_callback);return jid

    def run_job(self,jid,progress_callback:Callable[[int,float,str],None]|None=None):
        job=self.job(jid)
        if job['status'] not in ('Queued','Failed','Cancelled'):raise ValueError(f"Job is {job['status']}")
        if not self.tool_status().available:self._fail(jid,self.tool_status().message);raise RuntimeError(self.tool_status().message)
        asset=self.asset(job['media_asset_id']);settings=json.loads(job.get('settings_json') or '{}');now=datetime.now().isoformat()
        self.db.execute("UPDATE media_processing_jobs SET status='Running',started_at=?,attempt_count=attempt_count+1,worker_id=?,error_message=NULL,updated_at=? WHERE id=?",(now,f'{os.getpid()}:{threading.get_ident()}',now,int(jid)))
        cancel=threading.Event();self._cancel[int(jid)]=cancel
        try:
            if job['job_type']=='Probe metadata':self._probe(jid,asset)
            else:self._ffmpeg(jid,asset,job['job_type'],settings,cancel,progress_callback)
            if cancel.is_set() or self.job(jid)['status']=='Cancelled':return
            now=datetime.now().isoformat();self.db.execute("UPDATE media_processing_jobs SET status='Completed',progress_percent=100,completed_at=?,worker_id=NULL,updated_at=? WHERE id=?",(now,now,int(jid)))
            if self.notifications:self.notifications.create('System','Success','Video processing complete',f"{asset['display_name']}: {job['job_type']} completed.",'media_job',jid)
        except Exception as exc:
            if cancel.is_set():self.cancel_job(jid)
            else:self._fail(jid,str(exc))
            raise
        finally:self._cancel.pop(int(jid),None);self._processes.pop(int(jid),None)

    def _probe(self,jid,asset):
        cmd=[self.ffprobe_path,'-v','error','-print_format','json','-show_format','-show_streams',asset['source_path']];self._command(jid,cmd)
        r=subprocess.run(cmd,capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr.strip() or 'FFprobe failed')
        data=json.loads(r.stdout or '{}');fmt=data.get('format',{});streams=data.get('streams',[]);v=next((x for x in streams if x.get('codec_type')=='video'),{});a=next((x for x in streams if x.get('codec_type')=='audio'),{})
        try:n,d=str(v.get('avg_frame_rate','0/1')).split('/');fps=float(n)/float(d)
        except Exception:fps=None
        dur=float(fmt.get('duration') or v.get('duration') or 0);now=datetime.now().isoformat()
        self.db.execute("""UPDATE media_assets SET duration_seconds=?,width=?,height=?,frame_rate=?,video_codec=?,audio_codec=?,sample_rate=?,channels=?,container_format=?,bit_rate=?,probe_json=?,status='Ready',updated_at=? WHERE id=?""",(dur,v.get('width'),v.get('height'),fps,v.get('codec_name'),a.get('codec_name'),int(a.get('sample_rate') or 0) or None,a.get('channels'),fmt.get('format_name'),int(fmt.get('bit_rate') or 0) or None,json.dumps(data),now,int(asset['id'])))
        self.db.execute('UPDATE media_processing_jobs SET expected_duration_seconds=?,progress_seconds=?,progress_percent=100,updated_at=? WHERE id=?',(dur,dur,now,int(jid)))

    def _build(self,asset,kind,settings,out):
        src=asset['source_path'];out=Path(out)
        if kind=='Extract audio':
            target=out/'audio.wav';return [self.ffmpeg_path,'-y','-i',src,'-vn','-ac','1','-ar',str(settings.get('sample_rate',16000)),'-c:a','pcm_s16le','-progress','pipe:1','-nostats',str(target)],[('Audio',target,None)]
        if kind=='Generate thumbnails':
            interval=max(10,int(settings.get('interval_seconds',300)));target=out/'thumbnail_%06d.jpg';return [self.ffmpeg_path,'-y','-i',src,'-vf',f'fps=1/{interval},scale={int(settings.get("width",640))}:-2','-q:v','3','-progress','pipe:1','-nostats',str(target)],[('ThumbnailPattern',target,interval)]
        target=out/'proxy_720p.mp4';return [self.ffmpeg_path,'-y','-i',src,'-vf','scale=-2:720','-c:v','libx264','-preset','veryfast','-crf','28','-c:a','aac','-b:a','96k','-movflags','+faststart','-progress','pipe:1','-nostats',str(target)],[('Proxy',target,None)]

    def _ffmpeg(self,jid,asset,kind,settings,cancel,cb):
        job=self.job(jid);cmd,outputs=self._build(asset,kind,settings,job['output_directory']);self._command(jid,cmd);dur=float(asset.get('duration_seconds') or 0)
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1);self._processes[int(jid)]=p;last=0
        for raw in p.stdout:
            if cancel.is_set():p.terminate();break
            if raw.startswith('out_time_ms='):
                try:sec=float(raw.split('=',1)[1])/1_000_000
                except:continue
                if time.monotonic()-last>.15:
                    pct=min(99,(sec/dur*100) if dur else 0);now=datetime.now().isoformat();self.db.execute('UPDATE media_processing_jobs SET progress_seconds=?,progress_percent=?,expected_duration_seconds=?,updated_at=? WHERE id=?',(sec,pct,dur or None,now,int(jid)));last=time.monotonic()
                    if cb:cb(int(jid),pct,f'{sec/3600:.2f}h processed')
        err=p.stderr.read() if p.stderr else '';rc=p.wait()
        if cancel.is_set():return
        if rc:raise RuntimeError(err[-4000:] or f'FFmpeg exited with {rc}')
        self._register(jid,asset['id'],outputs)

    def _register(self,jid,aid,outputs):
        now=datetime.now().isoformat()
        for kind,path,interval in outputs:
            paths=sorted(path.parent.glob(path.name.replace('%06d','*'))) if kind=='ThumbnailPattern' else [path]
            for i,p in enumerate(paths):
                if p.exists():self.db.execute('INSERT OR IGNORE INTO media_artifacts(media_asset_id,job_id,artifact_type,file_path,timestamp_seconds,file_size_bytes,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?)',(int(aid),int(jid),'Thumbnail' if kind=='ThumbnailPattern' else kind,str(p),i*interval if interval else None,p.stat().st_size,json.dumps({'interval_seconds':interval} if interval else {}),now))
    def _command(self,jid,cmd):self.db.execute('UPDATE media_processing_jobs SET command_json=?,updated_at=? WHERE id=?',(json.dumps(cmd),datetime.now().isoformat(),int(jid)))
    def _fail(self,jid,msg):
        now=datetime.now().isoformat();self.db.execute("UPDATE media_processing_jobs SET status='Failed',error_message=?,worker_id=NULL,updated_at=? WHERE id=?",(msg,now,int(jid)))
        if self.notifications:self.notifications.create('System','Error','Video processing failed',msg,'media_job',jid)
    def _event(self,jid,kind,msg,detail):self.db.execute('INSERT INTO media_processing_events(job_id,event_type,message,detail_json,created_at) VALUES(?,?,?,?,?)',(jid,kind,msg,json.dumps(detail),datetime.now().isoformat()))
