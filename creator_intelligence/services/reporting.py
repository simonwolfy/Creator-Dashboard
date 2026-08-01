from pathlib import Path
from datetime import datetime

class ReportingService:
    def export_csv(self, frame, export_dir: Path, prefix: str):
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = export_dir / f"{prefix}_{stamp}.csv"
        frame.to_csv(path, index=False)
        return path
