"""One-off backfill for /history dates in Firebase RTDB.

Three models — gemini-3-5-flash, qwen3-7-max, step-3-5-flash — have a single
history entry dated 2026-05-26 because the daily cron repeatedly read a
2026-05-11-frozen history.csv from the repo checkout and re-emitted today's
date. This script changes those dates to when each model was first added to
tracking.json so past snapshots reconstruct correctly.

Idempotent: once a row's date no longer matches "2026-05-26" the row is left
alone, so running this script twice is safe.

Requires FIREBASE_DATABASE_URL and GOOGLE_APPLICATION_CREDENTIALS_JSON (or
GOOGLE_APPLICATION_CREDENTIALS) in env — same secrets the workflow uses. Run
locally:

    FIREBASE_DATABASE_URL=... \\
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json \\
    python scripts/backfill_history.py

Or trigger via workflow_dispatch on a temporary job that invokes this file.
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(BASE_DIR))

from scripts.firebase_upload import _init_firebase
from firebase_admin import db

# (model_id, current bogus date, correct date — first day in tracking.json)
BACKFILL = {
    "gemini-3-5-flash": "2026-05-20",
    "qwen3-7-max":      "2026-05-19",
    "step-3-5-flash":   "2026-05-21",
}
BOGUS_DATE = "2026-05-26"


def main():
    db_url = os.environ.get("FIREBASE_DATABASE_URL")
    if not db_url:
        raise SystemExit("FIREBASE_DATABASE_URL is not set")

    _init_firebase(db_url)
    raw = db.reference("history").get()
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not raw:
        raise SystemExit("/history is empty in Firebase — nothing to backfill")

    rows = [r for r in raw if r]
    changed = 0
    for row in rows:
        model = row.get("model")
        if model in BACKFILL and row.get("date") == BOGUS_DATE:
            print(f"  {model}: {row['date']} -> {BACKFILL[model]}")
            row["date"] = BACKFILL[model]
            changed += 1

    if not changed:
        print("Nothing to change — backfill already applied.")
        return

    db.reference("history").set(rows)
    print(f"\nWrote {len(rows)} rows back to /history ({changed} dates updated).")


if __name__ == "__main__":
    main()
