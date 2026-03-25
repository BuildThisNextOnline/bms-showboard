"""
bms_scraper.py
--------------
Scrapes BookMyShow Bengaluru listings and saves raw data to scrape_latest.json.
Run bms_curator.py next to generate the digest with Claude.

Usage:
    python bms_scraper.py --playwright           # scrape all categories
    python bms_scraper.py --playwright --category events plays  # specific only
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ── Constants ──────────────────────────────────────────────────────────────────

IST = ZoneInfo("Asia/Kolkata")

BMS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://in.bookmyshow.com/",
}

# All category URLs for Bengaluru
# Primary URLs — /explore/ pattern
BMS_CATEGORIES = {
    "movies":      "https://in.bookmyshow.com/explore/movies-bengaluru",
    "events":      "https://in.bookmyshow.com/explore/events-bengaluru",
    "plays":       "https://in.bookmyshow.com/explore/plays-bengaluru",
    "sports":      "https://in.bookmyshow.com/explore/sports-bengaluru",
    "activities":  "https://in.bookmyshow.com/explore/activities-bengaluru",
}

# Fallback URLs — used if primary returns <800 chars (city redirect)
BMS_CATEGORIES_FALLBACK = {
    "movies":      "https://in.bookmyshow.com/bengaluru/movies",
    "events":      "https://in.bookmyshow.com/bengaluru/events",
    "plays":       "https://in.bookmyshow.com/bengaluru/plays",
    "sports":      "https://in.bookmyshow.com/bengaluru/sports",
    "activities":  "https://in.bookmyshow.com/bengaluru/activities",
}

# Maximum chars to capture per category page.
# Set high enough to capture all content from even the largest BMS pages.
# Reduce only if you want a lighter/faster scrape (not recommended).
MAX_CHARS_PER_PAGE = 500_000
REQUEST_DELAY_SEC = 1.5  # polite delay between requests


# ── Date window ────────────────────────────────────────────────────────────────

def get_week_window() -> tuple[date, date]:
    """Return (today, today+7) in IST — 8 days inclusive starting from run date."""
    today = date.today()
    return today, today + timedelta(days=7)


# ── Scraping ───────────────────────────────────────────────────────────────────

def _fetch_html(url: str, session: requests.Session) -> str | None:
    """Fetch a URL, return raw HTML or None on failure."""
    try:
        resp = session.get(url, headers=BMS_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [warn] Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def _extract_text(html: str) -> str:
    """
    Extract meaningful visible text from BMS HTML.
    BMS is a React SPA — on a plain GET we get the static shell + any
    server-side rendered / hydration data. We extract both visible text
    and any JSON-LD / inline __NEXT_DATA__ blobs which often contain
    the full listing data even before JS runs.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise tags
    for tag in soup(["script", "style", "noscript", "head", "meta", "link"]):
        # Keep script tags that look like JSON data blobs
        if tag.name == "script":
            t = tag.get("type", "")
            if "json" in t or (tag.string and "__NEXT_DATA__" in (tag.get("id", ""))):
                continue  # keep these
        tag.decompose()

    # Pull inline __NEXT_DATA__ JSON if present (Next.js hydration payload)
    next_data_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    next_data_text = ""
    if next_data_tag and next_data_tag.string:
        try:
            # Flatten it to a compact string — Claude can parse JSON inline
            next_data_text = "\n[PAGE DATA JSON]\n" + next_data_tag.string[:8000]
        except Exception:
            pass

    # Pull all visible text
    visible = soup.get_text(separator="\n", strip=True)

    combined = visible + next_data_text
    return combined[:MAX_CHARS_PER_PAGE]


def scrape_category(category: str, session: requests.Session) -> str:
    """Scrape one BMS category page, return extracted text."""
    url = BMS_CATEGORIES[category]
    print(f"  Fetching {category}: {url}", file=sys.stderr)
    html = _fetch_html(url, session)
    if not html:
        return f"[{category}: fetch failed]"
    text = _extract_text(html)
    if len(text.strip()) < 200:
        return f"[{category}: page returned minimal content — likely JS-rendered, try Playwright]"
    return f"=== {category.upper()} ===\n{text}"


def scrape_all(categories: list[str] | None = None) -> str:
    """
    Scrape requested categories (default: all).
    Returns concatenated extracted text, politely rate-limited.
    """
    cats = categories or list(BMS_CATEGORIES.keys())
    session = requests.Session()
    parts = []
    for i, cat in enumerate(cats):
        parts.append(scrape_category(cat, session))
        if i < len(cats) - 1:
            time.sleep(REQUEST_DELAY_SEC)
    # Return same dict format as scrape_all_playwright: {cat: (text, {})}
    return {cat: (part.split("\n", 1)[1] if "\n" in part else part, {})
            for cat, part in zip(cats, parts)}

# Pixels per scroll step — simulates one row of listings scrolling up (~500px)
SCROLL_STEP_PX = 500
# Seconds to wait after each scroll step for new listings to render
SCROLL_STEP_WAIT = 1.5
# Minimum new listing cards to appear per step to keep scrolling
SCROLL_MIN_NEW_CARDS = 1
# Footer anchor text — always present in BMS footer, identical across all pages.
# We scroll until the viewport reaches the element containing this text,
# which means all listings above it have been loaded and scrolled through.
FOOTER_ANCHOR = "24/7 CUSTOMER CARE"


def _extract_urls(page) -> dict:
    """Extract all BMS listing URLs from anchor tags on the current page."""
    url_map = {}
    try:
        links = page.eval_on_selector_all(
            "a[href*='bookmyshow'], a[href^='/']",
            """els => els.map(el => ({
                text: el.innerText.trim().toLowerCase().slice(0, 60),
                href: el.href
            })).filter(l => l.text.length > 2 && l.href.includes('bookmyshow'))"""
        )
        for link in links:
            if link["text"] and link["href"]:
                url_map[link["text"]] = link["href"]
    except Exception:
        pass
    return url_map


def _playwright_fetch_one(page, cat: str) -> tuple[str, dict]:
    """
    Fetch one BMS category page with infinite scroll support.
    Scrolls repeatedly until no new content loads, capturing all listings.
    Returns (body_text, url_map) where url_map is {lowercase_title_fragment: full_url}.
    """
    url = BMS_CATEGORIES[cat]
    print(f"  [playwright] Fetching {cat}: {url}", file=sys.stderr)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(4)

        # Wait for initial content to render
        for selector in ["[class*='card']", "[class*='event']", "[class*='movie']", "main"]:
            try:
                page.wait_for_selector(selector, timeout=4_000)
                break
            except Exception:
                continue

        # Scroll in 500px steps simulating natural mouse scrolling.
        # Stop condition: viewport reaches the BMS footer anchor element
        # ("24/7 CUSTOMER CARE") — this is always present and identical
        # across all BMS pages. When our scroll position reaches its Y
        # coordinate, we have scrolled through all listings above it.
        #
        # Fallback: if the anchor element can't be found (layout change),
        # stop after 10 consecutive steps with no new content.

        scroll_step = 0
        current_pos = 0
        no_new_steps = 0
        prev_text_len = 0

        while True:
            # Find Y position of the footer anchor element
            try:
                footer_y = page.evaluate("""
                    () => {
                        const els = document.querySelectorAll('*');
                        for (const el of els) {
                            if (el.innerText && el.innerText.trim() === '24/7 CUSTOMER CARE') {
                                return el.getBoundingClientRect().top + window.scrollY;
                            }
                        }
                        return null;
                    }
                """)
            except Exception:
                footer_y = None

            viewport_height = page.evaluate("window.innerHeight")

            # Stop if our scroll position has reached the footer anchor
            if footer_y is not None and current_pos + viewport_height >= footer_y:
                print(f"  [playwright] {cat}: reached footer anchor at Y={footer_y:,.0f}px after {scroll_step} steps — all listings loaded", file=sys.stderr)
                break

            # Scroll one step
            current_pos += SCROLL_STEP_PX
            page.evaluate(f"window.scrollTo(0, {current_pos})")
            time.sleep(SCROLL_STEP_WAIT)
            scroll_step += 1

            # Track content growth as fallback stop condition
            current_text_len = len(page.inner_text("body"))
            new_chars = current_text_len - prev_text_len

            footer_info = f"footer at Y={footer_y:,.0f}px" if footer_y else "footer not found"
            if scroll_step % 5 == 0:
                print(f"  [playwright] {cat} step {scroll_step}: pos={current_pos:,}px total={current_text_len:,} chars | {footer_info}", file=sys.stderr)

            if current_text_len > prev_text_len + 200:
                no_new_steps = 0
                prev_text_len = current_text_len
            else:
                no_new_steps += 1
                if no_new_steps >= 10:
                    print(f"  [playwright] {cat}: no new content for 10 steps — stopping at step {scroll_step}", file=sys.stderr)
                    break

        body_text = page.inner_text("body")
        body_text = body_text[:MAX_CHARS_PER_PAGE]

        url_map = _extract_urls(page)
        return body_text, url_map

    except Exception as e:
        print(f"  [playwright] {cat} fetch error: {e}", file=sys.stderr)
        return f"[{cat}: fetch failed — {e}]", {}


# ── Chrome debug port (default) ───────────────────────────────────────────────
CHROME_DEBUG_PORT = 9222

def _find_chrome_exe() -> str:
    """Find the installed Chrome executable on Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise RuntimeError(
        "Could not find Chrome. Make sure Google Chrome is installed, "
        "or set CHROME_EXE environment variable to your chrome.exe path."
    )


def _launch_chrome_debug(port: int = CHROME_DEBUG_PORT) -> None:
    """
    Launch real Chrome with remote debugging enabled.
    Chrome opens visibly — this is intentional (beats Cloudflare).
    Call this once; subsequent scraper runs reuse the same session.
    """
    import subprocess
    chrome_exe = os.environ.get("CHROME_EXE") or _find_chrome_exe()
    profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".chrome_bms_profile")
    os.makedirs(profile_dir, exist_ok=True)
    cmd = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        # Force IPv4 — prevents Cloudflare seeing an IPv6 address which
        # may have no reputation history and triggers blocks
        "--disable-ipv6",
        "about:blank",
    ]
    subprocess.Popen(cmd)
    print(f"  [chrome] Launched real Chrome on debug port {port}. Waiting for it to start…", file=sys.stderr)
    time.sleep(4)


def _is_chrome_running(port: int = CHROME_DEBUG_PORT) -> bool:
    """Check if Chrome is already listening on the debug port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def scrape_all_playwright(categories: list[str] | None = None, headless: bool = False) -> str:
    """
    Scrape BMS using your real installed Chrome via remote debugging.
    This bypasses Cloudflare because it IS your real Chrome — same TLS
    fingerprint, same browser profile, indistinguishable from manual browsing.

    On first run: launches Chrome automatically. On subsequent runs in the
    same session: reuses the already-open Chrome window.

    headless param is ignored (kept for API compatibility) — real Chrome
    always runs visibly.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        )

    cats = categories or list(BMS_CATEGORIES.keys())
    cat_results = {}

    # Launch real Chrome if not already running on debug port
    if not _is_chrome_running(CHROME_DEBUG_PORT):
        _launch_chrome_debug(CHROME_DEBUG_PORT)
        # Wait a bit more for Chrome to fully initialise
        time.sleep(4)

    if not _is_chrome_running(CHROME_DEBUG_PORT):
        raise RuntimeError(
            f"Chrome did not start on port {CHROME_DEBUG_PORT}. "
            "Try launching Chrome manually with:\n"
            f"  chrome.exe --remote-debugging-port={CHROME_DEBUG_PORT} --user-data-dir=.chrome_bms_profile"
        )

    print(f"  [chrome] Connecting to real Chrome on port {CHROME_DEBUG_PORT}…", file=sys.stderr)

    with sync_playwright() as p:
        # Connect to the real Chrome instance — not launching a new one.
        # If this raises, it means Chrome isn't accepting CDP connections yet.
        try:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{CHROME_DEBUG_PORT}")
        except Exception as e:
            raise RuntimeError(
                f"Could not connect to Chrome on port {CHROME_DEBUG_PORT}: {e}\n"
                "Make sure Chrome was launched via launch_chrome_debug.bat and is still open.\n"
                f"You can verify Chrome is ready by opening http://localhost:{CHROME_DEBUG_PORT}/json in your browser."
            )

        print(f"  [chrome] Connected. Browser version: {browser.version}", file=sys.stderr)

        # Use the existing default context
        contexts = browser.contexts
        print(f"  [chrome] Available contexts: {len(contexts)}", file=sys.stderr)
        context = contexts[0] if contexts else browser.new_context()
        page = context.new_page()

        # Navigate to BMS Bengaluru home first to establish city context
        print("  [chrome] Navigating to BMS Bengaluru…", file=sys.stderr)
        try:
            page.goto("https://in.bookmyshow.com/bengaluru", wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)
        except Exception:
            pass

        for cat in cats:
            text, url_map = _playwright_fetch_one(page, cat)
            print(f"  [chrome] {cat}: got {len(text)} chars, {len(url_map)} URLs", file=sys.stderr)

            # If still minimal, try fallback URL
            if len(text.strip()) < 800 and cat in BMS_CATEGORIES_FALLBACK:
                print(f"  [chrome] {cat}: minimal content, trying fallback URL…", file=sys.stderr)
                fallback_url = BMS_CATEGORIES_FALLBACK[cat]
                try:
                    page.goto(fallback_url, wait_until="domcontentloaded", timeout=45_000)
                    time.sleep(4)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)
                    text = page.inner_text("body")
                    # Re-extract URLs from fallback page
                    url_map.update(_extract_urls(page))
                    print(f"  [chrome] {cat} fallback: got {len(text)} chars", file=sys.stderr)
                except Exception as e:
                    print(f"  [chrome] {cat} fallback failed: {e}", file=sys.stderr)

            cat_results[cat] = (text[:MAX_CHARS_PER_PAGE], url_map)
            time.sleep(REQUEST_DELAY_SEC)

        # Leave the page and browser open — Chrome stays running for reuse

    return cat_results


# ── Scrape runner ──────────────────────────────────────────────────────────────

SCRAPE_OUTPUT_FILE  = "scrape_latest.json"
SCRAPE_MIN_CHARS    = 3000   # below this = bad scrape, always redo
SCRAPE_CACHE_HOURS  = 12      # skip re-scraping if data is fresher than this


def _load_existing_scrape() -> dict:
    """Load existing scrape_latest.json, return {} if missing or unreadable."""
    if not os.path.exists(SCRAPE_OUTPUT_FILE):
        return {}
    try:
        with open(SCRAPE_OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _category_needs_scrape(cat: str, existing: dict, cache_hours: float) -> tuple[bool, str]:
    """
    Return (should_scrape, reason).
    Checks: does existing data exist, is it fresh, and is it good quality?
    """
    from datetime import datetime, timezone, timedelta
    cat_data = existing.get("categories", {}).get(cat)
    if not cat_data:
        return True, "no existing data"

    # Check quality
    chars = cat_data.get("chars", len(cat_data.get("text", "")))
    if chars < SCRAPE_MIN_CHARS:
        return True, f"only {chars} chars (below threshold)"

    # Check freshness
    ts_str = cat_data.get("scraped_at")
    if not ts_str:
        return True, "no timestamp"
    try:
        scraped_at = datetime.fromisoformat(ts_str)
        age_hours = (datetime.now() - scraped_at).total_seconds() / 3600
        if age_hours > cache_hours:
            return True, f"stale ({age_hours:.1f}h old, limit {cache_hours}h)"
    except Exception:
        return True, "invalid timestamp"

    return False, f"cached ({chars} chars, {age_hours:.1f}h old)"


def run(categories: list[str] | None = None, use_playwright: bool = False,
        headless: bool = False, force: bool = False,
        cache_hours: float = SCRAPE_CACHE_HOURS) -> dict:
    """
    Scrape BMS and save raw text + URLs to scrape_latest.json.
    Skips categories whose cached data is still fresh and good quality.

    force=True  : re-scrape everything regardless of cache
    cache_hours : how old cached data can be before re-scraping (default 6h)
                  set to 0 to always re-scrape, or 999 to never re-scrape during testing
    """
    from datetime import datetime
    window_start, window_end = get_week_window()
    all_cats = categories or list(BMS_CATEGORIES.keys())

    print(f"[Scraper] Window : {window_start} → {window_end}")
    print(f"[Scraper] Mode   : {'playwright/chrome' if use_playwright else 'requests'}")

    # Load existing scrape to check what can be skipped
    existing = {} if force else _load_existing_scrape()

    # Decide which categories need scraping
    to_scrape = []
    cached_results = {}
    for cat in all_cats:
        needs, reason = _category_needs_scrape(cat, existing, cache_hours)
        if needs:
            to_scrape.append(cat)
            print(f"[Scraper] {cat:<12} SCRAPE   ({reason})")
        else:
            # Reuse cached data
            cd = existing["categories"][cat]
            cached_results[cat] = (cd["text"], cd.get("url_map", {}))
            print(f"[Scraper] {cat:<12} CACHED   ({reason})")

    # Scrape only what's needed
    new_results = {}
    if to_scrape:
        if use_playwright:
            new_results = scrape_all_playwright(to_scrape, headless=headless)
        else:
            new_results = scrape_all(to_scrape)
    else:
        print(f"[Scraper] All categories cached — nothing to scrape.")

    # Merge cached + new
    cat_texts = {**cached_results, **new_results}

    # Build payload — preserve existing category data, update scraped ones
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    payload = existing if existing else {
        "window_start": window_start.isoformat(),
        "window_end":   window_end.isoformat(),
        "categories":   {}
    }
    payload["window_start"] = window_start.isoformat()
    payload["window_end"]   = window_end.isoformat()
    if "categories" not in payload:
        payload["categories"] = {}

    total_urls = 0
    for cat, (text, url_map) in cat_texts.items():
        status = "OK" if len(text) > SCRAPE_MIN_CHARS else "MINIMAL"
        is_new = cat in new_results
        flag = "NEW" if is_new else "---"
        print(f"[Scraper] {cat:<12} {len(text):>6} chars  {len(url_map):>4} URLs  [{status}] {flag}")
        total_urls += len(url_map)
        if is_new:
            payload["categories"][cat] = {
                "text":       text,
                "url_map":    url_map,
                "chars":      len(text),
                "scraped_at": now_str,
            }

    # Top-level scraped_at = most recent category scrape timestamp
    cat_timestamps = [
        cd.get("scraped_at") for cd in payload.get("categories", {}).values()
        if cd.get("scraped_at")
    ]
    payload["scraped_at"] = max(cat_timestamps) if cat_timestamps else now_str

    with open(SCRAPE_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    skipped = len(all_cats) - len(to_scrape)
    print(f"[Scraper] Saved  : {SCRAPE_OUTPUT_FILE}  "
          f"({len(to_scrape)} scraped, {skipped} cached, {total_urls} total URLs)")
    if to_scrape:
        print(f"[Scraper] Done. Run bms_curator.py next.")
    else:
        print(f"[Scraper] Done. All data from cache — run bms_curator.py to re-curate if needed.")
    return cat_texts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape BookMyShow Bengaluru — saves raw data for bms_curator.py.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bms_scraper.py --playwright          # normal run (skips fresh categories)
  python bms_scraper.py --playwright --force  # re-scrape everything
  python bms_scraper.py --playwright --cache-hours 0    # always re-scrape
  python bms_scraper.py --playwright --cache-hours 999  # never re-scrape (testing)
  python bms_scraper.py --playwright --category movies  # one category only
"""
    )
    parser.add_argument("--playwright",    action="store_true", help="Use real Chrome via CDP (recommended)")
    parser.add_argument("--headless",      action="store_true", help="Headless Chrome (may be blocked)")
    parser.add_argument("--force",         action="store_true", help="Re-scrape all categories ignoring cache")
    parser.add_argument("--cache-hours",   type=float, default=SCRAPE_CACHE_HOURS,
                        help=f"Hours before cached scrape is considered stale (default: {SCRAPE_CACHE_HOURS})")
    parser.add_argument("--category", nargs="+", choices=list(BMS_CATEGORIES.keys()),
                        help="Scrape specific categories only (default: all)")
    args = parser.parse_args()
    run(categories=args.category, use_playwright=args.playwright, headless=args.headless,
        force=args.force, cache_hours=args.cache_hours)
