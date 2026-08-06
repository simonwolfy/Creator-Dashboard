from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,QFileDialog,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QMessageBox,
    QProgressBar,QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout,QWizard,QWizardPage
)

from creator_intelligence.core.onboarding import default_workspace_path


class OnboardingWizard(QWizard):
    def __init__(self,service,parent=None):
        super().__init__(parent); self.service=service; profile=service.profile()
        self.setWindowTitle("Welcome to Creator Intelligence"); self.resize(760,560)
        self.setWizardStyle(QWizard.ModernStyle)
        welcome=QWizardPage(); welcome.setTitle("Your creator workspace, on your computer")
        layout=QVBoxLayout(welcome); notice=QLabel(
            "Creator Intelligence stores your workspace, media references, analytics, transcripts, and generated exports locally. "
            "Platform connections are optional and can be configured later. Credentials are never requested by this welcome wizard."
        ); notice.setWordWrap(True); layout.addWidget(notice)
        self.privacy=QCheckBox("I understand where my creator data will be stored and that I control this folder.")
        self.privacy.setChecked(profile.privacy_acknowledged); layout.addWidget(self.privacy); layout.addStretch(); self.addPage(welcome)
        workspace=QWizardPage(); workspace.setTitle("Choose your workspace")
        form=QFormLayout(workspace); self.workspace_name=QLineEdit(profile.workspace_name or "My Workspace")
        self.channel_name=QLineEdit(profile.channel_name or "My Channel")
        self.workspace_root=QLineEdit(profile.workspace_root or str(default_workspace_path()))
        browse_row=QHBoxLayout(); browse_row.addWidget(self.workspace_root,1); browse=QPushButton("Choose folder"); browse.clicked.connect(self.choose_folder); browse_row.addWidget(browse)
        form.addRow("Workspace name",self.workspace_name); form.addRow("Channel name",self.channel_name); form.addRow("Workspace folder",browse_row); self.addPage(workspace)
        diagnostics=QWizardPage(); diagnostics.setTitle("Check this computer")
        d_layout=QVBoxLayout(diagnostics); self.diagnostics_table=QTableWidget(0,3); self.diagnostics_table.setHorizontalHeaderLabels(["Component","Status","What this means"])
        self.diagnostics_table.horizontalHeader().setStretchLastSection(True); d_layout.addWidget(self.diagnostics_table)
        self.diagnostics_progress=QProgressBar(); self.diagnostics_progress.setFormat("%v of %m checks ready"); d_layout.addWidget(self.diagnostics_progress)
        rerun=QPushButton("Run checks again"); rerun.clicked.connect(self.run_diagnostics); d_layout.addWidget(rerun); self.addPage(diagnostics)
        connections=QWizardPage(); connections.setTitle("Optional platform connections")
        c_layout=QVBoxLayout(connections); text=QLabel("Choose the platforms you want to configure after setup. You can skip all of them and use the dashboard locally.")
        text.setWordWrap(True); c_layout.addWidget(text); self.platforms={}
        for key,label in (("youtube","YouTube"),("twitch","Twitch"),("instagram","Instagram"),("tiktok","TikTok")):
            box=QCheckBox(f"Show {label} setup after onboarding"); box.setChecked(key in profile.selected_platforms); self.platforms[key]=box; c_layout.addWidget(box)
        self.skip_connections=QCheckBox("Skip connections for now"); self.skip_connections.setChecked(profile.connections_skipped); c_layout.addWidget(self.skip_connections); c_layout.addStretch(); self.addPage(connections)
        finish=QWizardPage(); finish.setTitle("Ready to create your workspace")
        f_layout=QVBoxLayout(finish); summary=QLabel("Select Finish to create an empty database, save your workspace choice, and open Creator Intelligence. You can reopen this wizard from Settings.")
        summary.setWordWrap(True); f_layout.addWidget(summary); f_layout.addStretch(); self.addPage(finish)
        self.currentIdChanged.connect(lambda _page:self.run_diagnostics() if self.currentPage() is diagnostics else None)

    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"Choose Creator Intelligence workspace",self.workspace_root.text())
        if folder:self.workspace_root.setText(folder)

    def run_diagnostics(self):
        checks=self.service.diagnostics(self.workspace_root.text() or default_workspace_path())
        self.diagnostics_progress.setRange(0,len(checks)); self.diagnostics_progress.setValue(sum(check.ready for check in checks))
        self.diagnostics_table.setRowCount(len(checks))
        for row,check in enumerate(checks):
            values=(check.name,"Ready" if check.ready else "Required" if check.required else "Optional",check.detail)
            for column,value in enumerate(values):self.diagnostics_table.setItem(row,column,QTableWidgetItem(str(value)))

    def accept(self):
        try:
            self.service.complete(
                workspace_root=self.workspace_root.text(),workspace_name=self.workspace_name.text(),
                channel_name=self.channel_name.text(),privacy_acknowledged=self.privacy.isChecked(),
                selected_platforms=[key for key,box in self.platforms.items() if box.isChecked()],
                connections_skipped=self.skip_connections.isChecked())
        except Exception as exc:
            QMessageBox.warning(self,"Setup needs attention",str(exc));return
        super().accept()
