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

    match = scraped_df[scraped_df[model_col].str.contains(lookup_name, case=False, na=False, regex=False)];
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
            if str(lookup).strip().lower() in str(model_name).lower():
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

def append_history(result, history_file):
    today = datetime.now().strftime("%Y-%m-%d");

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
        history.to_csv(history_file, sep=";", index=False);
        print_step(f"Appended {len(new_rows)} changed rows to history.csv");
    else:
        print_step("No score changes detected, history.csv unchanged");

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
print_step(f"Extracted {len(lma_df)} rows, {len(lma_df.columns)} columns")
lma_file = data_dir / "lmarena_text_leaderboard.csv";
lma_df.to_csv(lma_file, index=False);
print_step(f"✓ Saved: {lma_file}", "SUCCESS")

print_step("[2/3] Scraping Artificial Analysis Models Leaderboard")
print_step("Launching headless Chrome browser...")
driver = get_chrome_driver();
print_step("Loading page and waiting for table to render...")
driver.get("https://artificialanalysis.ai/leaderboards/models?deprecation=all");
WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.w-full.caption-bottom.text-sm")));
print_step("Parsing rendered HTML...");
soup = BeautifulSoup(driver.page_source, "html.parser");
driver.quit();
table = soup.select_one("table.w-full.caption-bottom.text-sm");
if not table:
    raise RuntimeError("ArtificialAnalysis table not found")
aa_df = extract_table_data(table, skip_first_empty=True);
print_step(f"Extracted {len(aa_df)} rows, {len(aa_df.columns)} columns")
aa_file = data_dir / "aa_models_leaderboard.csv";
aa_df.to_csv(aa_file, index=False);
print_step(f"✓ Saved: {aa_file}", "SUCCESS")

print_step("[3/3] Scraping LiveBench Leaderboard")
print_step("Launching headless Chrome browser...")
driver = get_chrome_driver();

print_step("Loading page and waiting for table to render...")
driver.get("https://livebench.ai/#/");

print_step("Waiting for table data to load...")
WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.main-tabl.table tbody tr")));

time.sleep(3);

print_step("Scrolling table to ensure all content is loaded...")
table_el = driver.find_element(By.CSS_SELECTOR, "table.main-tabl.table");
driver.execute_script("arguments[0].parentElement.scrollLeft=arguments[0].parentElement.scrollWidth", table_el);

print_step("Parsing complex table...")
soup = BeautifulSoup(driver.page_source, "html.parser");
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

driver.quit();

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

# --- Section 1: TRACKING ISSUES (disappeared/renamed lookups) ---
print_step("Checking for tracking issues (disappeared/renamed models)...")
tracking_issues = [];

for idx, row in fixed_df.iterrows():
    for src in SOURCES:
        key = src["key"];
        lookup_value = row[src["lookup_col"]];
        if pd.isna(lookup_value) or not str(lookup_value).strip():
            continue;
        current_score = result.at[idx, key];
        if pd.isna(current_score) or current_score is None:
            had_score_before = False;
            if history_file.exists():
                hist = pd.read_csv(history_file, sep=";");
                model_hist = hist[hist["model"] == row["model"]];
                if not model_hist.empty:
                    past_scores = model_hist[key].dropna();
                    if len(past_scores) > 0:
                        had_score_before = True;
            tracking_issues.append({
                "model": row["name"],
                "model_id": row["model"],
                "source": source_labels[key],
                "lookup": str(lookup_value).strip(),
                "had_score_before": had_score_before
            });

alerts_output.append("");
alerts_output.append("─" * 70);
alerts_output.append("1. TRACKING ISSUES — models with lookups that returned no match");
alerts_output.append("─" * 70);

if tracking_issues:
    renamed = [t for t in tracking_issues if t["had_score_before"]];
    never_matched = [t for t in tracking_issues if not t["had_score_before"]];

    if renamed:
        alerts_output.append("");
        alerts_output.append("  ⚠ LIKELY RENAMED/REMOVED (had scores before, now missing):");
        for t in renamed:
            alerts_output.append(f"    • {t['model']} — {t['source']} lookup \"{t['lookup']}\" returned nothing");

    if never_matched:
        alerts_output.append("");
        alerts_output.append("  ○ NEVER MATCHED (lookup set but never found a score):");
        for t in never_matched:
            alerts_output.append(f"    • {t['model']} — {t['source']} lookup \"{t['lookup']}\" returned nothing");
else:
    alerts_output.append("");
    alerts_output.append("  All tracked lookups are matching. No issues detected.");

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
if untracked_file.exists():
    with open(untracked_file, "r") as f:
        history_untracked = json.load(f);
else:
    history_untracked = {};

alerts_output.append("");
alerts_output.append("─" * 70);
alerts_output.append("2. UNTRACKED MODELS — top 30 models not in tracking.json");
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

# --- Clean up stale entries from untracked history ---
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
        "new_untracked_models": new_models_count
    },
    "history_changes": changes_count
};

metadata_file = BASE_DIR / "metadata.json";
with open(metadata_file, "w") as f:
    json.dump(metadata, f, indent=4);

print_step(f"✓ Metadata saved to: {metadata_file.absolute()}", "SUCCESS")

print("\n" + "=" * 80)
print_step("UPDATE COMPLETED SUCCESSFULLY!", "SUCCESS")
print("=" * 80)
