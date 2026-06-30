import re
import json
import random
import requests
import time
import pandas as pd
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from rapidfuzz import process, fuzz

BASE_DIR = Path(__file__).parent.absolute()
STRIP_SELECTORS = "svg,img,picture,source,use,i,[aria-hidden='true'],*[hidden],.sr-only,.sr_only,.srOnly,.visually-hidden,[class*='icon'],i[class*='fa-']"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

def print_step(message, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S");
    prefix = ">>>" if level == "INFO" else "***";
    print(f"\n{prefix} [{timestamp}] {message}")

def normalize_model_name(name):
    norm = str(name).lower();
    norm = re.sub(r'^(meta|google|anthropic|mistral|openai)[-\s/]+', '', norm);
    norm = re.sub(r'[-_\s\(]+(instruct|chat|hf|v\.?\d+)\)?$', '', norm);
    norm = re.sub(r'[\s\.\-_]+', '', norm);
    return norm

def extract_numeric_score(score_value):
    if pd.isna(score_value):
        return None
    score_str = str(score_value).strip();

    match = re.search(r'-?\d+\.?\d*', score_str);
    if match:
        return match.group()
    return None

def clean_text(tag, extra_selectors=None):
    clone = BeautifulSoup(str(tag), "html.parser");
    selectors = STRIP_SELECTORS;
    if extra_selectors:
        selectors += "," + extra_selectors;
    for el in clone.select(selectors):
        el.decompose();
    return " ".join(clone.stripped_strings)

def get_chrome_driver(headless=True):
    opts = Options();
    if headless:
        opts.add_argument("--headless=new");
    opts.add_argument("--disable-gpu");
    opts.add_argument("--no-sandbox");
    opts.add_argument(f"user-agent={random.choice(USER_AGENTS)}");
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

def render_page(url, wait_selector, timeout=60, attempts=3, post_load=None):
    last_err = None;
    for n in range(1, attempts + 1):
        driver = get_chrome_driver();
        try:
            driver.get(url);
            WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector)));
            if post_load:
                post_load(driver);
            return driver.page_source;
        except Exception as e:
            last_err = e;
            print_step(f"⚠ Render attempt {n}/{attempts} failed for {url}: {type(e).__name__}", "WARN");
            if n < attempts:
                time.sleep(5 * n);
        finally:
            driver.quit();
    raise RuntimeError(f"render_page failed after {attempts} attempts for {url}") from last_err

def extract_table_data(table, skip_first_empty=False, extra_selectors=None):
    thead = table.find("thead");
    header_cells = thead.select("tr")[-1].find_all("th") if thead and thead.select("tr") else table.select("tr th");
    headers = [clean_text(th, extra_selectors) for idx, th in enumerate(header_cells) if not (skip_first_empty and idx == 0 and clean_text(th, extra_selectors) == "")];

    tbody = table.find("tbody") or table;
    rows = [];
    for tr in tbody.find_all("tr", recursive=False):
        cells = tr.find_all(["td", "th"], recursive=False);
        if not cells:
            continue;
        row = [clean_text(td, extra_selectors) for idx, td in enumerate(cells) if not (skip_first_empty and idx == 0 and clean_text(td, extra_selectors) == "")];
        if len(row) != len(headers):
            row = (row + [""] * len(headers))[:len(headers)];
        rows.append(row);
    return pd.DataFrame(rows, columns=headers)

def match_source_score(scraped_df, lookup_value, model_keywords, score_keywords, score_type="int"):
    if scraped_df is None or pd.isna(lookup_value):
        return None
    lookup_name = str(lookup_value).strip();
    if not lookup_name:
        return None

    model_col = None;
    for col in scraped_df.columns:
        if any(kw in col.lower() for kw in model_keywords):
            model_col = col;
            break;
    if not model_col:
        model_col = scraped_df.columns[0];

    col_vals = scraped_df[model_col].astype(str).str.strip();
    match = scraped_df[col_vals.str.lower() == lookup_name.lower()];
    if match.empty:
        return None

    for col in scraped_df.columns:
        if any(kw in col.lower() for kw in score_keywords):
            score = match.iloc[0][col];
            numeric_score = extract_numeric_score(score);
            if numeric_score:
                try:
                    if score_type == "int":
                        return int(float(numeric_score))
                    else:
                        return float(numeric_score)
                except (ValueError, TypeError):
                    pass;
            break;
    return None

def check_tracking_status(model_name, fixed_df, lookup_col):
    if pd.isna(model_name):
        return False, None

    for idx, row in fixed_df.iterrows():
        lookup = row[lookup_col];
        if pd.notna(lookup) and str(lookup).strip():
            if str(lookup).strip().lower() == str(model_name).strip().lower():  # exact, consistent with score matching
                return True, row['name'];
    return False, None

def get_untracked_models(df, source_name, score_keywords, fixed_df, lookup_col, top_n=30):
    untracked = [];
    if df is None or df.empty:
        return untracked

    model_col = None;
    for col in df.columns:
        if 'model' in col.lower() or 'name' in col.lower():
            model_col = col;
            break;
    if not model_col:
        model_col = df.columns[0];

    score_col = None;
    for col in df.columns:
        if any(keyword in col.lower() for keyword in score_keywords):
            score_col = col;
            break;

    if not score_col:
        return untracked

    df = df.copy();
    df['__numeric_score'] = df[score_col].apply(lambda x: float(extract_numeric_score(x) or 0));

    top_models = df.sort_values('__numeric_score', ascending=False).head(top_n);

    for rank, (idx, row) in enumerate(top_models.iterrows(), 1):
        raw_name = str(row[model_col]).strip();
        is_tracked, _ = check_tracking_status(raw_name, fixed_df, lookup_col);

        if not is_tracked:
            untracked.append({
                "source": source_name,
                "raw_name": raw_name,
                "norm_name": normalize_model_name(raw_name),
                "rank": rank,
                "score": row['__numeric_score']
            });

    return untracked

def build_sources_json(lma_df, aa_df, lb_df, fixed_df, models_json_path, output_path):
    with open(models_json_path) as f:
        models = json.load(f);
    alias_to_logo = {};
    for m in models:
        for alias in (m.get("aliases") or []):
            alias_to_logo[str(alias).strip().lower()] = m["id"];

    source_specs = {
        "lma": {
            "df": lma_df,
            "model_kw": ["model"],
            "score_kw": ["arena", "elo", "score", "rating"],
            "provider_kw": ["provider", "organization", "creator"],
            "score_type": "int",
            "lookup_col": "lma_lookup",
        },
        "aa": {
            "df": aa_df,
            "model_kw": ["model", "name"],
            "score_kw": ["quality", "score", "index"],
            "provider_kw": ["creator", "organization", "provider"],
            "score_type": "int",
            "lookup_col": "aa_lookup",
        },
        "lb": {
            "df": lb_df,
            "model_kw": ["model"],
            "score_kw": ["average", "overall", "total", "score"],
            "provider_kw": ["organization", "creator", "provider"],
            "score_type": "float",
            "lookup_col": "lb_lookup",
        },
    };

    sources = {};
    for key, spec in source_specs.items():
        df = spec["df"];
        if df is None or df.empty:
            sources[key] = [];
            continue;

        model_col = next((c for c in df.columns if any(kw in c.lower() for kw in spec["model_kw"])), df.columns[0]);
        score_col = next((c for c in df.columns if any(kw in c.lower() for kw in spec["score_kw"])), None);
        provider_col = next((c for c in df.columns if any(kw in c.lower() for kw in spec["provider_kw"])), None);
        if not score_col:
            sources[key] = [];
            continue;

        d = df.copy();
        d["__score"] = d[score_col].apply(lambda x: float(extract_numeric_score(x) or 0));
        d = d[d["__score"] > 0].sort_values("__score", ascending=False);

        rows = [];
        used_tracked_ids = set();
        for _, r in d.iterrows():
            raw_name = str(r[model_col]).strip();
            if not raw_name:
                continue;
            numeric = r["__score"];
            score = int(numeric) if spec["score_type"] == "int" else round(float(numeric), 4);
            provider_text = "";
            if provider_col is not None and not pd.isna(r[provider_col]):
                provider_text = str(r[provider_col]).strip();

            raw_lower = raw_name.lower();
            tracked_match = None;
            best_len = -1;
            for _, t in fixed_df.iterrows():
                model_id = str(t["model"]);
                if model_id in used_tracked_ids:
                    continue;
                lookup = t[spec["lookup_col"]];
                if not pd.notna(lookup):
                    continue;
                lk = str(lookup).strip().lower();
                if not lk or lk != raw_lower:
                    continue;
                if len(lk) > best_len:
                    tracked_match = t;
                    best_len = len(lk);

            if tracked_match is not None:
                used_tracked_ids.add(str(tracked_match["model"]));
                rows.append({
                    "id": str(tracked_match["model"]),
                    "name": str(tracked_match["name"]),
                    "score": score,
                    "logo": str(tracked_match["logo"]) if pd.notna(tracked_match["logo"]) else None,
                    "geo": str(tracked_match["geo"]) if pd.notna(tracked_match["geo"]) else None,
                    "provider": provider_text or None,
                    "tracked": True,
                });
            else:
                logo = None;
                if provider_text:
                    pt_lower = provider_text.lower();
                    logo = alias_to_logo.get(pt_lower);
                    if not logo:
                        for part in re.split(r"\s*[·|/,]\s*", provider_text):
                            cand = part.strip().lower();
                            if cand and cand in alias_to_logo:
                                logo = alias_to_logo[cand];
                                break;
                synthetic_id = f"{key}:" + re.sub(r"[^a-z0-9]+", "-", raw_name.lower()).strip("-");
                rows.append({
                    "id": synthetic_id,
                    "name": raw_name,
                    "score": score,
                    "logo": logo,
                    "geo": None,
                    "provider": provider_text or None,
                    "tracked": False,
                });

        sources[key] = rows;

    with open(output_path, "w") as f:
        json.dump(sources, f, indent=2);

    return sources

def _load_history_from_firebase():
    import os as _os
    db_url = _os.environ.get("FIREBASE_DATABASE_URL")
    if not db_url:
        return None
    import sys as _sys
    _sys.path.insert(0, str(BASE_DIR))
    from scripts.firebase_upload import _init_firebase
    from firebase_admin import db
    _init_firebase(db_url)
    raw = db.reference("history").get()
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not raw:
        return pd.DataFrame(columns=["date", "model", "lma", "aa", "lb"])
    df = pd.DataFrame([r for r in raw if r])
    for col in ["date", "model", "lma", "aa", "lb"]:
        if col not in df.columns:
            df[col] = None
    return df[["date", "model", "lma", "aa", "lb"]]


def _load_untracked_from_firebase():
    import os as _os
    db_url = _os.environ.get("FIREBASE_DATABASE_URL")
    if not db_url:
        return None
    import sys as _sys
    _sys.path.insert(0, str(BASE_DIR))
    from scripts.firebase_upload import _init_firebase
    from firebase_admin import db
    _init_firebase(db_url)
    raw = db.reference("untracked_models").get()
    return raw if isinstance(raw, dict) else {}

def append_history(result, history_file):
    today = datetime.now().strftime("%Y-%m-%d");

    history = _load_history_from_firebase();
    if history is None:
        if history_file.exists():
            history = pd.read_csv(history_file, sep=";");
        else:
            history = pd.DataFrame(columns=["date", "model", "lma", "aa", "lb"]);

    new_rows = [];
    for _, row in result.iterrows():
        prev = history[history["model"] == row["model"]];
        if prev.empty:
            new_rows.append({"date": today, "model": row["model"], "lma": row["lma"], "aa": row["aa"], "lb": row["lb"]});
        else:
            last = prev.iloc[-1];
            changed = False;
            for col in ["lma", "aa", "lb"]:
                old_val = last[col];
                new_val = row[col];
                if pd.isna(old_val) and pd.isna(new_val):
                    continue;
                if pd.isna(old_val) != pd.isna(new_val):
                    changed = True;
                    break;
                if float(old_val) != float(new_val):
                    changed = True;
                    break;
            if changed:
                new_rows.append({"date": today, "model": row["model"], "lma": row["lma"], "aa": row["aa"], "lb": row["lb"]});

    if new_rows:
        history = pd.concat([history, pd.DataFrame(new_rows)], ignore_index=True);
        print_step(f"Appended {len(new_rows)} changed rows to history");
    else:
        print_step("No score changes detected");

    history.to_csv(history_file, sep=";", index=False);

    return len(new_rows)


# ============================================================================
# STEP 1: SCRAPE LEADERBOARDS
# ============================================================================
print("=" * 80)
print_step("STARTING LEADERBOARD UPDATE", "START")
print("=" * 80)

data_dir = BASE_DIR / "data/scraped";
data_dir.mkdir(parents=True, exist_ok=True);
print_step(f"Data directory: {data_dir.absolute()}")

print_step("[1/3] Scraping LMArena Text Leaderboard")
print_step("Fetching page with requests...")
resp = requests.get("https://lmarena.ai/leaderboard/text", headers={
    "User-Agent": USER_AGENTS[0], "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache", "Pragma": "no-cache"
}, timeout=30);
resp.raise_for_status();
print_step("Parsing HTML and extracting table...")
soup = BeautifulSoup(resp.text, "html.parser");
table = soup.select_one("table.w-full.caption-bottom.text-sm");
if not table:
    raise ValueError("LMArena table not found")
lma_df = extract_table_data(table, extra_selectors="span.text-text-secondary");
lma_tbody = table.find("tbody") or table;
lma_providers = [];
for tr in lma_tbody.find_all("tr", recursive=False):
    cells = tr.find_all(["td", "th"], recursive=False);
    if not cells:
        continue;
    provider_text = "";
    for cell in cells:
        for span in cell.select("span.text-text-secondary"):
            txt = " ".join(span.stripped_strings).strip();
            if txt and any(c.isalpha() for c in txt):
                provider_text = txt;
                break;
        if provider_text:
            break;
    lma_providers.append(provider_text);
if len(lma_providers) == len(lma_df):
    lma_df["Provider"] = lma_providers;
else:
    print_step(f"⚠ Provider extraction row count mismatch ({len(lma_providers)} vs {len(lma_df)}); skipping Provider column");
print_step(f"Extracted {len(lma_df)} rows, {len(lma_df.columns)} columns")
lma_file = data_dir / "lmarena_text_leaderboard.csv";
lma_df.to_csv(lma_file, index=False);
print_step(f"✓ Saved: {lma_file}", "SUCCESS")

print_step("[2/3] Scraping Artificial Analysis Models Leaderboard")
print_step("Loading page and waiting for table to render...")
page_source = render_page("https://artificialanalysis.ai/leaderboards/models?deprecation=all", "table.w-full.caption-bottom.text-sm");
print_step("Parsing rendered HTML...");
soup = BeautifulSoup(page_source, "html.parser");
table = soup.select_one("table.w-full.caption-bottom.text-sm");
if not table:
    raise RuntimeError("ArtificialAnalysis table not found")
aa_df = extract_table_data(table, skip_first_empty=True);
print_step(f"Extracted {len(aa_df)} rows, {len(aa_df.columns)} columns")
aa_file = data_dir / "aa_models_leaderboard.csv";
aa_df.to_csv(aa_file, index=False);
print_step(f"✓ Saved: {aa_file}", "SUCCESS")

print_step("[3/3] Scraping LiveBench Leaderboard")
print_step("Loading page and waiting for table to render...")
def _lb_post_load(driver):
    time.sleep(3);
    table_el = driver.find_element(By.CSS_SELECTOR, "table.main-tabl.table");
    driver.execute_script("arguments[0].parentElement.scrollLeft=arguments[0].parentElement.scrollWidth", table_el);
page_source = render_page("https://livebench.ai/#/", "table.main-tabl.table tbody tr", post_load=_lb_post_load);

print_step("Parsing complex table...")
soup = BeautifulSoup(page_source, "html.parser");
table = soup.select_one("table.main-tabl.table");

if not table:
    raise RuntimeError("LiveBench table not found in page")

soup = BeautifulSoup(str(table), "html.parser");
thead = soup.find("thead");
header_rows = thead.find_all("tr") if thead else [];

grid, spans = [], {};
for tr in header_rows:
    row = [];
    for cell in tr.find_all(["th", "td"]):
        row.append({"text": cell.get_text(strip=True), "colspan": int(cell.get("colspan", 1)), "rowspan": int(cell.get("rowspan", 1))});
    grid.append(row);

header_matrix = [];
for r_idx in range(len(grid)):
    row_out, col_idx = [], 0;
    for cell in grid[r_idx]:
        while (r_idx, col_idx) in spans:
            row_out.append(spans[(r_idx, col_idx)]);
            col_idx += 1;
        for _ in range(cell["colspan"]):
            row_out.append(cell["text"]);
        if cell["rowspan"] > 1:
            for r in range(1, cell["rowspan"]):
                for i in range(cell["colspan"]):
                    spans[(r_idx + r, col_idx + i)] = cell["text"];
        col_idx += cell["colspan"];
    header_matrix.append(row_out);

max_cols = max(len(r) for r in header_matrix) if header_matrix else 0;
headers = [" | ".join(filter(None, [header_matrix[r][c] if c < len(header_matrix[r]) else "" for r in range(len(header_matrix))])) or f"col_{c+1}" for c in range(max_cols)];

tbody = soup.find("tbody");
if not tbody:
    print_step("⚠ Warning: No tbody found in LiveBench table");
    tbody_rows = [];
else:
    tbody_rows = tbody.find_all("tr", recursive=False);
    print_step(f"Found {len(tbody_rows)} rows in tbody");

data = [];
for tr in tbody_rows:
    cells = tr.find_all(["td", "th"]);
    if cells:
        row = [td.get_text(strip=True) for td in cells];
        data.append(row);

print_step(f"Extracted {len(data)} data rows before processing")

for row in data:
    if len(row) < len(headers):
        row += [""] * (len(headers) - len(row));
    elif len(row) > len(headers):
        data[data.index(row)] = row[:len(headers)];

lb_df = pd.DataFrame(data, columns=headers if headers else None);
print_step(f"Extracted {len(lb_df)} rows, {len(lb_df.columns)} columns")

lb_file = data_dir / "livebench_leaderboard.csv";
lb_df.to_csv(lb_file, index=False);
print_step(f"✓ Saved: {lb_file}", "SUCCESS")

print("\n" + "=" * 80)
print_step("ALL SCRAPING COMPLETED!", "SUCCESS")
print("=" * 80)

# ============================================================================
# STEP 2: BUILD PROCESSED.CSV
# ============================================================================
print("\n" + "=" * 80)
print_step("BUILDING PROCESSED.CSV", "START")
print("=" * 80)

print_step("Reading tracking.json (configuration)...")
fixed_df = pd.read_json(BASE_DIR / "config/tracking.json");
fixed_df = fixed_df.replace({"": None, float("nan"): None});
print_step(f"Loaded {len(fixed_df)} models configuration")

result = fixed_df[['model', 'name', 'logo', 'geo']].copy();
result['lma'] = None;
result['aa'] = None;
result['lb'] = None;

SOURCES = [
    {"key": "lma", "df": lma_df, "lookup_col": "lma_lookup", "model_kw": ["model"], "score_kw": ["arena", "elo", "score", "rating"], "type": "int"},
    {"key": "aa",  "df": aa_df,  "lookup_col": "aa_lookup",  "model_kw": ["model", "name"], "score_kw": ["quality", "score", "index"], "type": "int"},
    {"key": "lb",  "df": lb_df,  "lookup_col": "lb_lookup",  "model_kw": ["model"], "score_kw": ["average", "overall", "total", "score"], "type": "float"},
];

print_step("Matching models and extracting scores...")
matches_found = {s["key"]: 0 for s in SOURCES};

for idx, row in fixed_df.iterrows():
    for src in SOURCES:
        score = match_source_score(src["df"], row[src["lookup_col"]], src["model_kw"], src["score_kw"], src["type"]);
        if score is not None:
            result.at[idx, src["key"]] = score;
            matches_found[src["key"]] += 1;

print_step(f"Matches found - LMArena: {matches_found['lma']}, AA: {matches_found['aa']}, LiveBench: {matches_found['lb']}")

print_step("Saving...")
result.to_csv(BASE_DIR / "data/processed.csv", sep=";", index=False);
print_step(f"✓ Saved data with {len(result)} models", "SUCCESS")

# ============================================================================
# STEP 2b: BUILD SOURCES.JSON (full per-source top-N for source tabs)
# ============================================================================
print("\n" + "=" * 80)
print_step("BUILDING SOURCES.JSON", "START")
print("=" * 80)

sources_file = BASE_DIR / "data/sources.json";
sources_data = build_sources_json(
    lma_df, aa_df, lb_df, fixed_df,
    BASE_DIR / "config/models.json",
    sources_file,
);
for k, label in (("lma", "LMArena"), ("aa", "Artificial Analysis"), ("lb", "LiveBench")):
    rows = sources_data.get(k, []);
    tracked_n = sum(1 for r in rows if r.get("tracked"));
    no_logo_n = sum(1 for r in rows if not r.get("logo"));
    print_step(f"{label}: {len(rows)} rows ({tracked_n} tracked, {no_logo_n} unresolved logo)");
print_step(f"✓ Saved: {sources_file}", "SUCCESS")

# ============================================================================
# STEP 3: UPDATE HISTORY
# ============================================================================
print("\n" + "=" * 80)
print_step("UPDATING HISTORY", "START")
print("=" * 80)

history_file = BASE_DIR / "data/history.csv";
changes_count = append_history(result, history_file);
print_step(f"✓ History update complete ({changes_count} changes)", "SUCCESS")

# ============================================================================
# STEP 4: GENERATE ALERTS
# ============================================================================
print("\n" + "=" * 80)
print_step("GENERATING ALERTS", "START")
print("=" * 80)

today_str = datetime.now().strftime("%Y-%m-%d");
today_date = datetime.strptime(today_str, "%Y-%m-%d");

alerts_output = [];
alerts_output.append("LEADERBOARD ALERTS REPORT");
alerts_output.append("=" * 70);

source_labels = {"lma": "LMArena", "aa": "Artificial Analysis", "lb": "LiveBench"};

# --- Section 1: TRACKING ISSUES (lookups that returned no score) ---
print_step("Checking for tracking issues...")
tracking_issues = [];

for idx, row in fixed_df.iterrows():
    for src in SOURCES:
        key = src["key"];
        lookup_value = row[src["lookup_col"]];
        if pd.isna(lookup_value) or not str(lookup_value).strip():
            continue;
        current_score = result.at[idx, key];
        if pd.isna(current_score) or current_score is None:
            tracking_issues.append({
                "model": row["name"],
                "model_id": row["model"],
                "source": source_labels[key],
                "lookup": str(lookup_value).strip(),
            });

def _sig(t):
    return f"{t['model_id']}|{t['source']}|{t['lookup']}"

today_tracking_sigs = [_sig(t) for t in tracking_issues]
previous_tracking_sigs = set()

import os as _os_a
if _os_a.environ.get("FIREBASE_DATABASE_URL"):
    try:
        import sys as _sys_a
        _sys_a.path.insert(0, str(BASE_DIR))
        from scripts.firebase_upload import _init_firebase as _init_fb
        from firebase_admin import db as _db
        _init_fb(_os_a.environ["FIREBASE_DATABASE_URL"])
        prev = _db.reference("previous_alerts/tracking_issues").get()
        if isinstance(prev, list):
            previous_tracking_sigs = {str(s) for s in prev}
        elif isinstance(prev, dict):
            previous_tracking_sigs = {str(s) for s in prev.values()}
        _db.reference("previous_alerts/tracking_issues").set(today_tracking_sigs)
    except Exception as _e:
        print_step(f"⚠ previous_alerts roundtrip skipped: {_e}", "WARN")

new_tracking_sigs = {sig for sig in today_tracking_sigs if sig not in previous_tracking_sigs}

if new_tracking_sigs:
    alerts_output.append("");
    alerts_output.append("─" * 70);
    alerts_output.append("TRACKING ISSUES — models with lookups that returned no match");
    alerts_output.append("─" * 70);
    alerts_output.append("");
    for t in tracking_issues:
        marker = " [NEW]" if _sig(t) in new_tracking_sigs else "";
        alerts_output.append(f"  • {t['model']}{marker} — {t['source']} lookup \"{t['lookup']}\" returned nothing");

# --- Section 3: NEW UNTRACKED MODELS ---
print_step("Collecting untracked models across sources...")
untracked_list = [];
untracked_list.extend(get_untracked_models(lma_df, "LMArena", ['arena', 'elo', 'score', 'rating'], fixed_df, 'lma_lookup', top_n=30));
untracked_list.extend(get_untracked_models(aa_df, "Artificial Analysis", ['quality', 'score', 'index'], fixed_df, 'aa_lookup', top_n=30));
untracked_list.extend(get_untracked_models(lb_df, "LiveBench", ['average', 'overall', 'total', 'score'], fixed_df, 'lb_lookup', top_n=30));

print_step("Grouping untracked models using fuzzy matching...")
grouped_models = [];
for model in untracked_list:
    found_group = False;
    for group in grouped_models:
        if fuzz.token_sort_ratio(model["norm_name"], group["norm_name"]) > 85:
            group["instances"].append(model);
            found_group = True;
            break;
    if not found_group:
        grouped_models.append({
            "norm_name": model["norm_name"],
            "instances": [model]
        });

print_step("Filtering out weaker versions of tracked models...");
filtered_groups = [];
for group in grouped_models:
    untracked_norm = group["norm_name"];
    is_weaker_version = False;
    for _, row in fixed_df.iterrows():
        tracked_name = str(row['name']).lower();
        if "thinking" in tracked_name or "reasoning" in tracked_name:
            tracked_base = tracked_name.replace("(thinking)", "").replace("thinking", "").replace("(reasoning)", "").replace("reasoning", "").strip();
            tracked_base_norm = normalize_model_name(tracked_base);
            if fuzz.token_sort_ratio(untracked_norm, tracked_base_norm) > 85:
                is_weaker_version = True;
                break;
    if not is_weaker_version:
        filtered_groups.append(group);

grouped_models = filtered_groups;

untracked_file = BASE_DIR / "data/untracked_models.json";
history_untracked = _load_untracked_from_firebase();
if history_untracked is None:
    if untracked_file.exists():
        with open(untracked_file, "r") as f:
            history_untracked = json.load(f);
    else:
        history_untracked = {};

alerts_output.append("");
alerts_output.append("─" * 70);
alerts_output.append("UNTRACKED MODELS — top 30 models not in tracking.json");
alerts_output.append("─" * 70);

new_models_count = 0;

if grouped_models:
    alerts_output.append("");
    for group in grouped_models:
        norm_name = group["norm_name"];
        if norm_name not in history_untracked:
            history_untracked[norm_name] = today_str;
            new_models_count += 1;

        display_name = group["instances"][0]["raw_name"];
        sources_info = ", ".join([f"{inst['source']}: '{inst['raw_name']}'" for inst in group["instances"]]);

        alerts_output.append(f"  • {display_name}");
        alerts_output.append(f"    First seen: {history_untracked[norm_name]}");
        alerts_output.append(f"    Sources: {sources_info}");
        alerts_output.append("");
else:
    alerts_output.append("");
    alerts_output.append("  No untracked models found in the top 30 of any leaderboard.");

current_norms = {g["norm_name"] for g in grouped_models};
stale_keys = [k for k in history_untracked if k not in current_norms];
for k in stale_keys:
    del history_untracked[k];

alert_file = BASE_DIR / "alerts.txt";
with open(alert_file, "w") as f:
    f.write("\n".join(alerts_output));

with open(untracked_file, "w") as f:
    json.dump(history_untracked, f, indent=4);

print_step(f"✓ Alerts saved to: {alert_file.absolute()}", "SUCCESS")

print("\n" + "─" * 70)
print("ALERTS (mirrored to log for daily visibility)")
print("─" * 70)
print("\n".join(alerts_output))
print("─" * 70 + "\n")

def _esc(s):
    return (str(s)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))

NEW_BG = "#fff3cd"
NEW_BORDER_L = "4px solid #f59e0b"
NEW_BADGE = ('<span style="display:inline-block;background:#f59e0b;color:#fff;'
             'font-size:10px;font-weight:600;padding:1px 6px;border-radius:4px;'
             'margin-left:6px;vertical-align:middle;">NEW</span>')

html = []
html.append('<!DOCTYPE html><html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;color:#111;max-width:760px;margin:0 auto;padding:8px;">')
html.append(f'<h2 style="margin:0 0 4px 0;">Leaderboard alerts</h2>')
html.append(f'<div style="color:#666;font-size:13px;margin-bottom:18px;">{today_str}</div>')

if new_tracking_sigs:
    html.append('<h3 style="margin:18px 0 6px 0;font-size:15px;color:#444;border-bottom:1px solid #ddd;padding-bottom:4px;">Tracking issues — lookups returning no match</h3>')
    html.append('<table style="width:100%;border-collapse:collapse;font-size:13px;">')
    html.append('<thead><tr>'
                '<th style="text-align:left;padding:6px 8px;background:#f5f5f5;border-bottom:1px solid #ddd;">Model</th>'
                '<th style="text-align:left;padding:6px 8px;background:#f5f5f5;border-bottom:1px solid #ddd;">Source</th>'
                '<th style="text-align:left;padding:6px 8px;background:#f5f5f5;border-bottom:1px solid #ddd;">Lookup</th>'
                '</tr></thead><tbody>')
    for t in tracking_issues:
        is_new = _sig(t) in new_tracking_sigs
        row_style = f'background:{NEW_BG};border-left:{NEW_BORDER_L};' if is_new else ''
        badge = NEW_BADGE if is_new else ''
        html.append(
            f'<tr style="{row_style}">'
            f'<td style="padding:6px 8px;border-bottom:1px solid #eee;">{_esc(t["model"])}{badge}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #eee;color:#555;">{_esc(t["source"])}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #eee;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#333;">{_esc(t["lookup"])}</td>'
            f'</tr>'
        )
    html.append('</tbody></table>')

# Section 2: Untracked models (top 30 by appearance order)
top_untracked = grouped_models[:30]
html.append('<h3 style="margin:24px 0 6px 0;font-size:15px;color:#444;border-bottom:1px solid #ddd;padding-bottom:4px;">Untracked models — top 30 not in tracking.json</h3>')
if top_untracked:
    html.append('<table style="width:100%;border-collapse:collapse;font-size:13px;">')
    html.append('<thead><tr>'
                '<th style="text-align:left;padding:6px 8px;background:#f5f5f5;border-bottom:1px solid #ddd;">Model</th>'
                '<th style="text-align:left;padding:6px 8px;background:#f5f5f5;border-bottom:1px solid #ddd;">First seen</th>'
                '<th style="text-align:left;padding:6px 8px;background:#f5f5f5;border-bottom:1px solid #ddd;">Sources</th>'
                '</tr></thead><tbody>')
    for group in top_untracked:
        norm = group["norm_name"]
        first_seen = history_untracked.get(norm, today_str)
        is_new = first_seen == today_str
        row_style = f'background:{NEW_BG};border-left:{NEW_BORDER_L};' if is_new else ''
        badge = NEW_BADGE if is_new else ''
        display = group["instances"][0]["raw_name"]
        srcs = ", ".join(f"{i['source']}: {i['raw_name']}" for i in group["instances"])
        html.append(
            f'<tr style="{row_style}">'
            f'<td style="padding:6px 8px;border-bottom:1px solid #eee;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{_esc(display)}{badge}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #eee;color:#555;">{_esc(first_seen)}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #eee;color:#666;font-size:12px;">{_esc(srcs)}</td>'
            f'</tr>'
        )
    html.append('</tbody></table>')
else:
    html.append('<p style="color:#666;font-style:italic;">No untracked models in the top 30 of any leaderboard.</p>')

html.append('</body></html>')

alerts_html_file = BASE_DIR / "alerts.html"
with open(alerts_html_file, "w") as f:
    f.write("\n".join(html))
print_step(f"✓ HTML alerts saved to: {alerts_html_file.absolute()}", "SUCCESS")

# ============================================================================
# STEP 5: SAVE METADATA
# ============================================================================
print("\n" + "=" * 80)
print_step("SAVING METADATA", "START")
print("=" * 80)

metadata = {
    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "stats": {
        "models_tracked": len(fixed_df),
        "matches_found": matches_found,
        "rows_scraped": {
            "lmarena": len(lma_df) if lma_df is not None else 0,
            "artificial_analysis": len(aa_df) if aa_df is not None else 0,
            "livebench": len(lb_df) if lb_df is not None else 0
        }
    },
    "alerts_summary": {
        "tracking_issues": len(tracking_issues),
        "new_tracking_issues": len(new_tracking_sigs),
        "new_untracked_models": new_models_count,
        "send_email": bool(new_models_count or new_tracking_sigs)
    },
    "history_changes": changes_count
};

metadata_file = BASE_DIR / "metadata.json";
with open(metadata_file, "w") as f:
    json.dump(metadata, f, indent=4);

print_step(f"✓ Metadata saved to: {metadata_file.absolute()}", "SUCCESS")

# ============================================================================
# STEP 6: OPTIONAL FIREBASE UPLOAD (no-op unless FIREBASE_DATABASE_URL is set)
# ============================================================================
import os as _os
if _os.environ.get("FIREBASE_DATABASE_URL"):
    print("\n" + "=" * 80)
    print_step("PUSHING ARTIFACTS TO FIREBASE REALTIME DATABASE", "START")
    print("=" * 80)
    try:
        import sys as _sys
        _sys.path.insert(0, str(BASE_DIR))
        from scripts.firebase_upload import upload_artifacts
        summary = upload_artifacts(BASE_DIR);
        if summary:
            for path, size in summary.items():
                print_step(f"✓ /{path}  ({size})");
        else:
            print_step("Nothing uploaded (FIREBASE_DATABASE_URL unset)");
    except Exception as exc:
        print_step(f"⚠ Firebase upload failed: {exc}", "ERROR");

print("\n" + "=" * 80)
print_step("UPDATE COMPLETED SUCCESSFULLY!", "SUCCESS")
print("=" * 80)
