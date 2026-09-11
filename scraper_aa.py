"""Read AA's full model dataset, including deprecated models and estimates."""

import json
import math
import re
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
import requests
from bs4 import BeautifulSoup

from scraper_common import print_step

URL = "https://artificialanalysis.ai/leaderboards/models?deprecation=all"


def parse_models(page_source):
    # Next.js splits its server payload across script tags, sometimes mid-string.
    # Decode JSON only; never evaluate scripts received from the provider.
    soup = BeautifulSoup(page_source, "html.parser")
    chunks = []
    decoder = json.JSONDecoder()
    for script in soup.find_all("script"):
        text = (script.string or "").strip()
        prefix = "self.__next_f.push("
        if not text.startswith(prefix):
            continue
        try:
            payload, _ = decoder.raw_decode(text[len(prefix):])
        except ValueError as exc:
            raise RuntimeError("AA embedded payload is malformed") from exc
        if isinstance(payload, list) and len(payload) > 1 and payload[0] == 1 and isinstance(payload[1], str):
            chunks.append(payload[1])

    stream = "".join(chunks)
    candidates = []
    for match in re.finditer(r'"models"\s*:\s*\[', stream):
        try:
            models, _ = decoder.raw_decode(stream, match.end() - 1)
        except ValueError as exc:
            raise RuntimeError("AA model array is truncated") from exc
        if any(isinstance(m, dict) and "intelligenceIndex" in m for m in models):
            candidates.append(models)
    if not candidates:
        raise RuntimeError("AA embedded intelligence dataset not found; refusing a partial table fallback")
    models = max(candidates, key=len)
    version = re.search(r"Intelligence Index\s+(v\d+(?:\.\d+)+)", soup.get_text(" ", strip=True) + " " + stream)
    if not version:
        raise RuntimeError("AA Intelligence Index version not found")

    rows = []
    seen = set()
    for model in models:
        if not isinstance(model, dict) or not all(k in model for k in ("slug", "shortName", "intelligenceIndex", "intelligenceIndexIsEstimated")):
            raise RuntimeError("AA model schema changed")
        slug, name = model["slug"], model["shortName"]
        if not isinstance(slug, str) or not slug or not isinstance(name, str) or not name or slug in seen:
            raise RuntimeError("AA model identity is missing or duplicated")
        seen.add(slug)
        score = model["intelligenceIndex"]
        if score is None:
            continue
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            raise RuntimeError(f"Invalid AA intelligence score for {slug}")
        if not isinstance(model["intelligenceIndexIsEstimated"], bool):
            raise RuntimeError(f"Missing AA estimate status for {slug}")
        rows.append({
            "Model": name,
            # Match AA's displayed integer, rather than truncating its raw float.
            "Intelligence Index": int(Decimal(str(score)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            "Creator": model.get("modelCreatorName", ""),
            "aa_slug": slug,
            "aa_estimated": int(model["intelligenceIndexIsEstimated"]),
            "aa_version": version.group(1),
        })
    if not rows:
        raise RuntimeError("AA dataset contains no intelligence scores")
    return pd.DataFrame(rows)


def scrape():
    print_step("Loading AA embedded model data over HTTP...")
    response = requests.get(URL, timeout=(10, 45))
    response.raise_for_status()
    result = parse_models(response.text)
    print_step(f"AA: {len(result)} scored models, {int(result.aa_estimated.sum())} provider estimates")
    return result
