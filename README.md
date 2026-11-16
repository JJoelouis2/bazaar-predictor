# Bazaar Analysis

SkyBlock bazaar price intelligence: event-aware analytics (mayor / minister terms, z-scores,
cross-item correlation) and short-horizon forecasts for a curated watchlist of items,
published as a static site on GitHub Pages.

- **Live site:** https://jjoelouis2.github.io/bazaar-predictor
- **Watchlist:** 129 items across 8 mayor-focused phases
- **Models:** XGBoost (primary) and SARIMAX (baseline) for 6h and 24h forward log-returns
- **Grid:** 2h snapshots, with historical backfill from Coflnet

## What it does

1. Collects live bazaar prices and election state from the Hypixel API every 2h.
2. Backfills per-item 2h history from Coflnet, respecting its rate limit.
3. Builds dense per-item feature frames with mayor, minister, event and game-update terms.
4. Trains XGBoost and SARIMAX models, predicts 6h/24h returns, and computes z-score alerts,
   correlations and static inauguration effects.
5. Rebuilds the static `frontend/data` bundle; GitHub Actions commits refreshed data and deploys
   the site to Pages.

## Watchlist

The watchlist contains **129 tracked items**: **126 phase-specific items** plus **3 cross-phase
control items** (Booster Cookie, Catalyst, Titanic Experience Bottle).

| phase | mayor | focus | items |
| --- | --- | --- | --- |
| 1 | Aatrox | Slayer economy | 17 |
| 2 | Marina | Fishing & sea creatures | 20 |
| 3 | Cole | Mining | 20 |
| 4 | Diana | Mythological creatures & pets | 11 |
| 5 | Finnegan | Farming | 21 |
| 6 | Foxy | Events (Spooky / Season of Jerry) | 14 |
| 7 | Paul | Dungeons | 20 |
| 8 | Diaz | Economy & NPC shops | 8 |

Counts exclude the control items. Five items are tagged to two phases, so the tagged totals are
larger than the 126 unique phase-specific items.

**Paul (20):** core materials (Dungeon Chest Key, Kismet Feather, Wither Catalyst, Architect's
First Draft, Recombobulator 3000, Fuming Potato Book, Precursor Gear), drops (Diamond and Laser
Giant Fragments, Golem Poppy, Spirit Wing, First/Third/Fifth Master Star, Wither and Undead
Essence), scrolls (Implosion, Wither Shield) and enchantments (Ultimate Legion I, Ultimate Soul
Eater I).

**Diaz (8):** currency (Stock of Stonks, Freshly Minted Coins, Blood-Stained Coins, Blood-Soaked
Coins), items (Avaricious Chalice, Golden Fragment, Golden Bounty) and materials (Enchanted
Dandelion).

## Data sources

| source | use | notes |
| --- | --- | --- |
| [Hypixel API](https://api.hypixel.net) `/skyblock/bazaar` | live snapshots every 2h | `quick_status.buyPrice` = instabuy, `sellPrice` = instasell |
| [Hypixel API](https://api.hypixel.net) `/v2/resources/skyblock/election` | live mayor/minister + running election | optional `HYPIXEL_API_KEY` secret raises limits |
| [Coflnet](https://sky.coflnet.com) `api/bazaar/{tag}/history` | historical backfill (≥ Jun 2020, 2h resolution at ≤7-day request spans) | free, please credit sky.coflnet.com |
| [Hypixel SkyBlock Wiki](https://hypixelskyblock.minecraft.wiki/w/Module:Mayor/Elections/Data) | exact election dates years 1, 88–178 | Lua module parsed in `seed_calendar.py` |
| [SkyblockElections API](https://skyblockelections-api.onrender.com/api/stored-elections) | elections years 402–519 (candidates + votes) | dates interpolated, see limitations |

## Repository layout

```
backend/
  config/watchlist.json        tracked items, phases, mayor tabs
  config/event_calendar.json   mayor/minister terms, minister_weight, game updates
  datastore/history/*.jsonl    per-item 2h price history (tracked)
  datastore/elections.jsonl    live mayor/minister transitions (tracked)
  src/common.py                paths, constants, IO, HTTP helpers
  src/seed_calendar.py         build event_calendar.json from wiki + elections API
  src/backfill.py              Coflnet historical backfill
  src/collect.py               live bazaar + election collection (cron entrypoint)
  src/features.py              dense 2h frames, rolling stats, event dummies, targets
  src/analytics.py             z-score alerts, momentum, correlations, focus analysis
  src/train.py                 XGBoost (primary) + SARIMAX (baseline), 6h/24h horizons
  src/predict.py               latest-row inference -> frontend/data/predictions.json
  src/build.py                 assemble all frontend/data/*.json
  src/run_pipeline.py          calendar -> collect -> train -> predict -> build
frontend/
  index.html, item.html, ...   static site (vanilla JS + Chart.js, renders JSON only)
  data/*.json                  items, predictions, analytics, mayor effects, events, meta
  data/series/*.json           per-item 2h series for charts
.github/workflows/             collect.yml (2h cron + deploy), backfill.yml, deploy.yml
```

## Local setup

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\pip.exe install -r backend\requirements.txt

# first time only: full 2h backfill of the watchlist (~40k requests; respects the Coflnet
# rate limit — shard with --items if needed)
.\.venv\Scripts\python.exe backend\src\backfill.py

# daily loop
.\.venv\Scripts\python.exe backend\src\run_pipeline.py

# preview the site
.\.venv\Scripts\python.exe -m http.server 8765 --directory frontend
# open http://127.0.0.1:8765
```

Optionally create `.env` with `HYPIXEL_API_KEY=...` (loaded automatically if you use
python-dotenv; otherwise set the environment variable).

Useful flags:

```powershell
.\.venv\Scripts\python.exe backend\src\backfill.py --only SUMMONING_EYE --start 2024-01-01
.\.venv\Scripts\python.exe backend\src\train.py --window-days 365 --items SUMMONING_EYE BOOSTER_COOKIE
.\.venv\Scripts\python.exe backend\src\run_pipeline.py --skip calendar collect
```

## Configuration

`backend/config/watchlist.json` — `phase` / `phase_label` feed the site header, `mayors[]`
defines the phase tabs (`id`, `name`, `phase`, `tagline`), and `items[]` entries carry `id`,
`label`, `group`, `sector` and `mayors[]` (used by the item page to filter relevant terms).
The file-level `mayor_focus` (`aatrox`) drives the focus analysis.

`backend/config/event_calendar.json` — regenerated by `seed_calendar.py`:

- `terms[]`: `{start, end, year, mayor, mayor_name, minister, minister_name, source}`
  - `source: wiki_module` — exact dates from the wiki module (years 1, 88–178)
  - `source: derived_interpolation` — years 402–519 from the elections API; winner = top votes,
    minister = runner-up, dates anchored to the verified year-519 term start, uniform
    5.167 days/year (validated to ±11h against known 2026 term starts)
  - `source: gap` — spans with no structured election data (years 2–87 and 179–401); the model
    treats these as unlabeled baseline (all event dummies zero, `labeled = 0`)
- `minister_weight`: feature weight for minister dummies (0.35). A minister term is encoded as
  0.35 on `minister_<name>` and 1.0 on `mayor_<name>` when the mayor is the one in office.
- `updates[]`: optional game-update markers; a `near_update` flag (±24h) is derived from them.

## Analytics & models

- Grid: 2h. Dense per-item frames with forward-fill; `stale_h` / `filled` flag gaps
  (rows older than 48h are excluded from training).
- Features: log-return lags (2h…7d), 24h/7d/30d rolling z-scores and price ratios, spread,
  volume (sell/buy volume, moving week, ratio), cyclic hour/day-of-week, term age/remaining,
  term-boundary and game-update flags, one-hot mayor dummies (1.0), minister dummies (0.35),
  `focus_active` for the phase mayor, 7d correlation with Booster Cookie.
- Targets: forward log-returns at 6h and 24h. Time-ordered split; last 10% is test, 15% of the
  remainder is the early-stopping validation set. Everything is retrained on each 2h pipeline run
  (`--window-days 730` default), so models track regime changes.
- XGBoost is the primary model; SARIMAX(1,1,0) with event exog is a walk-forward baseline.
  Reported metrics: MAE, MAE-vs-naive (skill = 1 − MAE/MAE_naive), MAPE on price, directional
  accuracy, RMSE and skill from temporal-split and walk-forward backtests.
- Alerts: |z| of the 30d rolling z-score ≥ 3 (with 90d crossing history). Cross-item Pearson
  correlation of 2h returns uses a |z30| ≤ 3 filter and a 90d window.
- Inauguration effect (static): for each mayor's tagged items, computes median log-return over
  1d before / 1d during / 1d after inauguration across historical terms (mayor and minister roles
  separately), requiring ≥ 6 grid points and `stale_h < 48`; reports median %, term/item counts,
  positive-rate, and implied price = current mid × (1 + median). Static historical medians — not
  a live forecast, not financial advice.

## Current data snapshot

- Latest 2h bar: **2026-11-13T04:00:00Z**
- 129 items and 129 chart series
- 217 mayor/minister terms in the calendar
- 1 active alert and 15 correlated pairs in the latest rebuild
- Latest election transition: Foxy (mayor) / Finnegan (minister), year 525

## CI/CD (GitHub Actions)

- `collect.yml` — every 2h (`7 */2 * * *`) and on manual dispatch: collect → train → predict →
  build → commit `backend/datastore` + `frontend/data` → deploy Pages.
- `backfill.yml` — manual, parameterised historical re-pulls (shard by `items` if needed).
- `deploy.yml` — deploys `frontend/` on pushes touching the frontend.

Setup: in the repository, go to **Settings → Pages → Build and deployment → Source: GitHub Actions**.
Optionally add a repository secret `HYPIXEL_API_KEY` (not required). The scheduled workflow needs
`contents: write` (already set) so it can commit refreshed data.

## Known limitations

- Years 179–401 (Dec 2021 – Feb 2025) and 2–87 have no structured election data; terms there are
  explicitly unlabeled rather than guessed.
- Derived term dates assume uniform 5.167-day years; expect up to ~half a day of drift per term
  in most cases (special mayors that break the cycle can drift more).
- Several illiquid items have multi-month gaps in the Coflnet history; they are kept but modeled
  on whatever overlapping data exists (check per-item row counts and metrics).
- Paul (dungeon) and Diaz (economy) items have shorter bazaar histories than the original
  watchlist — most start in 2022–2024 — so they have fewer training rows.
- Skill values are measured on the most recent 10% window only and vary by item and regime;
  `skill <= 0` means the model did not beat a zero-change baseline.
- Bazaar prices move on game updates, content drops and manipulation; methodology is descriptive,
  not a trading guarantee.

## Disclaimer

Not affiliated with Hypixel or Mojang. Price data © their respective providers
(Hypixel API, Coflnet, wiki contributors, SkyblockElections). Forecasts are statistical
estimates, not financial advice.
