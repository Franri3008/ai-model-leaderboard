import requests
from bs4 import BeautifulSoup

from scraper_common import USER_AGENTS, extract_table_data, print_step

def scrape():
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
    tbody = table.find("tbody") or table;
    providers = [];
    for tr in tbody.find_all("tr", recursive=False):
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
        providers.append(provider_text);
    if len(providers) == len(lma_df):
        lma_df["Provider"] = providers;
    else:
        print_step(f"Provider extraction row count mismatch ({len(providers)} vs {len(lma_df)}); skipping Provider column");
    return lma_df
