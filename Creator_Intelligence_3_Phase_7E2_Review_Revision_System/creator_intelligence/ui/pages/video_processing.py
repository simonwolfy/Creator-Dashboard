from PySide6.QtCore import QObject,QThread,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableView,QTabWidget,QAbstractItemView,QFileDialog,QMessageBox,QInputDialog
from creator_intelligence.ui.pages.twitch import FrameModel
class JobWorker(QObject):
    finished=Signal(int);failed=Signal(int,str)
    def __init__(self,service,jid):super().__init__();self.service=service;self.jid=jid
    def run(self):
        try:self.service.run_job(self.jid);self.finished.emit(self.jid)
        except Exception as e:self.failed.emit(self.jid,str(e))
class VideoProcessingPage(QWidget):
    def __init__(self,service):
        super().__init__();self.service=service;self._threads=[];l=QVBoxLayout(self);t=QLabel('Video Processing Engine');t.setObjectName('pageTitle');l.addWidget(t);l.addWidget(QLabel(service.tool_status().message));r=QHBoxLayout()
        for x,f in [('Import VOD',self.import_vod),('Queue audio',lambda:self.queue('Extract audio')),('Queue thumbnails',lambda:self.queue('Generate thumbnails')),('Queue proxy',lambda:self.queue('Generate proxy')),('Run job',self.run_job),('Cancel',self.cancel),('Retry',self.retry),('Refresh',self.refresh)]:b=QPushButton(x);b.clicked.connect(f);r.addWidget(b)
        l.addLayout(r);self.tabs=QTabWidget();self.assets=QTableView();self.assets.setSelectionBehavior(QAbstractItemView.SelectRows);self.jobs=QTableView();self.jobs.setSelectionBehavior(QAbstractItemView.SelectRows);self.artifacts=QTableView();self.tabs.addTab(self.assets,'Media assets');self.tabs.addTab(self.jobs,'Processing queue');self.tabs.addTab(self.artifacts,'Artifacts');l.addWidget(self.tabs);self.refresh()
    def _id(self,table):
        i=table.currentIndex();return int(table.model().frame.iloc[i.row()]['id']) if i.isValid() else None
    def import_vod(self):
        p,_=QFileDialog.getOpenFileName(self,'Import VOD','','Video (*.mp4 *.mkv *.mov *.webm *.m4v);;All files (*)')
        if p:self.service.import_video(p);self.refresh()
    def queue(self,kind):
        aid=self._id(self.assets)
        if not aid:return
        s={}
        if kind=='Generate thumbnails':
            n,ok=QInputDialog.getInt(self,'Thumbnail interval','Seconds',300,30,3600,30)
            if not ok:return
            s={'interval_seconds':n,'width':640}
        self.service.queue_job(aid,kind,s);self.refresh()
    def run_job(self):
        jid=self._id(self.jobs)
        if not jid:return
        th=QThread(self);w=JobWorker(self.service,jid);w.moveToThread(th);th.started.connect(w.run);w.finished.connect(lambda *_:self._done(th));w.failed.connect(lambda _j,m:self._failed(th,m));self._threads.append((th,w));th.start()
    def _done(self,th):th.quit();th.wait();self._threads=[x for x in self._threads if x[0] is not th];self.refresh()
    def _failed(self,th,msg):self._done(th);QMessageBox.warning(self,'Processing failed',msg)
    def cancel(self):
        jid=self._id(self.jobs)
        if jid:self.service.cancel_job(jid);self.refresh()
    def retry(self):
        jid=self._id(self.jobs)
        if jid:self.service.retry_job(jid);self.refresh()
    def refresh(self):self.assets.setModel(FrameModel(self.service.assets()));self.jobs.setModel(FrameModel(self.service.jobs()));self.artifacts.setModel(FrameModel(self.service.artifacts()))
