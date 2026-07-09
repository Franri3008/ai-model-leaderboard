import json
import re
from io import StringIO

import pandas as pd
import requests

from scraper_common import USER_AGENTS, print_step

def _parse_model_metadata(bundle):
    map_match = re.search(r'=\{"[^"]+":\{url:"', bundle);
    if not map_match:
        raise RuntimeError("LiveBench model metadata map not found in JS bundle")
    map_start = map_match.start() + 1;
    depth = 0;
    map_end = None;
    for j in range(map_start, len(bundle)):
        if bundle[j] == '{':
            depth += 1;
        elif bundle[j] == '}':
            depth -= 1;
            if depth == 0:
                map_end = j + 1;
                break;
    if map_end is None:
        raise RuntimeError("LiveBench model metadata map not found in JS bundle")
    map_js = bundle[map_start:map_end];
    map_js = re.sub(r'([{,])([A-Za-z_$][\w$]*):', r'\1"\2":', map_js).replace('!0', 'true').replace('!1', 'false');
    meta = json.loads(map_js);
    names, orgs = {}, {};
    for model_id, info in meta.items():
        names[model_id] = info.get("displayName", model_id);
        orgs[model_id] = info.get("organization", "");
        for v in info.get("variants", []):
            names[v.get("rawName", "")] = v.get("displayName", v.get("rawName", ""));
            orgs[v.get("rawName", "")] = info.get("organization", "");
    return names, orgs

def scrape():
    print_step("Fetching LiveBench static data files (site serves raw CSV/JSON since 2026 redesign)...")
    headers = {"User-Agent": USER_AGENTS[0]};
    resp = requests.get("https://livebench.ai/", headers=headers, timeout=30);
    resp.raise_for_status();
    bundle_match = re.search(r'static/js/main\.[0-9a-f]+\.js', resp.text);
    if not bundle_match:
        raise RuntimeError("LiveBench JS bundle not found in page")
    bundle = requests.get(f"https://livebench.ai/{bundle_match.group(0)}", headers=headers, timeout=30).text;

    releases_match = re.search(r'\[(?:"20\d{2}-\d{2}-\d{2}",)+"20\d{2}-\d{2}-\d{2}"\]', bundle);
    if not releases_match:
        raise RuntimeError("LiveBench releases array not found in JS bundle")
    release = max(json.loads(releases_match.group(0))).replace("-", "_");
    print_step(f"Latest LiveBench release: {release}")

    resp = requests.get(f"https://livebench.ai/table_{release}.csv", headers=headers, timeout=30);
    resp.raise_for_status();
    raw_df = pd.read_csv(StringIO(resp.text));
    resp = requests.get(f"https://livebench.ai/categories_{release}.json", headers=headers, timeout=30);
    resp.raise_for_status();
    categories = resp.json();

    names, orgs = _parse_model_metadata(bundle);
    print_step(f"Parsed metadata for {len(names)} model ids")

    rows = [];
    for _, row in raw_df.iterrows():
        cat_avgs = {};
        for cat, cols in categories.items():
            vals = [row[c] for c in cols if c in row and pd.notna(row[c])];
            cat_avgs[cat] = sum(vals) / len(vals) if vals else None;
        if any(v is None for v in cat_avgs.values()):
            continue;  # site drops models missing an entire category
        model_id = row["model"];
        out = {
            "Model": names.get(model_id, model_id),
            "Organization": orgs.get(model_id, ""),
            "Global Average": round(sum(cat_avgs.values()) / len(cat_avgs), 2),
        };
        for cat, avg in cat_avgs.items():
            out[f"{cat} Average"] = round(avg, 2);
        rows.append(out);

    lb_df = pd.DataFrame(rows);
    return lb_df.sort_values("Global Average", ascending=False).reset_index(drop=True)
