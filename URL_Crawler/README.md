# URL Crawler

Purpose: collect **product listing URLs only** from configured category pages on Carousell Malaysia and Mudah.my.

It does not open product detail pages, extract descriptions, download images, or use a database.

## Run scripts

Exactly four run scripts, one per site/mode combination:

| Script | Site | Mode | Target |
|---|---|---|---:|
| `run_carousell_soft.bat` | Carousell | soft | 150 |
| `run_carousell_full.bat` | Carousell | full | 1,500 |
| `run_mudah_soft.bat` | Mudah | soft | 100 |
| `run_mudah_full.bat` | Mudah | full | 1,000 |

Plus `setup.bat` (one-time environment setup) and `monitor.bat` (live progress viewer, works for either site).

## Output

Every site + mode combination writes to its own files, so runs never overwrite each other:

- `output/carousell_urls_soft.csv` / `output/carousell_summary_soft.csv` — from `run_carousell_soft.bat`
- `output/carousell_urls_full.csv` / `output/carousell_summary_full.csv` — from `run_carousell_full.bat`
- `output/mudah_urls_soft.csv` / `output/mudah_summary_soft.csv` — from `run_mudah_soft.bat`
- `output/mudah_urls_full.csv` / `output/mudah_summary_full.csv` — from `run_mudah_full.bat`

A one-off manual run with `--output`/`--summary` (e.g. for a quick ad-hoc test) uses whatever paths you pass and never touches the files above.

Exact columns:

```csv
app,category,product_url
Carousell,Phones,https://www.carousell.com.my/p/example-phone-1234567890/
Mudah,Phones,https://www.mudah.my/example-phone-1234567890.htm
```

The `*_summary_*.csv` file reports how many URLs were collected per category, plus a `status` (`complete` / `partial` / `failed`) and an `error` message when something went wrong.

## Targets

Carousell full run pulled up to 1,500 candidate URLs, Mudah up to 1,000 (same category taxonomy) — a deliberate oversupply against the Data Collector's original 2,500-approved-listing plan, since not every crawled URL survives capture/review into an approved listing. That plan was later scoped down to the 2,209 listings actually approved (see `GuardianLens_Data_Collector_v_1.0.0/config/platform_targets.yaml`); this crawler's job is done and these numbers are historical, not a target still being pursued. Each site's soft test uses the same category proportions at a smaller scale for a quick correctness check.

### Carousell (`run_carousell_soft.bat` / `run_carousell_full.bat`)

| Category | Soft test | Full target |
|---|---:|---:|
| Phones | 23 | 225 |
| Laptops | 18 | 180 |
| Audio | 15 | 150 |
| Gaming | 15 | 150 |
| Fashion | 15 | 150 |
| Home Appliances | 15 | 150 |
| Cameras | 12 | 120 |
| Sports | 11 | 105 |
| Wearables | 9 | 90 |
| Tablets | 7 | 75 |
| Collectibles | 7 | 75 |
| Other | 3 | 30 |
| **Total** | **150** | **1,500** |

### Mudah (`run_mudah_soft.bat` / `run_mudah_full.bat`)

| Category | Soft test | Full target |
|---|---:|---:|
| Phones | 15 | 150 |
| Laptops | 12 | 120 |
| Audio | 10 | 100 |
| Gaming | 10 | 100 |
| Fashion | 10 | 100 |
| Home Appliances | 10 | 100 |
| Cameras | 8 | 80 |
| Sports | 7 | 70 |
| Wearables | 6 | 60 |
| Tablets | 5 | 50 |
| Collectibles | 5 | 50 |
| Other | 2 | 20 |
| **Total** | **100** | **1,000** |

## Windows setup

1. Extract the ZIP.
2. Double-click `setup.bat` once.
3. Double-click `run_carousell_soft.bat` (Carousell) or `run_mudah_soft.bat` (Mudah).
4. When finished, open the corresponding `output/<site>_urls_soft.csv`.

Both sites block headless Chromium with a Cloudflare challenge on every request, so all
four run scripts launch a visible (headed) browser window by default — this is required,
not optional. Do not close that window while a run is in progress.

For the full runs, use `run_carousell_full.bat` (1,500 URLs) or `run_mudah_full.bat`
(1,000 URLs). These write to the `*_full.csv` files, separate from the soft-test files.

Each run script opens **two windows automatically** — the crawl itself, and a second
"Monitor" window with the live per-category progress table — so you never need to launch
monitoring by hand. The run script also clears that mode's old output files first, so the
monitor never shows stale results from a previous run. Just close the Monitor window
whenever you're done watching; the crawl keeps running independently of it. To reopen a
monitor by hand for a run already in progress, double-click `monitor.bat` (it asks which
site to watch, or pass args to skip the prompt: `monitor.bat carousell soft`).

## Command line

```powershell
.venv\Scripts\python.exe crawler.py --site carousell --mode soft --headed
.venv\Scripts\python.exe crawler.py --site carousell --mode full --headed
.venv\Scripts\python.exe crawler.py --site mudah --mode soft --headed
.venv\Scripts\python.exe crawler.py --site mudah --mode full --headed
```

`--site` defaults to `carousell` if omitted.

## Category configuration

Edit `config/categories.csv` (Carousell) or `config/categories_mudah.csv` (Mudah) if a category URL changes.

`seed_urls` supports multiple pages separated by `|`. Carousell's Fashion and Mudah's Fashion are both configured with separate Women's and Men's seed pages.

## Behavior

- Opens only configured category pages.
- Collects links matching each site's listing URL pattern (Carousell: `/p/...-<listing-id>/`, Mudah: `...-<listing-id>.htm`).
- Removes URL query strings and fragments.
- Deduplicates URLs globally across every category and seed within a run (one shared set, checked before each URL is written).
- Carousell: scrolls and uses `Show more results` when available. Mudah: pages through numbered results via the `?o=N` parameter / "Next" button.
- Stops each category when its target is reached.
- Writes rows to CSV as it runs, so completed rows survive a manual stop.
- Stops trying a page after repeated scroll/page rounds produce no new links.

## Notes

Website structure can change. If either site changes its HTML or category URLs, update the matching `config/categories*.csv` or the listing-link selector in `crawler.py`.

Use a reasonable request rate and comply with each site's terms and access controls.
