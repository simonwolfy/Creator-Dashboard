from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QScrollArea,
    QSplitter,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget,
)


class AssetLibraryPage(QWidget):
    """Searchable asset browser with an integrated technical media inspector."""

    ALL = "All"

    def __init__(self, service):
        super().__init__();self.service=service;self._rows=[]
        outer=QVBoxLayout(self);header=QHBoxLayout();title=QLabel("Asset Library");title.setObjectName("pageTitle")
        refresh=QPushButton("Refresh");refresh.clicked.connect(self.refresh);header.addWidget(title);header.addStretch();header.addWidget(refresh);outer.addLayout(header)

        filters=QHBoxLayout();self.search_box=QLineEdit();self.search_box.setPlaceholderText("Search name, path, URL, or notes");self.search_box.returnPressed.connect(self.refresh)
        self.type_filter=self._combo([self.ALL,"Video","Audio","Image","Thumbnail","Project","Subtitle","Overlay","Other"])
        self.provider_filter=self._combo([self.ALL,"Local","Google Drive","Backup","Other"])
        self.status_filter=self._combo([self.ALL,"Available","Missing","Processing","Archived"])
        for label,widget in (("Search",self.search_box),("Type",self.type_filter),("Storage",self.provider_filter),("Status",self.status_filter)):
            filters.addWidget(QLabel(label));filters.addWidget(widget)
        apply_button=QPushButton("Apply");apply_button.clicked.connect(self.refresh);filters.addWidget(apply_button);outer.addLayout(filters)

        splitter=QSplitter(Qt.Horizontal);self.table=QTableWidget(0,11)
        self.table.setHorizontalHeaderLabels(["Name","Type","Role","Storage","Status","Size","Duration","Resolution","FPS","Updated","Location"])
        self.table.setAlternatingRowColors(True);self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False);self.table.itemSelectionChanged.connect(self._show_selection);self.table.horizontalHeader().setStretchLastSection(True);splitter.addWidget(self.table)

        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(390);detail=QWidget();detail_layout=QVBoxLayout(detail)
        detail_title=QLabel("Media Inspector");detail_title.setStyleSheet("font-size:18px;font-weight:700;");detail_layout.addWidget(detail_title)
        self.inspector_summary=QLabel("Select an asset to inspect it.");self.inspector_summary.setWordWrap(True);detail_layout.addWidget(self.inspector_summary)
        self.detail_labels={};form=QFormLayout()
        fields=(
            ("name","Name"),("asset_type","Type"),("role","Role"),("storage_provider","Storage"),("status","Asset status"),
            ("probe_status","Metadata status"),("location","Location"),("mime_type","MIME type"),("size_bytes","Size"),
            ("duration_seconds","Duration"),("resolution","Resolution"),("frame_rate","Frame rate"),("aspect_ratio","Aspect ratio"),
            ("video_codec","Video codec"),("video_profile","Profile"),("pixel_format","Pixel format"),("hdr_format","Dynamic range"),
            ("color_space","Color space"),("container_format","Container"),("bit_rate","Bitrate"),("rotation","Rotation"),
            ("audio_codec","Audio codec"),("audio_tracks","Audio tracks"),("audio_channels","Channels"),("audio_sample_rate","Sample rate"),
            ("probed_at","Metadata read"),("probe_error","Metadata error"),("checksum_sha256","SHA-256"),("last_verified_at","Last verified"),("notes","Notes"),
        )
        for key,label in fields:
            value=QLabel("—");value.setWordWrap(True);value.setTextInteractionFlags(Qt.TextSelectableByMouse);self.detail_labels[key]=value;form.addRow(label,value)
        detail_layout.addLayout(form);detail_layout.addStretch();scroll.setWidget(detail);splitter.addWidget(scroll);splitter.setSizes([1050,430]);outer.addWidget(splitter)
        self.summary=QLabel();outer.addWidget(self.summary);self.refresh()

    @staticmethod
    def _combo(values):
        combo=QComboBox();combo.addItems(values);return combo
    @staticmethod
    def _selected(combo):
        value=combo.currentText();return None if value==AssetLibraryPage.ALL else value

    def refresh(self):
        self._rows=self.service.search(self.search_box.text().strip() or None,asset_type=self._selected(self.type_filter),storage_provider=self._selected(self.provider_filter),status=self._selected(self.status_filter),limit=1000)
        self.table.setRowCount(len(self._rows));missing=0;checksum_counts={};complete=0
        for row in self._rows:
            checksum=row.get("checksum_sha256")
            if checksum:checksum_counts[checksum]=checksum_counts.get(checksum,0)+1
            if row.get("probe_status")=="Complete":complete+=1
        duplicate_checksums={value for value,count in checksum_counts.items() if count>1}
        for row_index,row in enumerate(self._rows):
            if str(row.get("status") or "").casefold()=="missing":missing+=1
            values=(row.get("name"),row.get("asset_type"),row.get("role"),row.get("storage_provider"),row.get("status"),self._format_size(row.get("size_bytes")),self._format_duration(row.get("duration_seconds")),self._resolution(row),self._format_fps(row.get("frame_rate")),row.get("updated_at"),row.get("location"))
            for column,value in enumerate(values):
                item=QTableWidgetItem("" if value is None else str(value));item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if row.get("checksum_sha256") in duplicate_checksums:item.setToolTip("Possible duplicate: another asset has the same checksum")
                self.table.setItem(row_index,column,item)
        self.table.resizeColumnsToContents();duplicate_count=sum(checksum_counts[value] for value in duplicate_checksums)
        videos=sum(1 for row in self._rows if row.get("asset_type")=="Video")
        self.summary.setText(f"Assets: {len(self._rows)}  |  Videos inspected: {complete}/{videos}  |  Missing: {missing}  |  Possible duplicates: {duplicate_count}")
        self._show_selection()

    def _show_selection(self):
        selected=self.table.selectionModel().selectedRows() if self.table.selectionModel() else [];row=self._rows[selected[0].row()] if selected else None
        if row is None:self.inspector_summary.setText("Select an asset to inspect it.")
        elif row.get("asset_type")!="Video":self.inspector_summary.setText("Technical video metadata is available for video assets.")
        elif row.get("probe_status")=="Complete":self.inspector_summary.setText("Technical metadata is available.")
        elif row.get("probe_status"):self.inspector_summary.setText(f"Metadata status: {row.get('probe_status')}")
        else:self.inspector_summary.setText("Metadata has not been read yet. Use Video Metadata to probe a local copy.")
        for key,label in self.detail_labels.items():
            if row is None:label.setText("—");continue
            value=self._display_value(key,row)
            label.setText("—" if value in (None,"") else str(value))

    def _display_value(self,key,row):
        if key=="size_bytes":return self._format_size(row.get(key))
        if key=="duration_seconds":return self._format_duration(row.get(key))
        if key=="resolution":return self._resolution(row)
        if key=="frame_rate":return self._format_fps(row.get(key))
        if key=="aspect_ratio":return self._aspect_ratio(row.get("width"),row.get("height"))
        if key=="bit_rate":return self._format_bitrate(row.get(key))
        if key=="audio_sample_rate":return f"{int(row[key]):,} Hz" if row.get(key) not in (None,"") else None
        if key=="rotation":return f"{int(row[key])}°" if row.get(key) not in (None,"") else None
        return row.get(key)

    @staticmethod
    def _resolution(row):
        w,h=row.get("width"),row.get("height");return f"{int(w)} × {int(h)}" if w and h else "—"
    @staticmethod
    def _format_fps(value):return "—" if value in (None,"") else f"{float(value):.3f}".rstrip("0").rstrip(".")+" fps"
    @staticmethod
    def _format_duration(value):
        if value in (None,""):return "—"
        total=max(0,int(round(float(value))));hours,remainder=divmod(total,3600);minutes,seconds=divmod(remainder,60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    @staticmethod
    def _format_bitrate(value):
        if value in (None,""):return "—"
        bits=float(value);return f"{bits/1_000_000:.2f} Mbps" if bits>=1_000_000 else f"{bits/1_000:.0f} Kbps"
    @staticmethod
    def _aspect_ratio(width,height):
        if not width or not height:return "—"
        from math import gcd
        w,h=int(width),int(height);d=gcd(w,h);return f"{w//d}:{h//d}"
    @staticmethod
    def _format_size(value):
        if value in (None,""):return "—"
        size=float(value);units=("B","KB","MB","GB","TB");index=0
        while size>=1024 and index<len(units)-1:size/=1024;index+=1
        return f"{size:.1f} {units[index]}"
