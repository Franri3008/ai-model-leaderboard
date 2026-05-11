import csv
import json
import os
import tempfile
from pathlib import Path


_NUMERIC_COLUMNS = {
    "processed": {"lma": "int", "aa": "int", "lb": "float"},
    "history":   {"lma": "int", "aa": "int", "lb": "float"},
}


def _coerce_row(row, schema):
    out = {}
    for k, v in row.items():
        if v is None or v == "":
            out[k] = None
            continue
        cast = schema.get(k) if schema else None
        if cast == "int":
            try: out[k] = int(float(v))
            except (TypeError, ValueError): out[k] = None
        elif cast == "float":
            try: out[k] = float(v)
            except (TypeError, ValueError): out[k] = None
        else:
            out[k] = v
    return out


def _read_csv_as_rows(path, schema):
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        return [_coerce_row(r, schema) for r in reader]


def _init_firebase(database_url):
    import firebase_admin
    from firebase_admin import credentials

    if firebase_admin._apps:
        return

    cred_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if cred_json:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(cred_json)
            cred_path = f.name
        cred = credentials.Certificate(cred_path)
    else:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not cred_path:
            raise RuntimeError(
                "Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_APPLICATION_CREDENTIALS_JSON"
            )
        cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {"databaseURL": database_url})


def _build_payloads(base_dir):
    """Read each generated artifact and return {rtdb_path: value}."""
    base = Path(base_dir)
    payloads = {}

    p = base / "data/processed.csv"
    if p.exists():
        payloads["processed"] = _read_csv_as_rows(p, _NUMERIC_COLUMNS["processed"])

    h = base / "data/history.csv"
    if h.exists():
        payloads["history"] = _read_csv_as_rows(h, _NUMERIC_COLUMNS["history"])

    s = base / "data/sources.json"
    if s.exists():
        with open(s) as f:
            payloads["sources"] = json.load(f)

    u = base / "data/untracked_models.json"
    if u.exists():
        with open(u) as f:
            payloads["untracked_models"] = json.load(f)

    m = base / "metadata.json"
    if m.exists():
        with open(m) as f:
            payloads["metadata"] = json.load(f)

    a = base / "alerts.txt"
    if a.exists():
        payloads["alerts"] = a.read_text()

    return payloads


def upload_artifacts(base_dir, database_url=None):
    """
    Push all generated artifacts to RTDB. Returns dict {path: row_count_or_size}
    or None if FIREBASE_DATABASE_URL is unset.
    """
    database_url = database_url or os.environ.get("FIREBASE_DATABASE_URL")
    if not database_url:
        return None

    try:
        import firebase_admin  # noqa: F401
        from firebase_admin import db
    except ImportError as e:
        raise RuntimeError(
            "firebase-admin is not installed. Add `firebase-admin` to "
            "requirements.txt and pip install it."
        ) from e

    _init_firebase(database_url)
    payloads = _build_payloads(base_dir)

    summary = {}
    for path, value in payloads.items():
        db.reference(path).set(value)
        if isinstance(value, list):
            summary[path] = f"{len(value)} rows"
        elif isinstance(value, dict):
            summary[path] = f"{len(value)} keys"
        elif isinstance(value, str):
            summary[path] = f"{len(value)} chars"
        else:
            summary[path] = "ok"
    return summary
