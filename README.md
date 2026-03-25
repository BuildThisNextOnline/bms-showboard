# The Bengaluru Show Board

A weekly events digest for Bengaluru, built on BookMyShow data and curated by Claude.

**Live:** https://buildthisnextonline.github.io/bms-showboard

---

Every week, this page surfaces everything happening in Bengaluru — movies, concerts,
plays, comedy, sports, trekking, workshops, nightlife — 1,700+ listings in one place,
with direct booking links to BookMyShow.

No login. No app. Just open the URL.

---

## How to use the filters

**Event Type** filters let you narrow by category. Click a broad group (Live Arts,
Sports & Fitness, Workshops & Learning) to see its subcategories — then click any
subcategory to narrow further. You can select multiple groups and multiple subcategories
simultaneously.

**Area** filters let you narrow by part of the city. Click a zone (South, North, East,
Central, West) to see its neighbourhoods — then click any neighbourhood to narrow further.
You can select multiple zones and multiple neighbourhoods simultaneously.

Filters across both dimensions work together — selecting Live Arts and South shows you
Live Arts events in South Bengaluru. The counts update in both directions as you filter.

Events with no area data appear under **Unknown** — still discoverable, just not
geographically placed.

---

## What's not perfect yet

**Dates are missing for many one-time events.** BMS listing cards don't always show
specific dates for touring shows — the date lives on the individual event page, which
this tool doesn't visit yet. These events still appear with venue and price.

**Some listings may fall outside the week's window.** When no date is visible on a
listing card, the curator defaults to including rather than excluding. An occasional
out-of-window listing may appear.

**About 40% of events have no area data.** Many BMS listing cards don't mention a
neighbourhood. These appear under Unknown.

**The digest is not always updated weekly.** Each run costs roughly $1.40 in API credits.
The pipeline is built to run every Sunday but may run less frequently.

---

## Background

Built to validate the product hypothesis in:
[BookMyShow: The Case for Date-First Event Discovery](https://buildthisnext.substack.com)

The build story (product): [BTNOnline article](https://buildthisnext.substack.com)
The build story (technical): [Promptcraft article](https://promptcraftai.substack.com)

Source code: https://github.com/BuildThisNextOnline/bms-showboard-code

---

If you're at BookMyShow and want to discuss how to improve event discovery on the
platform, or if you're interested in Product Consulting: reach out via Substack or
LinkedIn.

*Kamal Gaur — Build This Next Online*
