import argparse
import os
import sys
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(BASE_DIR))

from scripts.firebase_upload import _init_firebase
from firebase_admin import db


ID_RENAMES = {
    "gpt-5.5": "gpt-5-5",
    "gpt-5.4-mini": "gpt-5-4-mini",
    "gpt-5.4": "gpt-5-4",
    "gpt-5.2": "gpt-5-2",
    "qwen3-7": "qwen3-7-max",
}


def migrate_history(raw):
    """Return a migrated copy and per-ID replacement counts."""
    migrated = deepcopy(raw)
    rows = migrated.values() if isinstance(migrated, dict) else migrated
    counts = Counter()

    for row in rows:
        if not isinstance(row, dict):
            continue
        old_id = row.get("model")
        new_id = ID_RENAMES.get(old_id)
        if new_id:
            row["model"] = new_id
            counts[old_id] += 1

    return migrated, counts


def row_count(raw):
    rows = raw.values() if isinstance(raw, dict) else raw
    return sum(1 for row in rows if isinstance(row, dict))


def print_counts(counts):
    for old_id, new_id in ID_RENAMES.items():
        print(f"  {old_id} -> {new_id}: {counts.get(old_id, 0)} row(s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up and transactionally replace /history. Default is dry-run.",
    )
    args = parser.parse_args()

    db_url = os.environ.get("FIREBASE_DATABASE_URL")
    if not db_url:
        raise SystemExit("FIREBASE_DATABASE_URL is not set")

    _init_firebase(db_url)
    history_ref = db.reference("history")
    original = history_ref.get()
    if not isinstance(original, (list, dict)) or not original:
        raise SystemExit("/history is empty or has an unexpected shape")

    migrated, counts = migrate_history(original)
    changed = sum(counts.values())
    print(f"History rows: {row_count(original)}")
    print_counts(counts)
    print(f"Total rows to update: {changed}")

    if not changed:
        print("Nothing to change; all history IDs are already canonical.")
        return
    if not args.apply:
        print("Dry run only. Re-run with --apply to write the migration.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y_%m_%d_%H%M%S_utc")
    backup_path = f"history_backups/id_migration_{stamp}"
    db.reference(backup_path).set(original)
    print(f"Backup written to /{backup_path}")

    def transaction_update(current):
        if not isinstance(current, (list, dict)):
            raise RuntimeError("/history changed to an unexpected shape")
        updated, _ = migrate_history(current)
        return updated

    history_ref.transaction(transaction_update)

    verified = history_ref.get()
    _, remaining = migrate_history(verified)
    remaining_count = sum(remaining.values())
    if remaining_count:
        raise RuntimeError(f"Migration verification failed: {remaining_count} legacy row(s) remain")
    if row_count(verified) != row_count(original):
        raise RuntimeError("Migration verification failed: history row count changed")

    print(f"Migration complete: {changed} row(s) canonicalized; verification passed.")


if __name__ == "__main__":
    main()
