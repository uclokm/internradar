"""Where InternRadar keeps things.

    data/radar.db        public job postings collected by the daily run (committed by CI)
    data/jobs.csv        the same postings as CSV, for easy diffs
    data/changes/        daily change reports
    data/private/        YOUR data: applications and hand-added roles (git-ignored)
    data/demo/           fictional demo data so a fresh clone has something to show
    config/master_cv.yaml  your real CV (git-ignored); master_cv.example.yaml is the public stand-in
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = Path(os.environ.get("RADAR_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("RADAR_DB", DATA / "radar.db"))
PRIVATE = Path(os.environ.get("RADAR_PRIVATE_DIR", DATA / "private"))
DEMO = ROOT / "data" / "demo"
