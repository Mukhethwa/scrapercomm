"""Runtime settings, loaded from environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parents[2]  # project root (…/scraper)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class Settings:
    def __init__(self) -> None:
        self.database_url = os.environ.get(
            "DATABASE_URL", "postgresql://gabs:gabs@localhost:5433/gabs"
        )
        self.base_url = os.environ.get("GABS_BASE_URL", "https://www.gabs.co.za/")
        self.timetable_url = self.base_url.rstrip("/") + "/Timetable.aspx"
        self.user_agent = os.environ.get("GABS_USER_AGENT", _DEFAULT_UA)

        data_dir = os.environ.get("GABS_DATA_DIR")
        self.data_dir = Path(data_dir) if data_dir else _ROOT / "data"
        self.pdf_dir = self.data_dir / "pdfs"
        self.manifest_path = self.data_dir / "manifest.json"
        self.schema_path = _ROOT / "sql" / "schema.sql"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
