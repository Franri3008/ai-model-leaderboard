from bs4 import BeautifulSoup

from scraper_common import extract_table_data, print_step, render_page

def scrape():
    print_step("Loading page and waiting for table to render...")
    page_source = render_page("https://artificialanalysis.ai/leaderboards/models?deprecation=all", "table.w-full.caption-bottom.text-sm");
    print_step("Parsing rendered HTML...");
    soup = BeautifulSoup(page_source, "html.parser");
    table = soup.select_one("table.w-full.caption-bottom.text-sm");
    if not table:
        raise RuntimeError("ArtificialAnalysis table not found")
    return extract_table_data(table, skip_first_empty=True)
