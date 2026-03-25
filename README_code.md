# BMS Show Board — Developer Notes

Source code for the Bengaluru Show Board weekly events pipeline.

Live tool: https://buildthisnextonline.github.io/bms-showboard
Live tool repo: https://github.com/BuildThisNextOnline/bms-showboard

---

## Architecture

Two Python scripts, one mapping file, one HTML page.

**bms_scraper.py** — connects to real Chrome via Chrome DevTools Protocol, navigates
BookMyShow Bengaluru category pages with full infinite scroll, extracts text and URLs,
saves to a local JSON cache. No Claude calls.

**bms_curator.py** — reads the scrape cache, splits each category into 20,000-char
batches, sends each batch to Claude via streaming API, gets back structured JSON,
normalises results using category_area_map.json, saves a versioned digest.

**category_area_map.json** — maps variant category labels to canonical names and maps
neighbourhood names to city zones. Edit this file and run remap.bat to fix label
issues without re-scraping or re-curating.

**showboard.html** — single self-contained HTML page. Two-level filters for category
and area, bidirectional counts, no framework, no backend. Gets copied to index.html
before each Git push.

The scraper and curator are deliberately separate. If curation fails for one category,
re-run just that — no re-scraping, no re-negotiating with Cloudflare, no wasted credits.

---

## Files

**Python scripts**

| File | Purpose |
|---|---|
| bms_scraper.py | Scrapes BMS via real Chrome + CDP with full infinite scroll. Saves scrape_latest.json. No Claude API calls |
| bms_curator.py | Reads scrape cache, curates with Claude in streaming batches, normalises categories and areas, saves digest_latest.json |

**Configuration**

| File | Purpose |
|---|---|
| category_area_map.json | Four sections: category_dedup (synonym mapping), category_groups (Level 1 groupings), area_dedup (area name variants), area_zones (neighbourhood to zone mapping). Edit to fix label drift |
| requirements.txt | Python dependencies — anthropic, playwright, requests, beautifulsoup4 |

**Bat files — run these**

| File | Purpose |
|---|---|
| launch_chrome_debug.bat | Starts Chrome on debug port 9222 — must be running before scraping |
| run_bms.bat | Full manual pipeline — scrape + curate + publish to both Git repos |
| remap.bat | Re-applies category/area normalisation to cached events, no API calls, publishes to both Git repos |
| publish_git.bat | Pushes current files to both Git repos without scraping or curating — use after editing showboard.html, README files, or category_area_map.json |

**Bat files — run once**

| File | Purpose |
|---|---|
| run_bms_scheduled.bat | Scheduled version of run_bms.bat — auto-launches Chrome, used by Windows Task Scheduler |
| setup_github.bat | One-time setup — initialises Git, creates both remotes (origin + code), sets up .gitignore |
| setup_schedule.bat | One-time setup — creates Windows Task Scheduler task for Sunday 9 AM runs. Run as Administrator |

**Task Scheduler**

| File | Purpose |
|---|---|
| BMS Show Board Weekly Scrape.xml | Task Scheduler task definition — exported for backup. Re-import via Task Scheduler if the task is lost |

---

## Setup

1. Install Python dependencies: `pip install -r requirements.txt`
2. Install Playwright: `playwright install`
3. Run setup_github.bat once to configure Git remotes and .gitignore
4. Run setup_schedule.bat as Administrator to create the weekly Task Scheduler task

For each run, Chrome must be on debug port 9222 — either launch it manually via
launch_chrome_debug.bat, or use run_bms_scheduled.bat which handles this automatically.

---

## Weekly Workflow (manual)

1. Double-click launch_chrome_debug.bat
2. Double-click run_bms.bat

Scrapes all BMS categories, curates with Claude, normalises, publishes to both Git repos.

---

## Fixing category or area labels

If the Show Board shows unexpected labels or wrong area mappings:

1. Edit category_area_map.json:
   - category_dedup: add synonyms (e.g. "Stand Up Comedy": "Comedy")
   - category_groups: assign labels to the right Level 1 group
   - area_dedup: add area name variants (e.g. "Koromangala": "Koramangala")
   - area_zones: assign areas to the right zone (Central/South/North/East/West)

2. Double-click remap.bat

No API calls, no scraping. Re-normalises all cached events and publishes.

---

## Recovery

| Situation | Action |
|---|---|
| Scraping worked, curation failed | Run run_bms.bat — scrape is cached, goes straight to curation |
| One category failed | `python bms_curator.py --category plays --force` |
| Fix area/category labels | Edit category_area_map.json, double-click remap.bat |
| Push file changes only | Double-click publish_git.bat |
| Force fresh scrape | `python bms_scraper.py --force` |
| Task Scheduler task lost | Re-import BMS Show Board Weekly Scrape.xml via Task Scheduler |

---

## Cache Behaviour

- Scrape data cached for 12 hours (SCRAPE_CACHE_HOURS in bms_scraper.py)
- Clean curation results cached and skipped on re-run
- Failed or salvaged categories retried automatically on next run
- Re-running the pipeline repeatedly during testing burns no extra API credits

---

## Cloudflare and Scroll Notes

BMS uses Cloudflare bot protection that fingerprints TLS cipher suite ordering.
Playwright's bundled Chromium gets blocked. The scraper connects to your real installed
Chrome via CDP — Cloudflare sees your real browser with your real IP reputation.

IPv6 is disabled (--disable-ipv6 Chrome flag) — BMS Cloudflare blocks IPv6 addresses
with no reputation history.

Infinite scroll uses 500px steps with 1.5s pauses to simulate natural scrolling.
Stop condition: the Y position of the "24/7 CUSTOMER CARE" footer element becomes
reachable by the viewport — meaning all listings above it have loaded.

---

## Cost

Each run costs roughly $1.40 in Anthropic API credits:
- ~42,500 input tokens at $3/M = ~$0.13
- ~85,000 output tokens at $15/M = ~$1.28

Output tokens dominate because 1,700+ events each generate a structured JSON object
with multiple fields and a one-liner reason to attend. At $1.40/run the pipeline may
run occasionally rather than every Sunday.

---

## Known Limitations

- Dates missing for many one-time events (Level 2 scraping not implemented)
- ~40% of events have no area data
- Category labels may drift week to week — fix with remap.bat
- Event counts not manually validated against BMS

---

## Articles

Product story: [BTNOnline](https://buildthisnext.substack.com)
Technical build story: [Promptcraft](https://promptcraftai.substack.com)
