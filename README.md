# AI Model Leaderboard Data Pipeline

Automated scraper and aggregator for three AI model leaderboards (LMArena, Artificial Analysis, LiveBench). Scores are matched using a crosswalk mapping and published as static data consumed by the [visualization](https://franri3008.github.io/pages/CEPS/AI-World/ModelLeaderboard/viz.html).

## How it works

1. **Scrape** three leaderboards daily via GitHub Actions
2. **Match** models using lookup keys in `config/tracking.json`
3. **Output** `data/processed.csv` (current scores) and `data/history.csv` (append-only changelog)

## File structure

```
update.py               Main script, runs the scrapers, matches, builds data
scraper_lma.py          LMArena scraper (requests/bs4)
scraper_aa.py           Artificial Analysis scraper (selenium-rendered table)
scraper_lb.py           LiveBench scraper (static CSV/JSON data files)
scraper_common.py       Shared scraper helpers (logging, selenium, table parsing)
config/
  ├── tracking.json     Model metadata & lookup keys
  └── models.json       Organization colors & logos
data/
  ├── processed.csv     Current aggregated scores (consumed by viz)
  ├── history.csv       Append-only score history (only changed rows)
  └── scraped/          Raw scraped CSVs (gitignored)
metadata.json           Run stats (timestamp, match counts)
```

## Quick Start

```bash
pip install -r requirements.txt
python update.py
```

## Adding a Model

1. Add an entry to `config/tracking.json`:
   ```json
   {
       "model": "new-model-id",
       "name": "Display Name",
       "logo": "org-logo-id",
       "geo": "US",
       "os": 0,
       "lma_lookup": "LMArena name",
       "aa_lookup": "AA name",
       "lb_lookup": "LiveBench name"
   }
   ```
2. If new organization, add to `config/models.json`
3. Run `python update.py`

## Score types

| Key | Source | Type | Range |
|-----|--------|------|-------|
| `lma` | LMArena Elo | integer | ~1200–1500 |
| `aa` | Artificial Analysis Quality Index | integer | 0–100 |
| `lb` | LiveBench Average | float | 0–100 |

## History format

`data/history.csv` is append-only, a new row is added only when a model's score changes:

```
date;model;lma;aa;lb
2026-02-06;gpt-5.4;1480;56;79.50
2026-03-19;gpt-5.4;1486;57;80.28
```

To reconstruct scores for any past date, take the latest entry per model on or before that date.
