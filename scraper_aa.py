import math
import os
import re
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
import requests

from scraper_common import print_step

URL = "https://artificialanalysis.ai/api/v2/language/models"
FREE_URL = URL + "/free"
SCORE_KEY = "artificial_analysis_intelligence_index"
TIERS = ("free", "pro", "commercial")
MAX_PAGES = 25
TIMEOUT = (10, 45)
MIN_SCORED_MODELS = 200
MIN_SCORED_NEW_INDEX = 50
PREVIOUS_STATS_PATH = "metadata/stats"
V4_TOKEN = re.compile(r"(?<![a-z0-9])v_?4(?:[._](\d+))?(?![0-9])")
VERSION_FIELD = re.compile(r"version|index", re.IGNORECASE)
MODEL_FIELDS = ("id", "slug", "name", "model_creator", "evaluations", "pricing", "release_date")


def is_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def is_int(value):
    return not isinstance(value, bool) and isinstance(value, int)


def check_page(payload, page):
    if not isinstance(payload, dict) or payload.get("tier") not in TIERS or not isinstance(payload.get("data"), list):
        raise RuntimeError("AA API response schema changed")
    if not is_number(payload.get("intelligence_index_version")):
        raise RuntimeError("AA API response schema changed (intelligence_index_version)")
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict) or not isinstance(pagination.get("has_more"), bool) \
            or not is_int(pagination.get("page")) or not is_int(pagination.get("total_pages")):
        raise RuntimeError("AA API response schema changed (pagination)")
    if pagination["page"] != page:
        raise RuntimeError(f"AA API returned page {pagination['page']} when page {page} was requested")
    if pagination["has_more"] and not payload["data"]:
        raise RuntimeError(f"AA API page {page} is empty but reports more pages")
    if not pagination["has_more"] and page < pagination["total_pages"]:
        raise RuntimeError(f"AA API stopped at page {page} of {pagination['total_pages']}")
    return payload


def version_label(version):
    return version if isinstance(version, str) else f"v{float(version)}"


def check_models(models):
    for model in models:
        if not isinstance(model, dict) or not all(k in model for k in ("slug", "name", "model_creator", "evaluations")):
            raise RuntimeError("AA model schema changed")
        if not isinstance(model["evaluations"], dict) or SCORE_KEY not in model["evaluations"]:
            raise RuntimeError("AA model schema changed")


def evaluation_counts(models):
    counts = {}
    for model in models:
        for key, value in model["evaluations"].items():
            counts[key] = counts.get(key, 0) + (value is not None)
    return counts


def version_fields(models):
    counts = {}
    for model in models:
        for key, value in model.items():
            if key not in MODEL_FIELDS and VERSION_FIELD.search(key):
                counts[key] = counts.get(key, 0) + (value is not None)
    return counts


def log_fields(models):
    counts = evaluation_counts(models)
    listed = ", ".join(f"{k}={counts[k]}" for k in sorted(counts))
    print_step(f"AA: evaluations keys with non-null counts over {len(models)} models: {listed or 'none'}")
    fields = version_fields(models)
    listed = ", ".join(f"{k}={fields[k]}" for k in sorted(fields))
    print_step(f"AA: top-level model fields that look like an index version: {listed or 'none'}")
    return counts


def v4_candidates(counts):
    found = []
    for key, count in counts.items():
        match = V4_TOKEN.search(key.lower())
        if key != SCORE_KEY and "intelligence" in key.lower() and match:
            found.append((count, key, f"v4.{match.group(1)}" if match.group(1) else "v4"))
    return sorted(found, reverse=True)


def choose_rule(models, version):
    counts = log_fields(models)
    candidates = v4_candidates(counts)
    if candidates and candidates[0][0] >= MIN_SCORED_MODELS:
        count, key, label = candidates[0]
        return dict(name="v4", key=key, label=label, floor=MIN_SCORED_MODELS, same_version_only=False,
                    reason=f"{key} has {count} models with a value, at least {MIN_SCORED_MODELS}")
    if candidates:
        why = ", ".join(f"{key} has {count}" for count, key, _ in candidates) + f", below {MIN_SCORED_MODELS}"
    else:
        why = "no v4 intelligence index key in evaluations"
    return dict(name="current", key=SCORE_KEY, label=version_label(version), floor=MIN_SCORED_NEW_INDEX,
                same_version_only=True, reason=why)


def parse_models(models, version, key=SCORE_KEY):
    rows = []
    seen = set()
    label = version_label(version)
    check_models(models)
    for model in models:
        evaluations, creator = model["evaluations"], model["model_creator"]
        if not isinstance(creator, (dict, type(None))):
            raise RuntimeError("AA model schema changed")
        slug, name = model["slug"], model["name"]
        if not isinstance(slug, str) or not slug or not isinstance(name, str) or not name or slug in seen:
            raise RuntimeError("AA model identity is missing or duplicated")
        seen.add(slug)
        score = evaluations.get(key)
        if score is None:
            continue
        if not is_number(score) or not 0 <= score <= 100:
            raise RuntimeError(f"Invalid AA intelligence score for {slug}")
        rows.append({
            "Model": name,
            "Intelligence Index": int(Decimal(str(score)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            "Creator": (creator or {}).get("name") or "",
            "aa_slug": slug,
            "aa_estimated": None,
            "aa_version": label,
        })
    if not rows:
        raise RuntimeError("AA dataset contains no intelligence scores")
    return pd.DataFrame(rows)


def error_message(response):
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("error", ""))[:200] if isinstance(body, dict) else ""


def get_page(url, key, page):
    response = requests.get(url, headers={"x-api-key": key}, params={"page": page}, timeout=TIMEOUT)
    if response.status_code == 200:
        try:
            return response, response.json()
        except ValueError as exc:
            raise RuntimeError(f"AA API returned invalid JSON on page {page}") from exc
    return response, None


def fail(response, url, page):
    detail = error_message(response)
    status = response.status_code
    hint = {
        401: " (AA_API_KEY missing or invalid)",
        410: " (endpoint retired, see https://artificialanalysis.ai/data-api/migrate-v2-data)",
        429: f" (daily quota used up, retry after {response.headers.get('Retry-After', '?')}s)",
    }.get(status, "")
    raise RuntimeError(f"AA API returned HTTP {status} for {url} page {page}{hint}" + (f": {detail}" if detail else ""))


def first_page(key):
    response, payload = get_page(URL, key, 1)
    if payload is not None:
        return URL, payload
    if response.status_code != 403:
        fail(response, URL, 1)
    print_step(f"AA: Pro list refused with HTTP 403 ({error_message(response) or 'no detail'}), using the free list", "WARNING")
    response, payload = get_page(FREE_URL, key, 1)
    if payload is None:
        fail(response, FREE_URL, 1)
    return FREE_URL, payload


def fetch_models(key):
    url, payload = first_page(key)
    pages = [check_page(payload, 1)]
    while pages[-1]["pagination"]["has_more"]:
        page = len(pages) + 1
        if page > MAX_PAGES:
            raise RuntimeError(f"AA API still reports more pages after {MAX_PAGES} pages")
        response, payload = get_page(url, key, page)
        if payload is None:
            fail(response, url, page)
        pages.append(check_page(payload, page))
    versions = {p["intelligence_index_version"] for p in pages}
    tiers = {p["tier"] for p in pages}
    if len(versions) > 1 or len(tiers) > 1:
        raise RuntimeError(f"AA API pages disagree on index version {sorted(versions)} or tier {sorted(tiers)}")
    models = [m for p in pages for m in p["data"]]
    return url, pages, models


def previous_run():
    url = os.environ.get("FIREBASE_DATABASE_URL", "").strip()
    if not url:
        return None, None
    try:
        from firebase_admin import db
        from scripts.firebase_upload import _init_firebase
        _init_firebase(url)
        stats = db.reference(PREVIOUS_STATS_PATH).get()
    except Exception as exc:
        print_step(f"AA: previous run stats unavailable ({type(exc).__name__})", "WARNING")
        return None, None
    if not isinstance(stats, dict):
        return None, None
    count = (stats.get("rows_scraped") or {}).get("artificial_analysis") if isinstance(stats.get("rows_scraped"), dict) else None
    version = stats.get("aa_index_version")
    count = count if is_int(count) and count > 0 else None
    version = version if isinstance(version, str) and version else None
    return count, version


def guard_floor(rule, previous, previous_version):
    if not previous:
        return rule["floor"], "no previous count"
    if rule["same_version_only"] and previous_version != rule["label"]:
        return rule["floor"], f"previous run was on index {previous_version or 'unknown'}, half-of-previous skipped"
    return max(rule["floor"], previous // 2), f"previous run {previous} on index {previous_version or 'unknown'}"


def check_scored_count(count, rule, previous, previous_version):
    floor, basis = guard_floor(rule, previous, previous_version)
    print_step(f"AA: size guard floor {floor} ({basis}, fixed minimum {rule['floor']}), {count} scored")
    if count < floor:
        raise RuntimeError(
            f"AA returned {count} scored models, below the floor of {floor} "
            f"({basis}, fixed minimum {rule['floor']})"
        )


def scrape():
    key = os.environ.get("AA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("AA_API_KEY is not set")
    print_step("Loading AA models from the official API...")
    url, pages, models = fetch_models(key)
    first = pages[0]
    check_models(models)
    rule = choose_rule(models, first["intelligence_index_version"])
    print_step(f"AA: rule {rule['name']} uses {rule['key']} as {rule['label']} because {rule['reason']}")
    result = parse_models(models, rule["label"], rule["key"])
    extra = sorted(k for k in first if k not in ("tier", "intelligence_index_version", "pagination", "data"))
    print_step(
        f"AA: tier {first['tier']} via {url.rsplit('/api/v2', 1)[-1]}, {len(pages)} pages "
        f"(page size {first['pagination'].get('page_size')}, total_pages {first['pagination']['total_pages']}), "
        f"{len(models)} models, {len(result)} scored, index {rule['label']}, "
        f"response index {version_label(first['intelligence_index_version'])}, extra top-level keys {extra}"
    )
    check_scored_count(len(result), rule, *previous_run())
    return result
