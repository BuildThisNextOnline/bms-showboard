"""
bms_curator.py
--------------
Reads scrape_latest.json (written by bms_scraper.py) and curates
the listings with Claude — one API call per category.

Usage:
    python bms_curator.py           # curate all categories, save digest
    python bms_curator.py --dry-run # show what would be curated, no API calls
    python bms_curator.py --category events plays  # curate specific categories only

Keeping scraping and curation separate means:
  - If curation fails, just re-run this file — no re-scraping, no Cloudflare.
  - If scraping fails, fix that first, then run this.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone


# ── Constants ──────────────────────────────────────────────────────────────────

SCRAPE_INPUT_FILE  = "scrape_latest.json"
DIGEST_LATEST_JSON = "digest_latest.json"
DIGEST_LATEST_MD   = "digest_latest.md"
DIGEST_ARCHIVE_DIR = "digests"

BMS_CATEGORIES = ["movies", "events", "plays", "sports", "activities"]

# ── Category + Area normalisation ──────────────────────────────────────────────

def _load_mappings() -> tuple[dict, dict, dict, dict]:
    """Load category/area dedup and grouping mappings from JSON file."""
    import pathlib
    map_file = pathlib.Path(__file__).parent / "category_area_map.json"
    if not map_file.exists():
        return {}, {}, {}, {}
    with open(map_file, encoding="utf-8") as f:
        m = json.load(f)
    return (m.get("category_dedup", {}),
            m.get("category_groups", {}),
            m.get("area_dedup", {}),
            m.get("area_zones", {}))

def _normalise_category(raw: str, dedup: dict) -> str:
    """Apply dedup mapping, then title-case normalise."""
    if not raw:
        return "Other"
    # Try exact match first
    if raw in dedup:
        return dedup[raw]
    # Try case-insensitive match
    raw_lower = raw.strip().lower()
    for k, v in dedup.items():
        if k.lower() == raw_lower:
            return v
    # No match — normalise casing
    return raw.strip().title().replace(" And ", " & ").replace("&Amp;", "&")

def _normalise_area(raw: str, dedup: dict) -> str | None:
    """Apply area dedup mapping. Returns None for vague areas."""
    if not raw:
        return None
    if raw in dedup:
        return dedup[raw]  # may be None (drop vague areas)
    raw_lower = raw.strip().lower()
    for k, v in dedup.items():
        if k.lower() == raw_lower:
            return v
    return raw.strip().title()

# Max chars to send to Claude in a single curation call.
# Large categories (events, activities) are split into batches of this size.
# Keep small enough to complete within the 10-minute API timeout.
BATCH_CHARS = 10_000


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_client():
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set.\n"
            "Run:  set ANTHROPIC_API_KEY=sk-ant-..."
        )
    return anthropic.Anthropic(api_key=api_key)


def _parse_array_response(response_text: str, cat_name: str) -> tuple[list, str]:
    """
    Parse Claude's JSON array response.
    Returns (events, status) where status is one of:
      "clean"    — full valid JSON array, no issues
      "salvaged" — truncated, partial recovery succeeded
      "refused"  — Claude returned prose instead of JSON (will re-curate next run)
      "failed"   — parse failed and salvage failed (will re-curate next run)
    """
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if not text.startswith("["):
        print(f"[Curator] WARN  : {cat_name} — prose returned instead of JSON array")
        print(f"           Preview: {text[:120]!r}")
        return [], "refused"
    try:
        return json.loads(text), "clean"
    except json.JSONDecodeError as e:
        print(f"[Curator] WARN  : {cat_name} — JSON truncated ({e}), attempting salvage…")
        try:
            truncated = text[:e.pos].rsplit("}", 1)[0] + "}"
            salvaged = json.loads("[" + truncated.lstrip("[") + "]")
            print(f"[Curator]          Salvaged {len(salvaged)} events from partial response")
            return salvaged, "salvaged"
        except Exception:
            print(f"[Curator]          Salvage failed — will retry next run")
            return [], "failed"


def _match_urls(events: list, url_map: dict) -> list:
    """Match event titles to BMS booking URLs using fuzzy prefix matching."""
    for ev in events:
        title_lower = ev.get("title", "").lower()
        matched = None
        for length in [60, 40, 20, 10]:
            prefix = title_lower[:length]
            if not prefix:
                break
            for key, url in url_map.items():
                if prefix in key or key[:len(prefix)] == prefix:
                    matched = url
                    break
            if matched:
                break
        ev["url"] = matched
    return events


# ── Per-category curation ──────────────────────────────────────────────────────

def curate_category(cat_name: str, raw_text: str, url_map: dict,
                    window_start: date, window_end: date, client) -> list:
    """One Claude API call for one category. Returns list of event dicts."""
    ws, we = window_start.isoformat(), window_end.isoformat()

    system = f"""You are an entertainment data extractor for BookMyShow Bengaluru.
Extract ALL distinct listings from the scraped page text provided.

DATE WINDOW: {ws} to {we}.

ABSOLUTE RULES — violation means your response is useless:
- Your ENTIRE response must be a JSON array. Start with "[", end with "]".
- NEVER write prose, explanations, apologies, or markdown. Not even one word outside the array.
- If date is unknown, use null — do NOT refuse or explain. null is always acceptable.
- If no events found, return exactly: []
- Missing data is fine — use null. Incomplete data is better than no data.

For each listing extract:
- title (string)
- category: most specific — Movie, Play, Concert, Comedy, Sports, Experience, Workshop,
  Food & Drink, Art & Culture, Kids, Nightlife, Wellness, Trekking, Gaming, Festivals,
  Amusement Parks, Parties, Quizzes and Competitions, or invent one if none fit.
- venue: full venue name including any hall/theatre name (string or null)
- area: neighbourhood or area only, e.g. "Koramangala", "Indiranagar", "Whitefield",
  "HSR Layout", "JP Nagar", "Jayanagar", "MG Road", "Marathahalli" etc. (string or null)
  Extract from venue address if present. Use null if not discernible.
- price: e.g. "₹499 onwards" or "FREE" (string or null)
- date_iso: YYYY-MM-DD of first/next occurrence. Resolve day names from {ws}. Use null if unknown — do NOT skip the event.
- timing: full date+time string, all show times if multiple (string or null)
- recurrence: "one-time" / "recurring" / null
- why: one sentence why someone in Bengaluru would enjoy this
- in_demand: true ONLY if page shows "Selling Fast" / "Filling Fast" / "Last Few Seats"

Include events where date_iso is null OR between {ws} and {we}. When in doubt, include.
Your response must start with [ and contain nothing else."""

    # Split large categories into batches of BATCH_CHARS each.
    # This avoids any single call hitting output token limits and gives
    # resilience — if one batch fails, only that batch needs retrying.
    # max_tokens per batch: 6x estimated input tokens, no ceiling.
    # Raised to 6x: events batch 1 had 121 events needing ~24K tokens from 15K chars input.
    # Split on newline boundaries so batches never cut mid-listing.
    # Find the last newline before each BATCH_CHARS boundary.
    chunks = []
    start = 0
    while start < len(raw_text):
        end = start + BATCH_CHARS
        if end >= len(raw_text):
            chunks.append(raw_text[start:])
            break
        # Walk back to the nearest newline
        split_at = raw_text.rfind("\n", start, end)
        if split_at == -1 or split_at <= start:
            split_at = end  # no newline found, split at char boundary
        chunks.append(raw_text[start:split_at])
        start = split_at + 1

    all_events = []
    overall_status = "clean"
    for batch_num, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            print(f"\n  [batch {batch_num}/{len(chunks)}]", end=" ", flush=True)
        input_tokens_est = len(chunk) // 4
        output_tokens_needed = input_tokens_est * 8
        max_tok = max(4096, ((output_tokens_needed + 1023) // 1024) * 1024)
        print(f"(max_tokens={max_tok})", end=" ", flush=True)

        full_text = ""
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=max_tok,
            system=system,
            messages=[{
                "role": "user",
                "content": (
                    f"BookMyShow Bengaluru — {cat_name.upper()} listings"
                    + (f" (batch {batch_num} of {len(chunks)})" if len(chunks) > 1 else "")
                    + f":\n\n{chunk}\n\n"
                    f"Extract all {cat_name} listings between {ws} and {we}. JSON array only."
                )
            }]
        ) as stream:
            for text_chunk in stream.text_stream:
                full_text += text_chunk
            usage = stream.get_final_message().usage
            print(f" [in={usage.input_tokens} out={usage.output_tokens} max={max_tok}]", end="", flush=True)
        batch_events, batch_status = _parse_array_response(full_text, f"{cat_name}[batch {batch_num}]")
        all_events.extend(batch_events)
        if batch_status != "clean":
            overall_status = batch_status

    events = all_events
    status = overall_status

    # Set category and match URLs
    for ev in events:
        if not ev.get("category"):
            ev["category"] = cat_name.capitalize()
    return _match_urls(events, url_map), status


# ── Top pick + curator note ────────────────────────────────────────────────────

def pick_top_and_note(all_events: list, window_start: date, client) -> tuple[dict, str]:
    """One small Claude call to pick top event and write curator note."""
    titles = [ev["title"] for ev in all_events[:50]]
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"Bengaluru this week: {json.dumps(titles)}\n\n"
                    f"1. Pick the single best event as top_pick.\n"
                    f"2. Write one witty curator_note about Bengaluru's cultural mood.\n"
                    f'Respond ONLY as JSON: {{"top_pick": {{"title": "", "category": "", "reason": ""}}, "curator_note": ""}}'
                )
            }]
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1][4:].strip() if text.split("```")[1].startswith("json") else text.split("```")[1].strip()
        meta = json.loads(text)
        return meta.get("top_pick"), meta.get("curator_note", "")
    except Exception as e:
        print(f"[Curator] WARN  : top_pick/note failed ({e})")
        return None, ""


# ── Output formatting ──────────────────────────────────────────────────────────

def format_markdown(data: dict) -> str:
    w = data.get("window", {})
    lines = [f"# 🎭 Bengaluru Show Board — {w.get('from')} to {w.get('to')}\n"]
    tp = data.get("top_pick")
    if tp:
        lines += [f"## ⭐ Top Pick: {tp['title']}", f"*{tp.get('reason', '')}*\n"]
    lines.append(f"**{data.get('total_events', 0)} events across {len(data.get('categories', []))} categories.**\n")
    for cat in data.get("categories", []):
        lines.append(f"### {cat['name']} ({len(cat.get('events', []))})")
        for ev in cat.get("events", []):
            flag = " 🔥" if ev.get("in_demand") else ""
            lines.append(f"**{ev['title']}**{flag}")
            meta = []
            if ev.get("venue"):      meta.append(f"📍 {ev['venue']}")
            if ev.get("timing"):     meta.append(f"🕐 {ev['timing']}")
            if ev.get("price"):      meta.append(f"₹ {ev['price']}")
            if ev.get("recurrence"): meta.append(f"🔁 {ev['recurrence']}")
            if ev.get("url"):        meta.append(f"🔗 {ev['url']}")
            if meta: lines.append("  " + "  |  ".join(meta))
            if ev.get("why"): lines.append(f"  *{ev['why']}*")
            lines.append("")
    note = data.get("curator_note")
    if note: lines.append(f"---\n*{note}*")
    return "\n".join(lines)


# ── Versioned save ─────────────────────────────────────────────────────────────

def save_versioned(data: dict, digest_md: str) -> str:
    now_ist = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5, minutes=30)
    ts = now_ist.strftime("%Y-%m-%d_%H%M%S")
    os.makedirs(DIGEST_ARCHIVE_DIR, exist_ok=True)
    json_path = os.path.join(DIGEST_ARCHIVE_DIR, f"digest_{ts}.json")
    md_path   = os.path.join(DIGEST_ARCHIVE_DIR, f"digest_{ts}.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(digest_md)
    shutil.copy2(json_path, DIGEST_LATEST_JSON)
    shutil.copy2(md_path,   DIGEST_LATEST_MD)
    return json_path


# ── Main ───────────────────────────────────────────────────────────────────────

def remap() -> dict:
    """
    Re-apply category/area normalisation to cached curated events.
    No Claude API calls — reads existing curated_events from scrape_latest.json,
    re-runs the normalisation pass, and saves a new digest.
    Use this after updating category_area_map.json without needing to re-curate.
    """
    if not os.path.exists(SCRAPE_INPUT_FILE):
        raise FileNotFoundError(f"{SCRAPE_INPUT_FILE} not found.")
    with open(SCRAPE_INPUT_FILE, encoding="utf-8") as f:
        scrape = json.load(f)

    window_start = date.fromisoformat(scrape["window_start"])
    window_end   = date.fromisoformat(scrape["window_end"])
    scraped_at   = scrape.get("scraped_at", "unknown")

    print(f"[Curator] Remap  : re-applying normalisation from category_area_map.json")
    print(f"[Curator] Window : {window_start} → {window_end}")

    # Collect all cached events
    all_cat_results: dict[str, list] = {}
    for cat, cat_data in scrape["categories"].items():
        cached = cat_data.get("curated_events")
        if cached is not None:
            all_cat_results[cat] = cached
            print(f"[Curator] Loaded : {cat} ({len(cached)} events)")
        else:
            print(f"[Curator] SKIP   : {cat} — no cached events")

    # Load mappings and normalise
    cat_dedup, cat_groups, area_dedup, area_zones = _load_mappings()
    cat_to_group: dict[str, str] = {}
    for group, labels in cat_groups.items():
        for label in labels:
            cat_to_group[label.lower()] = group

    merged: dict[str, list] = {}
    for cat, events in all_cat_results.items():
        for ev in events:
            raw_cat = ev.get("category") or cat.capitalize()
            canonical_cat = _normalise_category(raw_cat, cat_dedup)
            ev["category"] = canonical_cat
            ev["category_group"] = cat_to_group.get(canonical_cat.lower(), "Other")
            raw_area = ev.get("area")
            if raw_area:
                norm_area = _normalise_area(raw_area, area_dedup)
                ev["area"] = norm_area
                if norm_area:
                    norm_area_lower = norm_area.lower()
                    ev["area_zone"] = next(
                        (zone for zone, areas in area_zones.items()
                         if any(a.lower() == norm_area_lower for a in areas)),
                        "Other"
                    )
                else:
                    ev["area_zone"] = None
            else:
                ev["area_zone"] = None
            merged.setdefault(canonical_cat, []).append(ev)

    all_categories = [{"name": label, "events": evs} for label, evs in merged.items()]
    total_events = sum(len(c["events"]) for c in all_categories)

    # Reuse existing top_pick and curator_note from latest digest if available
    top_pick, curator_note = {}, ""
    if os.path.exists(DIGEST_LATEST_JSON):
        with open(DIGEST_LATEST_JSON, encoding="utf-8") as f:
            existing = json.load(f)
        top_pick    = existing.get("top_pick", {})
        curator_note = existing.get("curator_note", "")
        print(f"[Curator] Reusing top pick and curator note from existing digest")

    data = {
        "fetched_at":   scraped_at,
        "window":       {"from": window_start.isoformat(), "to": window_end.isoformat()},
        "top_pick":     top_pick,
        "categories":   all_categories,
        "total_events": total_events,
        "curator_note": curator_note,
    }

    path = save_versioned(data, format_markdown(data))
    print(f"[Curator] Saved  : {path}")
    print(f"[Curator] Latest : {DIGEST_LATEST_JSON}")
    print(f"[Curator] Total  : {total_events} events across {len(all_categories)} categories")
    return data


def run(categories: list[str] | None = None, dry_run: bool = False,
        force: bool = False) -> dict:
    """
    Curate BMS scrape data with Claude.
    Skips categories that were already cleanly curated (not salvaged).
    force=True re-curates everything regardless of cache.
    """
    if not os.path.exists(SCRAPE_INPUT_FILE):
        raise FileNotFoundError(
            f"{SCRAPE_INPUT_FILE} not found. Run bms_scraper.py first."
        )
    with open(SCRAPE_INPUT_FILE, encoding="utf-8") as f:
        scrape = json.load(f)

    window_start = date.fromisoformat(scrape["window_start"])
    window_end   = date.fromisoformat(scrape["window_end"])
    scraped_at   = scrape.get("scraped_at", "unknown")
    cats_to_run  = categories or list(scrape["categories"].keys())

    print(f"[Curator] Input  : {SCRAPE_INPUT_FILE} (scraped {scraped_at})")
    print(f"[Curator] Window : {window_start} → {window_end}")

    if dry_run:
        print("[Curator] DRY RUN — no API calls made")
        for cat in cats_to_run:
            d = scrape["categories"].get(cat, {})
            cached = d.get("curated_events")
            status = f"cached ({len(cached)} events)" if cached else "needs curation"
            print(f"  {cat:<12} {len(d.get('text',''))!s:>6} chars  [{status}]")
        return {}

    client = _get_client()
    # Collect ALL category results — both cached and freshly curated
    all_cat_results: dict[str, list] = {}  # {cat_name: [events]}

    for cat in cats_to_run:
        cat_data = scrape["categories"].get(cat)
        if not cat_data:
            print(f"[Curator] SKIP   : {cat} — not in scrape file")
            continue

        # Check for clean cached curation
        cached_events = cat_data.get("curated_events")
        was_salvaged  = cat_data.get("curation_salvaged", False)

        # Retry if: salvaged, refused (0 events + salvaged flag), or explicitly forced
        # A "refused" result is stored with curation_salvaged=True and 0 events
        is_clean = (cached_events is not None and not was_salvaged
                    and len(cached_events) > 0)
        if is_clean and not force:
            print(f"[Curator] CACHED : {cat} ({len(cached_events)} events, clean)")
            all_cat_results[cat] = cached_events
            continue
        elif cached_events is not None and not force and len(cached_events) == 0 and not was_salvaged:
            # Genuinely empty category (e.g. sports with no events) — trust it
            print(f"[Curator] CACHED : {cat} (0 events, clean — category may be empty)")
            all_cat_results[cat] = cached_events
            continue

        # Need to curate
        print(f"[Curator] Curate : {cat}…", end=" ", flush=True)
        try:
            events, status = curate_category(
                cat, cat_data["text"], cat_data["url_map"],
                window_start, window_end, client
            )
            flag = f"  [{status}]" if status != "clean" else ""
            print(f"{len(events)} events{flag}")
            all_cat_results[cat] = events

            # Only cache as clean if status is "clean" — salvaged/refused/failed
            # will be retried automatically on next run
            scrape["categories"][cat]["curated_events"]    = events
            scrape["categories"][cat]["curation_salvaged"] = (status != "clean")
        except Exception as e:
            print(f"FAILED ({e})")
            # Mark as salvaged so next run retries it
            scrape["categories"][cat]["curation_salvaged"] = True
            all_cat_results[cat] = cached_events or []

    # Save updated scrape file (with curated_events embedded)
    with open(SCRAPE_INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(scrape, f, ensure_ascii=False, indent=2)

    # Load normalisation mappings
    cat_dedup, cat_groups, area_dedup, area_zones = _load_mappings()

    # Build reverse lookup: canonical label → Level 1 group
    cat_to_group: dict[str, str] = {}
    for group, labels in cat_groups.items():
        for label in labels:
            cat_to_group[label.lower()] = group

    # Flatten all events, normalise category + area, merge by canonical category
    merged: dict[str, list] = {}
    for cat, events in all_cat_results.items():
        for ev in events:
            # Normalise category
            raw_cat = ev.get("category") or cat.capitalize()
            canonical_cat = _normalise_category(raw_cat, cat_dedup)
            ev["category"] = canonical_cat
            ev["category_group"] = cat_to_group.get(canonical_cat.lower(), "Other")

            # Normalise area
            raw_area = ev.get("area")
            if raw_area:
                norm_area = _normalise_area(raw_area, area_dedup)
                ev["area"] = norm_area  # None means drop it
                # Find zone
                if norm_area:
                    norm_area_lower = norm_area.lower()
                    ev["area_zone"] = next(
                        (zone for zone, areas in area_zones.items()
                         if any(a.lower() == norm_area_lower for a in areas)),
                        "Other"
                    )
                else:
                    ev["area_zone"] = None
            else:
                ev["area_zone"] = None

            merged.setdefault(canonical_cat, []).append(ev)

    all_categories = [{"name": label, "events": evs} for label, evs in merged.items()]
    total_events = sum(len(c["events"]) for c in all_categories)

    # Top pick + curator note
    all_events_flat = [ev for cat in all_categories for ev in cat["events"]]
    print(f"[Curator] Picking top event + writing note…", end=" ", flush=True)
    top_pick, curator_note = pick_top_and_note(all_events_flat, window_start, client)
    print("done")

    data = {
        "fetched_at":   scraped_at,
        "window":       {"from": window_start.isoformat(), "to": window_end.isoformat()},
        "top_pick":     top_pick,
        "categories":   all_categories,
        "total_events": total_events,
        "curator_note": curator_note,
    }

    path = save_versioned(data, format_markdown(data))
    print(f"[Curator] Saved  : {path}")
    print(f"[Curator] Latest : {DIGEST_LATEST_JSON}")
    print(f"[Curator] Total  : {total_events} events across {len(all_categories)} categories")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Curate BMS scrape data with Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bms_curator.py                        # curate (skips already-clean categories)
  python bms_curator.py --force                # re-curate everything
  python bms_curator.py --category movies      # re-curate one category only
  python bms_curator.py --dry-run              # preview without API calls
"""
    )
    parser.add_argument("--category", nargs="+", choices=BMS_CATEGORIES,
                        help="Curate specific categories only (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be curated without making API calls")
    parser.add_argument("--force",   action="store_true",
                        help="Re-curate all categories ignoring cache")
    parser.add_argument("--remap", action="store_true",
                        help="Re-apply category/area normalisation to cached events (no API calls)")
    args = parser.parse_args()
    if args.remap:
        remap()
    else:
        run(categories=args.category, dry_run=args.dry_run, force=args.force)
