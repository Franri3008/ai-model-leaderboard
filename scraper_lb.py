import json
import re
from io import StringIO

import pandas as pd
import requests

from scraper_common import USER_AGENTS, print_step

BASE_URL = "https://livebench.ai";
WEIGHTS_KEY = "_overall_weights";

def _js_object_end(bundle, start):
    depth = 0;
    in_str = None;
    j = start;
    while j < len(bundle):
        ch = bundle[j];
        if in_str:
            if ch == "\\":
                j += 2;
                continue;
            if ch == in_str:
                in_str = None;
        elif ch in "\"'`":
            in_str = ch;
        elif ch == "{":
            depth += 1;
        elif ch == "}":
            depth -= 1;
            if depth == 0:
                return j + 1
        j += 1;
    return None

def _js_to_json(map_js):
    map_js = re.sub(r'([{,])([A-Za-z_$][\w$]*):', r'\1"\2":', map_js);
    return json.loads(map_js.replace("!0", "true").replace("!1", "false"))

def _parse_metadata_maps(bundle):
    maps = [];
    for map_match in re.finditer(r'=\{"[^"]+":\{(?:url|displayName|organization):"', bundle):
        map_start = map_match.start() + 1;
        map_end = _js_object_end(bundle, map_start);
        if map_end is None:
            continue;
        try:
            meta = _js_to_json(bundle[map_start:map_end]);
        except json.JSONDecodeError:
            continue;
        entries = {};
        for model_id, info in meta.items():
            entries[model_id] = info;
            for v in info.get("variants", []) or []:
                raw = v.get("rawName");
                if raw:
                    entries[raw] = {**info, **v};
        maps.append(entries);
    if not maps:
        raise RuntimeError("LiveBench model metadata map not found in JS bundle")
    return maps

def _find_releases(bundle):
    releases = set();
    for arr in re.finditer(r'\[(?:"20\d{6}",)*"20\d{6}"\]', bundle):
        releases.update(json.loads(arr.group(0)));
    if not releases:
        raise RuntimeError("LiveBench 2.0 releases array not found in JS bundle")
    return sorted(releases, reverse=True)

def _mean(values):
    vals = [];
    for v in values:
        try:
            f = float(v);
        except (TypeError, ValueError):
            continue;
        if not pd.isna(f):
            vals.append(f);
    return sum(vals) / len(vals) if vals else None

def scrape():
    print_step("Fetching LiveBench 2.0 release files (data/<release>/table.csv + categories.json)...")
    headers = {"User-Agent": USER_AGENTS[0]};
    resp = requests.get(f"{BASE_URL}/", headers=headers, timeout=30);
    resp.raise_for_status();
    bundle_match = re.search(r'static/js/main\.[0-9a-f]+\.js', resp.text);
    if not bundle_match:
        raise RuntimeError("LiveBench JS bundle not found in page")
    bundle = requests.get(f"{BASE_URL}/{bundle_match.group(0)}", headers=headers, timeout=30).text;

    cache_match = re.search(r'\./data/\$\{[^}]+\}`\s*,\s*\w+\s*=\s*"(\?v=[^"]+)"', bundle);
    cache = cache_match.group(1) if cache_match else "";

    release, table_text = None, None;
    for candidate in _find_releases(bundle):
        resp = requests.get(f"{BASE_URL}/data/{candidate}/table.csv{cache}", headers=headers, timeout=30);
        if resp.ok and resp.text.lstrip().startswith("model"):
            release, table_text = candidate, resp.text;
            break;
        print_step(f"⚠ LiveBench release {candidate} has no table.csv ({resp.status_code}), trying older", "WARN");
    if release is None:
        raise RuntimeError("No LiveBench 2.0 release with a readable table.csv")
    print_step(f"Latest LiveBench 2.0 release: {release}")

    raw_df = pd.read_csv(StringIO(table_text));
    resp = requests.get(f"{BASE_URL}/data/{release}/categories.json{cache}", headers=headers, timeout=30);
    resp.raise_for_status();
    categories = dict(resp.json());
    raw_weights = categories.pop(WEIGHTS_KEY, None) or {};
    weights = {};
    for cat, w in raw_weights.items():
        try:
            w = float(w);
        except (TypeError, ValueError):
            continue;
        if cat in categories and w > 0 and w != float("inf"):
            weights[cat] = w;
    print_step(f"Categories: {list(categories)} / Overall weights: {weights or 'none (plain mean)'}")

    maps = _parse_metadata_maps(bundle);
    table_ids = set(raw_df["model"].astype(str));
    meta = max(maps, key=lambda m: len(table_ids & set(m)));
    print_step(f"Using metadata map with {len(meta)} ids, covering {len(table_ids & set(meta))}/{len(table_ids)} table rows")

    rows = [];
    for _, row in raw_df.iterrows():
        model_id = str(row["model"]);
        info = meta.get(model_id);
        if info is None:
            print_step(f"⚠ LiveBench row {model_id} has no metadata, the site hides it, skipping", "WARN");
            continue;
        if info.get("finetune"):
            continue;
        cat_avgs = {cat: _mean(row[c] for c in cols if c in row) for cat, cols in categories.items()};
        num, den = 0.0, 0.0;
        for cat, avg in cat_avgs.items():
            w = weights.get(cat, 1.0);
            if avg is not None:
                num += avg * w;
                den += w;
        if den == 0:
            continue;
        out = {
            "Model": info.get("displayName") or model_id,
            "Organization": info.get("organization", ""),
            "Global Average": round(num / den, 2),
        };
        for cat, avg in cat_avgs.items():
            out[f"{cat} Average"] = round(avg, 2) if avg is not None else None;
        rows.append(out);

    lb_df = pd.DataFrame(rows);
    return lb_df.sort_values("Global Average", ascending=False).reset_index(drop=True)
