import random
import time
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

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
