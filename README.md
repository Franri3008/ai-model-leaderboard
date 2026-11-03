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
  ├── models.json       Organization colors & logos
  └── lab-geography.json  Lab to city and country, for geography.html
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

## Methodology: capability score

The "Overall" tab shows one capability score per model. The frontend computes it in [`scripts/aggregation.js`](scripts/aggregation.js). The Python pipeline only stores raw values and never normalises them. The per-source tabs show raw scores.

### Sources

- **LMArena** (`lma`). An Elo rating from human votes, roughly 1200 to 1550.
- **Artificial Analysis** (`aa`). The Intelligence Index, 0 to 100.
- **LiveBench** (`lb`). The average over LiveBench's tests, 0 to 100.

### Reference model and target

The reference model is GPT 6.1 Sol (`gpt-6-1-sol`). Its score is fixed at 0.70. Both values live in one constant, `ALL_REFERENCE` in `scripts/aggregation.js`.

Each source gives a part. The part is `0.70 × value / reference value`. The reference value is GPT 6.1 Sol's score on that source's current scale. The capability score is the mean of the three parts. So GPT 6.1 Sol scores 0.70, and a model 10% above it on every source scores 0.77.

Why GPT 6.1 Sol. It has a live score on all three current scales, so no part of the reference is guessed. That gives the three sources equal weight. Why 0.70. On 24 October 2026, the last scored day before the scale switches, the old method gave GPT 6.1 Sol 0.742, and the top models sat between 0.70 and 0.80. A 0.70 target keeps the homepage at about that level.

### Dates before GPT 6.1 Sol

GPT 6.1 Sol first appears in the data on 30 September 2026. Snapshots of earlier dates use the old method. Its constant is `ALL_LEGACY_REFERENCE` in `scripts/aggregation.js`.

- The reference model is GPT-5 (`gpt-5-high`). Its score is 0.50.
- Each reference value is GPT-5's score in that day's data. If GPT-5 has no score there, the value is the one the old code used. That is 1434 for LMArena, 45 for AA and 70.48 for LiveBench.
- GPT-5 is not pinned. If it misses a source, it gets an estimate like any other model.

These dates were before AA v5 and LiveBench 2.0, so the old scales apply. The switch is one check in the code. If GPT 6.1 Sol is in the data, it is the reference. If not, GPT-5 is. If neither is there, the Overall tab shows an error and no ranking.

The bump chart's Overall tab uses the same code for both of its dates. A comparison that starts before 30 September 2026 mixes the two methods. On 30 September 2026 the old method scored the top five models about 0.05 higher on average.

### Current scales

Each source is compared only on its current scale.

- **LiveBench 2.0.** Since 26 October 2026 only LiveBench 2.0 scores count. A model with only a LiveBench 1.0 score counts as missing on LiveBench.
- **AA v5.** Since 29 October 2026 the current scale is Intelligence Index v5. AA did not rescore every model. A model with only a v4 score is moved onto the v5 scale with one ratio. The ratio is the median of v5 score over v4 score for every model that has both. Each model's v4 score is its last one before the switch day. Its v5 score is its latest one. Untagged history rows from the switch day onward are left out. On 3 November 2026 the ratio was 0.761.

### Missing sources

A model needs scores on at least 2 sources to appear. Live and last known scores both count. When a model misses a source, it gets an estimate. The model's percentile on its other sources is averaged. That percentile is read back as a value from the missing source's own list of scores. The estimate then counts like a real score. Tooltips show it as `~X (est.)`.

The reference gets the same treatment. If GPT 6.1 Sol has no score on a source's current scale, its reference value there is its percentile estimate. Its percentile comes from the sources where it does have a current score. Its own part on that source is then exactly 0.70.

If a model drops off a source but has history, its last known score is used. Tooltips grey it out and mark it with `!`.

### Changelog

- **2026-10-26.** LiveBench moved to 2.0. LiveBench 1.0 scores stopped counting for missing 2.0 scores.
- **2026-10-29.** Artificial Analysis moved to Intelligence Index v5. Each AA score was compared with GPT-5's score on its own index version.
- **2026-11-03.** The reference moved from GPT-5 at 0.50 to GPT 6.1 Sol at 0.70. GPT-5 had scored 0.40 instead of 0.50. It had no v5 AA score and no LiveBench 2.0 score. Its AA score was divided by a fixed 45 from an older AA scale. Its LiveBench reference was a fixed 70.48 from LiveBench 1.0. The v5 to v4 ratio also came out as exactly 1. History rows from 29 October held v5 values without a version tag, so they were read as v4. The ratio now skips those rows. With GPT-5 as the reference, the AA part was about three times the size of the others, because GPT-5's AA reference had to be estimated. GPT 6.1 Sol has a live score on all three sources, so the parts weigh the same.
- **2026-11-03.** Snapshots before 30 September 2026 keep the old method, with GPT-5 at 0.50. Their rankings match what the page showed with the code of 24 October 2026.
- **2026-11-03.** The bump chart's Overall tab now uses the same scoring as the homepage, for both dates it compares. Before, it had its own copy with GPT-5 at 0.50 and a different rule for missing sources. A "Ref" marker now shows when the compared dates cross the reference switch. Its date is the first day GPT 6.1 Sol appears in the history, 30 September 2026 if that cannot be found.

## Geography page

`geography.html` shows where frontier models come from. It links each urban area to its labs, each lab to its best model, and each model to its capability score. It uses the Overall score, the same one as the homepage. It keeps each lab's best scored model that is not deactivated. It shows the top 15 labs. `?snapshot=YYYY-MM-DD` shows a past date, as on the homepage.

A lab is the model's `logo`, the `id` in `config/models.json`. `config/lab-geography.json` places each lab. Under `labs`, each id has a display `label`, a `city` key and a `country`. Under `cities`, each key has a `name`, a `country` and a `color`. Cities appear in the order they are listed there. Cities of one country sit close together.

A lab that is not in `labs` is never dropped. It shows under an "Unmapped" city in grey, and the page logs a console warning that names it. Add the lab to `config/lab-geography.json` to place it. A new organization in `config/models.json` needs an entry there too. `tests/test_geography.js` checks this.

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
