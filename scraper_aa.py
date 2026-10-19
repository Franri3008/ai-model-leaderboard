import math
import os
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
import requests

from scraper_common import print_step

URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
SCORE_KEY = "artificial_analysis_intelligence_index"


def parse_models(payload):
    if not isinstance(payload, dict) or payload.get("status") != 200 or not isinstance(payload.get("data"), list):
        raise RuntimeError("AA API response schema changed")

    rows = []
    seen = set()
    for model in payload["data"]:
        if not isinstance(model, dict) or not all(k in model for k in ("slug", "name", "model_creator", "evaluations")):
            raise RuntimeError("AA model schema changed")
        evaluations, creator = model["evaluations"], model["model_creator"]
        if not isinstance(evaluations, dict) or SCORE_KEY not in evaluations or not isinstance(creator, dict):
            raise RuntimeError("AA model schema changed")
        slug, name = model["slug"], model["name"]
        if not isinstance(slug, str) or not slug or not isinstance(name, str) or not name or slug in seen:
            raise RuntimeError("AA model identity is missing or duplicated")
        seen.add(slug)
        score = evaluations[SCORE_KEY]
        if score is None:
            continue
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            raise RuntimeError(f"Invalid AA intelligence score for {slug}")
        rows.append({
            "Model": name,
            "Intelligence Index": int(Decimal(str(score)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            "Creator": creator.get("name") or "",
            "aa_slug": slug,
            "aa_estimated": None,
            "aa_version": "",
        })
    if not rows:
        raise RuntimeError("AA dataset contains no intelligence scores")
    return pd.DataFrame(rows)


def scrape():
    key = os.environ.get("AA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("AA_API_KEY is not set")
    print_step("Loading AA models from the official API...")
    response = requests.get(URL, headers={"x-api-key": key}, timeout=(10, 45))
    if response.status_code != 200:
        raise RuntimeError(f"AA API returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("AA API returned invalid JSON") from exc
    result = parse_models(payload)
    print_step(f"AA: {len(result)} scored models")
    return result
