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
scraper_aa.py           Artificial Analysis scraper (official API, paged JSON)
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

## Artificial Analysis collection

AA comes from the official Data API with the `AA_API_KEY` secret sent in the `x-api-key` header. The scraper calls `GET /api/v2/language/models` (Pro tier). If AA answers `403`, the key is Free tier, and the scraper switches to `GET /api/v2/language/models/free`. Both return `tier`, `intelligence_index_version`, `pagination` and `data`. The scraper requests `?page=1`, `?page=2` and so on until `pagination.has_more` is false, and stops with an error after 25 pages. AA sets the page size itself.

The old `/api/v2/data/llms/models` endpoint retires on 2026-11-04 and returns `410 Gone` after that. See https://artificialanalysis.ai/data-api/migrate-v2-data.

Each model gives `slug`, `name`, `model_creator.name` (may be null) and `evaluations`. Scores are rounded to AA's displayed integer. Models with no score are skipped. A schema change, an HTTP error, a duplicate slug or pages that disagree stop the update before anything is written.

AA moved to Intelligence Index v5 in October 2026 and did not rescore older models. On 2026-10-29 the free list had 716 models and only 78 had a v5 score. The scraper picks the index at run time.

- **Rule v4.** If `evaluations` holds a key with `intelligence` and `v4` in its name, such as `artificial_analysis_intelligence_index_v4`, and at least 200 models have it, that key is used. `aa_version` is read from the key name, for example `v4` or `v4.3`.
- **Rule current.** Otherwise `evaluations.artificial_analysis_intelligence_index` is used. `aa_version` is the response's `intelligence_index_version`, for example `v5.0`.

The AA docs list no v4 field and no version parameter, so the current rule is the expected one. Rule v4 is there in case AA adds a field for the old index.

The update stops if too few models have a score. Rule v4 needs at least 200, and at least half of the previous run's count. Rule current needs at least 50. It applies the half-of-previous check only when the previous run used the same index version. The previous count and version come from Firebase `metadata/stats`, as `rows_scraped/artificial_analysis` and `aa_index_version`. `update.py` writes both into `metadata.json`, which is already uploaded each run. Runs from before this change have no `aa_index_version`, so the first v5 run skips the half-of-previous check.

The run log shows what happened, in these lines.

- `AA: evaluations keys with non-null counts over N models: ...` lists every key under `evaluations` and how many models have a value. It shows no scores.
- `AA: top-level model fields that look like an index version: ...` lists model fields with `version` or `index` in the name.
- `AA: rule <v4|current> uses <key> as <version> because <reason>` names the rule.
- `AA: tier ... via ..., N pages ..., M models, K scored, index vX.Y` records what was fetched.
- `AA: size guard floor F (...)` shows the floor and why.

`aa_estimated` (0/1, empty because the API does not publish it), `aa_version` (the response's `intelligence_index_version`, for example `v5.0`), and `aa_slug` accompany AA scores in processed data, history, and source exports. Provider estimate status is retained in the data; tooltips display the published score without an AA estimate label. AA-published estimates count as an available source in the existing aggregation. Exact variant names remain configured through `aa_lookup`.

## Aggregate score ("ALL" view)

Per-source tabs show raw scores. The combined **"ALL"** ranking is computed in the frontend ([`scripts/aggregation.js`](scripts/aggregation.js)): the Python pipeline never normalizes, it only stores raw values.

1. **Normalize each source against a fixed baseline.** Each raw score is divided by `2 × GPT-5's score on that source` (`lma≈1434`, `aa≈45`, `lb≈70.48`, with those constants as fallback if GPT-5 drops out). This puts every axis on a scale where **GPT-5 = 0.5**, and keeps scores stable over time (they're anchored to a fixed reference, not to the current field).
2. **Combine.** The aggregate is the mean of the three normalized axes.
3. **Estimate a missing source** instead of dropping the model or giving it a free pass. When a model isn't on a leaderboard yet (e.g. a new model missing from LMArena), it's placed on that source at the **percentile it holds on the sources it does have**, and that percentile is mapped back to a real value from the source's own distribution. The estimate is then normalized like any real score, so a missing axis no longer inflates the model's rank. Estimated cells are shown in tooltips as `~X (est.)`. A model needs **at least 2 published sources** (live or historical, including AA-published estimates) to appear, at most one axis is ever estimated, so a whole profile is never fabricated from a single score.
4. **Stale scores persist.** If a model stops being tracked on a source but has history, its last known value is used (greyed with a `!` in tooltips) rather than treated as missing, so models don't vanish from the aggregate once a leaderboard drops them.
5. **AA index versions.** Since AA's Intelligence Index v5, each AA value is normalised against GPT-5's score on its own index version. The v5 reference is GPT-5's v5 score when AA publishes one. Otherwise it is the v4 reference times the median v5/v4 ratio of rescored models. `AA_V5_GPT5_REFERENCE` in `scripts/aggregation.js` overrides the ratio. The AA tab ranks only v5 scores once v5 exists.

## History format

`data/history.csv` is append-only, a new row is added when a model's score or AA metadata changes:

```
date;model;lma;aa;lb
2026-02-06;gpt-5.4;1480;56;79.50
2026-03-19;gpt-5.4;1486;57;80.28
```

New rows also carry `aa_estimated`, `aa_version`, and `aa_slug`; older rows may have those fields empty. Metadata changes are recorded even when the rounded score stays the same.

A tracked model that has no AA score this run does not change its AA history. Losing the score never adds a row by itself. If LMArena or LiveBench changes and a row is added, the row keeps the last known `aa` with its `aa_estimated`, `aa_version` and `aa_slug`. `processed.csv` leaves `aa` empty for that model, and the viz shows the last known value as stale.

To reconstruct scores for any past date, take the latest entry per model on or before that date.

## Email alerts

Alert emails are delta-only:

- A tracking issue is included only when a configured lookup has newly stopped matching.
- An untracked model is included only the first time it enters a source's top 50.
- Previously seen models are remembered permanently, even after leaving the top 50.
- No email is sent when there is no new alert or when the Firebase alert state cannot be read or saved.

## Validation

```bash
python -m unittest discover -s tests -v
node --test tests/test_aa_frontend.js
```
