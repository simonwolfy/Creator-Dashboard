from __future__ import annotations

import csv
import json
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree


class TranscriptExportMixin:
    """Professional transcript, chapter, and NLE marker exports."""

    def export_markdown(self, transcript_id: int, output_path) -> Path:
        transcript = self.transcript(transcript_id)
        segments = self.segments(transcript_id)
        chapters = self.chapters(transcript_id)
        lines = [f'# {transcript.get("title") or "Transcript"}', ""]
        chapter_rows = chapters.to_dict("records") if not chapters.empty else []
        chapter_index = 0
        for _, row in segments.iterrows():
            start = float(row["start_seconds"])
            while chapter_index < len(chapter_rows) and start >= float(chapter_rows[chapter_index]["start_seconds"]):
                chapter = chapter_rows[chapter_index]
                if start <= float(chapter["end_seconds"]):
                    lines.extend([f'## {self._clock_export(chapter["start_seconds"])} — {chapter["title"]}', ""])
                chapter_index += 1
            speaker = str(row.get("speaker") or "").strip()
            prefix = f'**{speaker}:** ' if speaker else ""
            lines.append(f'[{self._clock_export(start)}] {prefix}{row["text"]}')
            lines.append("")
        path = Path(output_path)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def export_csv(self, transcript_id: int, output_path) -> Path:
        segments = self.segments(transcript_id)
        path = Path(output_path)
        fields = ["segment_index", "start_seconds", "end_seconds", "speaker", "confidence", "text"]
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for _, row in segments.iterrows():
                writer.writerow({field: row.get(field) for field in fields})
        return path

    def export_youtube_chapters(self, transcript_id: int, output_path) -> Path:
        chapters = self.chapters(transcript_id)
        if chapters.empty:
            raise ValueError("Build chapters before exporting YouTube chapters.")
        lines = []
        for _, row in chapters.iterrows():
            lines.append(f'{self._youtube_clock(row["start_seconds"])} {row["title"]}')
        path = Path(output_path)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def export_marker_csv(self, transcript_id: int, output_path, format_name: str = "premiere") -> Path:
        chapters = self.chapters(transcript_id)
        if chapters.empty:
            raise ValueError("Build chapters before exporting markers.")
        path = Path(output_path)
        normalized = format_name.lower()
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            if normalized == "premiere":
                fields = ["Marker Name", "Description", "In", "Out", "Marker Type"]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for _, row in chapters.iterrows():
                    writer.writerow({
                        "Marker Name": row["title"],
                        "Description": row.get("summary") or "",
                        "In": self._clock_export(row["start_seconds"], milliseconds=True),
                        "Out": self._clock_export(row["end_seconds"], milliseconds=True),
                        "Marker Type": "Comment",
                    })
            elif normalized == "resolve":
                fields = ["Name", "Start", "End", "Notes", "Color"]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for _, row in chapters.iterrows():
                    writer.writerow({
                        "Name": row["title"],
                        "Start": self._clock_export(row["start_seconds"], milliseconds=True),
                        "End": self._clock_export(row["end_seconds"], milliseconds=True),
                        "Notes": row.get("summary") or "",
                        "Color": "Purple",
                    })
            else:
                raise ValueError("Marker format must be 'premiere' or 'resolve'.")
        return path

    def export_fcpxml(self, transcript_id: int, output_path) -> Path:
        transcript = self.transcript(transcript_id)
        chapters = self.chapters(transcript_id)
        root = Element("fcpxml", version="1.10")
        resources = SubElement(root, "resources")
        SubElement(resources, "format", id="r1", name="FFVideoFormat1080p30")
        library = SubElement(root, "library")
        event = SubElement(library, "event", name=str(transcript.get("title") or "Transcript"))
        project = SubElement(event, "project", name=str(transcript.get("title") or "Transcript"))
        sequence = SubElement(project, "sequence", format="r1", duration=self._fcpx_time(transcript.get("duration_seconds") or 0))
        spine = SubElement(sequence, "spine")
        gap = SubElement(spine, "gap", name="Transcript Timeline", offset="0s", start="0s", duration=self._fcpx_time(transcript.get("duration_seconds") or 0))
        for _, row in chapters.iterrows():
            SubElement(
                gap,
                "marker",
                start=self._fcpx_time(row["start_seconds"]),
                duration="1/30s",
                value=str(row["title"]),
                note=str(row.get("summary") or ""),
            )
        path = Path(output_path)
        ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        return path

    def export_review_json(self, transcript_id: int, output_path) -> Path:
        transcript = self.transcript(transcript_id)
        payload = {
            "transcript": transcript,
            "statistics": self.transcript_statistics(transcript_id),
            "segments": self.segments(transcript_id).to_dict("records"),
            "chapters": self.chapters(transcript_id).to_dict("records"),
            "speakers": self.speakers(transcript_id).to_dict("records"),
        }
        path = Path(output_path)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    @staticmethod
    def _clock_export(seconds, milliseconds: bool = False) -> str:
        total_ms = max(0, int(round(float(seconds) * 1000)))
        hours, remainder = divmod(total_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1000)
        base = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{base}.{millis:03d}" if milliseconds else base

    @staticmethod
    def _youtube_clock(seconds) -> str:
        total = max(0, int(float(seconds)))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    @staticmethod
    def _fcpx_time(seconds) -> str:
        frames = max(0, round(float(seconds) * 30))
        return f"{frames}/30s"
