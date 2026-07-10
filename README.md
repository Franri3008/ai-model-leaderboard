# AI Model Leaderboard Data Pipeline

Automated scraper and aggregator for three AI model leaderboards (LMArena, Artificial Analysis, LiveBench). Scores are matched using a crosswalk mapping and published as static data consumed by the [visualization](https://aileaderboard.franri.dev/index.html).

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

## Aggregate score ("ALL" view)

Per-source tabs show raw scores. The combined **"ALL"** ranking is computed in the frontend ([`scripts/aggregation.js`](scripts/aggregation.js)): the Python pipeline never normalizes, it only stores raw values.

1. **Normalize each source against a fixed baseline.** Each raw score is divided by `2 × GPT-5's score on that source` (`lma≈1434`, `aa≈45`, `lb≈70.48`, with those constants as fallback if GPT-5 drops out). This puts every axis on a scale where **GPT-5 = 0.5**, and keeps scores stable over time (they're anchored to a fixed reference, not to the current field).
2. **Combine.** The aggregate is the mean of the three normalized axes.
3. **Estimate a missing source** instead of dropping the model or giving it a free pass. When a model isn't on a leaderboard yet (e.g. a new model missing from LMArena), it's placed on that source at the **percentile it holds on the sources it does have**, and that percentile is mapped back to a real value from the source's own distribution. The estimate is then normalized like any real score, so a missing axis no longer inflates the model's rank. Estimated cells are shown in tooltips as `~X (est.)`. A model needs **at least 2 real sources** (live or historical) to appear, at most one axis is ever estimated, so a whole profile is never fabricated from a single score.
4. **Stale scores persist.** If a model stops being tracked on a source but has history, its last known value is used (greyed with a `!` in tooltips) rather than treated as missing, so models don't vanish from the aggregate once a leaderboard drops them.

## History format

`data/history.csv` is append-only, a new row is added only when a model's score changes:

```
date;model;lma;aa;lb
2026-02-06;gpt-5.4;1480;56;79.50
2026-03-19;gpt-5.4;1486;57;80.28
```

To reconstruct scores for any past date, take the latest entry per model on or before that date.
