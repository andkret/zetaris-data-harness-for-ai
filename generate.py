#!/usr/bin/env python3
"""
generate.py: builds the Northbound Outfitters course dataset described in DATA_SPEC.md.

INTERNAL ONLY. This script hard-codes the planted findings from DATA_SPEC.md
section 7. Publishing it next to the data puts the answer key next to the exam.
Ship the generated files and a neutral README, never this file.

    python generate.py --events 20000     # sample run, inspect before scaling
    python generate.py                    # full run, 2,000,000 events

Build order follows DATA_SPEC.md section 9:
    products -> campaigns -> sessions -> events -> orders (derived from purchase
    events) -> spend (back-fitted) -> briefs -> validation -> size report

Every random draw comes from one numpy Generator seeded with SEED and passed
through the whole script, so every run produces identical files.

Two techniques do most of the work of making the planted findings hold:

* Exact quotas. Conversions, funnel depth, device mix, camp_002's Cooking & Water
  share and returns are allocated as exact counts (round(n * rate)), and the
  seeded generator only picks *which* sessions or lines get them. The findings
  therefore land on target at any scale instead of drifting with sampling noise.
* Spend is back-fitted. Daily clicks come from daily sessions (85-92% ratio);
  each campaign's total spend comes from its realised gross revenue divided by
  a target ROAS. That fixes the F1/F2/F6 ranking regardless of how revenue
  happens to fall.

Validation (section 8) re-reads every file from disk and checks the findings by
querying the generated data, not the parameters below.
"""
from __future__ import annotations

import argparse
import bisect
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

# ---------------------------------------------------------------------------
# Ground rules (section 0)
# ---------------------------------------------------------------------------
SEED = 20260101
FULL_SCALE_EVENTS = 2_000_000
N_DAYS = 181                                    # 2026-01-01 .. 2026-06-30 inclusive
MS_PER_DAY = 86_400_000
T0_MS = int(np.datetime64("2026-01-01T00:00:00", "ms").astype(np.int64))
T_END_MS = T0_MS + N_DAYS * MS_PER_DAY - 1      # 2026-06-30 23:59:59.999
MONTH_START_DAY = [0, 31, 59, 90, 120, 151]     # day index of the 1st of Jan..Jun
MONTH_LABELS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
DAY_MONTH = np.searchsorted(MONTH_START_DAY, np.arange(N_DAYS), side="right") - 1

SESSIONS_PER_EVENT = 0.09           # 2M events -> 180k sessions (~11.1 events each)
USERS_PER_SESSION = 130 / 180       # ~130k distinct users for 180k sessions
CAMPAIGN_TRAFFIC_SHARE = 0.58       # section 4: ~58% of sessions carry a campaign
JUNE_OVER_JANUARY = 2.5             # F4: session volume ramp
BASELINE_RETURN_RATE = 0.08         # share of all order lines returned
CAMP_007_RETURN_RATE = 0.24         # F6
CAMP_002_COOKING_SHARE = 0.60       # F3, share of camp_002 order lines

# Stage = the deepest funnel step a session reaches. FUNNEL_REACH is the share
# of all sessions reaching at least that stage (section 4 baseline funnel).
BOUNCE, PRODUCT, CART, CHECKOUT, PURCHASE = range(5)
FUNNEL_REACH = {PRODUCT: 0.62, CART: 0.14, CHECKOUT: 0.06, PURCHASE: 0.036}

# Order shape (section 3)
LINES_PER_ORDER = ([1, 2, 3, 4], [0.50, 0.33, 0.12, 0.05])      # mean 1.72
QUANTITY = ([1, 2, 3], [0.82, 0.14, 0.04])
DISCOUNTS = ([5, 10, 15, 20, 25, 30], [0.25, 0.25, 0.20, 0.15, 0.10, 0.05])
NO_DISCOUNT_SHARE = 0.70

# ID ranges. Integers everywhere (section 1). Distinct ranges so that joining on
# the wrong key returns nothing instead of plausible-looking garbage.
FIRST_PRODUCT_ID = 1001
FIRST_UID = 100_001
FIRST_SESS_ID = 1_000_001
FIRST_ORDER_ID = 50_001

SITE_DOMAIN = "northboundoutfitters.com"

# ---------------------------------------------------------------------------
# Catalog (section 2)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Category:
    name: str
    code: str
    slug: str
    price_lo: int
    price_hi: int
    base_weight: float          # share of browsing/buying before campaign skew
    season: tuple               # Jan..Jun multiplier (F4)
    # (subcategory, slug, price_scale, descriptors). price_scale shrinks the
    # right-skewed draw so footprints don't price like tents.
    subcategories: tuple


CATEGORIES = [
    Category("Tents & Shelter", "TNT", "tents-shelter", 80, 700, 0.14,
             (0.45, 0.50, 0.70, 1.00, 1.90, 2.40), (
                 ("Tents", "tents", 1.00, ("1P Tent", "2P Tent", "3P Tent", "4P Tent", "UL 2P Tent", "Dome Tent")),
                 ("Tarps", "tarps", 0.45, ("Flat Tarp", "Hex Tarp", "UL Tarp", "Tarp Shelter")),
                 ("Footprints", "footprints", 0.15, ("Footprint", "Groundsheet", "Tent Footprint")))),
    Category("Backpacks", "BPK", "backpacks", 40, 320, 0.17,
             (0.80, 0.80, 0.95, 1.05, 1.20, 1.30), (
                 ("Daypacks", "daypacks", 0.35, ("18L Daypack", "22L Daypack", "28L Daypack")),
                 ("Hiking Packs", "hiking-packs", 1.00, ("38L Pack", "45L Pack", "55L Pack", "65L Pack")),
                 ("Travel Packs", "travel-packs", 0.75, ("40L Travel Pack", "Carry-On Pack", "Duffel Pack")))),
    Category("Sleep Systems", "SLP", "sleep-systems", 30, 450, 0.15,
             (1.10, 1.00, 1.00, 1.00, 1.05, 1.10), (
                 ("Sleeping Bags", "sleeping-bags", 1.00, ("-5C Down Bag", "0C Synthetic Bag", "5C Quilt", "-10C Down Bag")),
                 ("Sleeping Pads", "sleeping-pads", 0.50, ("Air Pad", "Foam Pad", "Insulated Air Pad", "Self-Inflating Mat")),
                 ("Pillows", "pillows", 0.08, ("Inflatable Pillow", "Camp Pillow", "Foam Pillow")))),
    Category("Footwear", "FTW", "footwear", 60, 260, 0.18,
             (0.55, 0.60, 0.80, 1.05, 1.80, 2.20), (
                 ("Hiking Boots", "hiking-boots", 1.00, ("Mid WP Boot", "Leather Boot", "Hiking Boot", "Backpacking Boot")),
                 ("Trail Runners", "trail-runners", 0.75, ("Trail Runner", "Trail Shoe", "Approach Shoe")),
                 ("Sandals", "sandals", 0.35, ("Sport Sandal", "Camp Sandal", "River Sandal")))),
    Category("Apparel", "APP", "apparel", 25, 380, 0.21,
             (1.40, 1.25, 1.05, 0.95, 0.85, 0.80), (
                 ("Shell Jackets", "shell-jackets", 1.00, ("Rain Shell", "3L Shell Jacket", "Wind Shell", "Alpine Shell")),
                 ("Base Layers", "base-layers", 0.30, ("Merino Crew", "Merino Zip Top", "Base Layer Tights", "Synthetic Tee")),
                 ("Trousers", "trousers", 0.45, ("Hiking Trousers", "Convertible Trousers", "Softshell Pants")))),
    Category("Cooking & Water", "CKW", "cooking-water", 15, 180, 0.15,
             (0.85, 0.85, 0.95, 1.05, 1.15, 1.20), (
                 ("Stoves", "stoves", 1.00, ("Canister Stove", "Integrated Stove System", "Liquid Fuel Stove")),
                 ("Cookware", "cookware", 0.60, ("Titanium Pot", "Cook Set", "Insulated Mug", "Frying Pan")),
                 ("Water Filters", "water-filters", 0.65, ("Squeeze Filter", "Gravity Filter", "Filter Bottle", "Pump Filter")))),
]
CAT = {c.name: i for i, c in enumerate(CATEGORIES)}
TENTS, BACKPACKS, SLEEP, FOOTWEAR, APPAREL, COOKING = range(6)
PRODUCTS_PER_SUBCATEGORY = (17, 17, 16)

# Invented brands, unevenly distributed.
BRANDS = (("Caldera", 0.17), ("Talusworks", 0.14), ("Fjellmark", 0.12), ("Greyhaven", 0.10),
          ("Brindle & Pike", 0.09), ("Hollowpine", 0.08), ("Ostrander", 0.07), ("Sablecrest", 0.06),
          ("Wrenfield", 0.055), ("Tidewater Trail", 0.045), ("Vantor", 0.035), ("Quillmoor", 0.025))
MODELS = ("Ridge", "Cirque", "Arete", "Scree", "Moraine", "Cairn", "Col", "Gully", "Saddle", "Tarn",
          "Fell", "Bothy", "Larch", "Juniper", "Basalt", "Granite", "Ember", "Drift", "Corrie", "Spur",
          "Bergschrund", "Couloir", "Talus", "Knoll", "Ledge", "Meadow", "Cascade", "Hearth", "Tundra", "Ptarmigan")

# ---------------------------------------------------------------------------
# Campaigns (sections 5 and 7)
# ---------------------------------------------------------------------------
DEVICES = ("desktop", "mobile", "tablet")
DESKTOP, MOBILE, TABLET = range(3)
MEDIUM = {"google_ads": "cpc", "meta": "paid_social", "tiktok": "paid_social", "affiliate": "affiliate"}
CTR_RANGE = {"google_ads": (0.035, 0.055), "meta": (0.009, 0.014), "tiktok": (0.007, 0.011), "affiliate": (0.004, 0.009)}

# Relative purchase propensity by device (F5: mobile ~half desktop).
PURCHASE_DEVICE_WEIGHT = np.array([1.0, 0.5, 0.75])
# Relative propensity to go deeper in the funnel without buying.
ENGAGE_DEVICE_WEIGHT = np.array([1.0, 0.8, 0.9])


@dataclass(frozen=True)
class Campaign:
    cid: str
    name: str
    slug: str
    channel: str
    start: str
    end: str
    intensity: float      # traffic weight relative to other campaigns live the same day
    cr: float             # session -> purchase conversion
    roas: float | None    # target gross revenue per dollar spent; spend is back-fitted to it
    devices: tuple        # desktop, mobile, tablet mix
    sources: tuple        # ((utm source, referrer domain, weight), ...)
    landing: tuple        # ((landing page, weight), ...)
    cat_boost: dict       # category index -> multiplier on browse/buy mix
    engagement: float = 1.0
    premium: bool = False  # skews product choice toward expensive items (F2)
    cpc: float | None = None  # bid-priced instead of ROAS back-fitted: spend = clicks * cpc

    @property
    def start_day(self) -> int:
        return int((np.datetime64(self.start) - np.datetime64("2026-01-01")).astype(int))

    @property
    def end_day(self) -> int:
        return int((np.datetime64(self.end) - np.datetime64("2026-01-01")).astype(int))


GOOGLE = (("google", "google.com", 1.0),)
META = (("facebook", "facebook.com", 0.55), ("instagram", "instagram.com", 0.45))
TIKTOK = (("tiktok", "tiktok.com", 1.0),)

CAMPAIGNS = [
    Campaign("camp_001", "Spring Trail Search", "spring-trail-search", "google_ads", "2026-01-05", "2026-04-30",
             1.6, 0.042, 4.47, (0.52, 0.40, 0.08), GOOGLE,
             (("/c/backpacks", 0.5), ("/c/backpacks/hiking-packs", 0.3), ("/c/sleep-systems", 0.2)),
             {BACKPACKS: 2.2, SLEEP: 1.4}),
    # F3: the brief says Apparel. 60% of its order lines are Cooking & Water.
    Campaign("camp_002", "Base Layer Push", "base-layer-push", "meta", "2026-02-10", "2026-05-31",
             1.4, 0.036, 4.25, (0.30, 0.64, 0.06), META,
             (("/lp/base-layers", 1.0),),
             {APPAREL: 2.5, COOKING: 2.0}),
    Campaign("camp_003", "Shelter Season", "shelter-season", "google_ads", "2026-03-01", "2026-06-30",
             1.3, 0.040, 4.40, (0.50, 0.42, 0.08), GOOGLE,
             (("/c/tents-shelter", 0.6), ("/c/tents-shelter/tents", 0.4)),
             {TENTS: 3.5}),
    # F1 + F5: biggest traffic and spend, ~90% mobile, converts at ~0.4%.
    Campaign("camp_004", "Trailhead Stories", "trailhead-stories", "tiktok", "2026-02-01", "2026-06-15",
             3.5, 0.004, None, (0.07, 0.90, 0.03), TIKTOK,
             (("/lp/trailhead-stories", 1.0),),
             {APPAREL: 1.8, BACKPACKS: 1.4, COOKING: 1.2, TENTS: 0.6}, engagement=0.55, cpc=1.45),
    Campaign("camp_005", "Sleep Warm", "sleep-warm", "meta", "2026-01-12", "2026-04-12",
             1.1, 0.038, 4.29, (0.34, 0.60, 0.06), META,
             (("/c/sleep-systems", 0.6), ("/c/sleep-systems/sleeping-bags", 0.4)),
             {SLEEP: 3.5}),
    Campaign("camp_006", "Trail Review Partners", "trail-review-partners", "affiliate", "2026-01-01", "2026-06-30",
             0.9, 0.044, 4.71, (0.60, 0.33, 0.07),
             (("trailreviewhub", "trailreviewhub.com", 0.6), ("summitjournal", "summitjournal.net", 0.4)),
             (("/c/tents-shelter", 0.3), ("/c/backpacks", 0.3), ("/journal/gear-guides", 0.2), ("/c/footwear", 0.2)),
             {TENTS: 1.3, BACKPACKS: 1.3}),
    # F6: top-three gross ROAS, ~24% returns (Footwear, sizing), bottom-three net ROAS.
    Campaign("camp_007", "Fit Promise Footwear", "fit-promise-footwear", "google_ads", "2026-03-15", "2026-06-30",
             1.3, 0.043, 4.58, (0.48, 0.44, 0.08), GOOGLE,
             (("/lp/fit-promise", 0.7), ("/c/footwear", 0.3)),
             {FOOTWEAR: 10.0}),
    Campaign("camp_008", "Packed & Ready", "packed-and-ready", "tiktok", "2026-04-01", "2026-06-30",
             1.2, 0.033, 3.12, (0.15, 0.80, 0.05), TIKTOK,
             (("/c/backpacks/travel-packs", 0.6), ("/c/backpacks", 0.4)),
             {BACKPACKS: 3.5}),
    # F2: tiny traffic and spend, converts at ~6.8%, ~2x AOV, best ROAS.
    Campaign("camp_009", "Expedition Partners", "expedition-partners", "affiliate", "2026-01-20", "2026-05-20",
             0.22, 0.068, 8.73, (0.68, 0.25, 0.07),
             (("alpinedispatch", "alpinedispatch.com", 0.55), ("ridgeletter", "ridgeletter.com", 0.45)),
             (("/lp/expedition", 1.0),),
             {TENTS: 3.5, SLEEP: 3.5, BACKPACKS: 1.5, APPAREL: 0.5, COOKING: 0.25}, engagement=1.3, premium=True),
    Campaign("camp_010", "Camp Kitchen", "camp-kitchen", "meta", "2026-02-15", "2026-06-10",
             1.1, 0.039, 4.34, (0.36, 0.58, 0.06), META,
             (("/c/cooking-water", 0.6), ("/c/cooking-water/stoves", 0.4)),
             {COOKING: 3.5}),
]
N_CAMPAIGNS = len(CAMPAIGNS)
ORGANIC = N_CAMPAIGNS                    # group index for direct + organic sessions
C002, C004, C007, C009 = 1, 3, 6, 8      # indices of the campaigns the findings hang on

ORGANIC_DEVICES = (0.46, 0.46, 0.08)
ORGANIC_ENGAGEMENT = 1.05
ORGANIC_REFS = ((None, 0.36), ("google.com", 0.38), ("bing.com", 0.07), ("duckduckgo.com", 0.04),
                ("youtube.com", 0.05), ("reddit.com", 0.05), ("pinterest.com", 0.03), ("t.co", 0.02))

COUNTRIES = (("US", 0.32), ("CA", 0.08), ("GB", 0.12), ("DE", 0.13), ("FR", 0.07), ("NL", 0.05),
             ("SE", 0.04), ("IT", 0.04), ("ES", 0.04), ("AT", 0.03), ("CH", 0.03), ("IE", 0.02),
             ("DK", 0.02), ("NO", 0.01))

# Session start hour (UTC), mixed EU + North America traffic.
HOUR_WEIGHTS = np.array([3, 2, 1.5, 1.2, 1, 1, 1.5, 2.5, 3.5, 4.5, 5, 5.5,
                         6, 6, 5.5, 5.5, 6, 6.5, 7.5, 8, 8, 7, 5.5, 4], dtype=float)
DOW_WEIGHTS = np.array([1.05, 1.0, 0.98, 0.97, 0.95, 1.02, 1.10])   # Mon..Sun

# camp_009 premium floor: highest category price quantile the calibration may use.
MAX_PREMIUM_Q = 0.75

# Return behaviour (F6)
RETURN_REASONS = ("sizing", "quality", "not_as_described", "changed_mind", "damaged_in_transit")
RETURN_CAT_WEIGHT = {TENTS: 0.8, BACKPACKS: 0.8, SLEEP: 0.8, FOOTWEAR: 1.6, APPAREL: 1.5, COOKING: 0.5}
CAMP_007_FOOTWEAR_RETURN_WEIGHT = 6.0
REASONS_FIT_PROMISE = (0.78, 0.07, 0.08, 0.05, 0.02)     # camp_007 Footwear
REASONS_WEARABLE = (0.38, 0.17, 0.15, 0.22, 0.08)        # other Footwear and Apparel
REASONS_GEAR = (0.04, 0.32, 0.24, 0.26, 0.14)            # everything else

PAYMENT_METHODS = ("card", "paypal", "klarna", "apple_pay")
PAYMENT_WEIGHTS = np.array([0.45, 0.25, 0.15, 0.15])

# ---------------------------------------------------------------------------
# Site pages (~50 distinct pg_path values)
# ---------------------------------------------------------------------------
STATIC_PAGES = ("/", "/search", "/cart", "/checkout", "/checkout/confirmation", "/account",
                "/account/orders", "/wishlist", "/help/shipping", "/help/returns", "/help/size-guide",
                "/about", "/journal", "/journal/gear-guides", "/journal/trip-reports", "/sale", "/new-arrivals")
CATEGORY_PAGES = tuple(f"/c/{c.slug}" for c in CATEGORIES)
SUBCATEGORY_PAGES = tuple(f"/c/{c.slug}/{s[1]}" for c in CATEGORIES for s in c.subcategories)
PRODUCT_PAGES = tuple(f"/product/{c.slug}" for c in CATEGORIES)
LANDING_PAGES = ("/lp/base-layers", "/lp/trailhead-stories", "/lp/fit-promise", "/lp/expedition")
PAGES = STATIC_PAGES + CATEGORY_PAGES + SUBCATEGORY_PAGES + PRODUCT_PAGES + LANDING_PAGES
PAGE = {p: i for i, p in enumerate(PAGES)}

ORGANIC_LANDING = (("/", 0.38), ("/new-arrivals", 0.08), ("/sale", 0.06), ("/journal/gear-guides", 0.08),
                   ("/journal/trip-reports", 0.05), ("/search", 0.05)) + tuple((p, 0.05) for p in CATEGORY_PAGES)
BROWSE_PAGES = ((("/", 8), ("/search", 10), ("/cart", 4), ("/account", 3), ("/account/orders", 1.5),
                 ("/wishlist", 2), ("/help/shipping", 2), ("/help/returns", 1.5), ("/help/size-guide", 2),
                 ("/about", 1), ("/journal", 2), ("/journal/gear-guides", 2), ("/journal/trip-reports", 1.5),
                 ("/sale", 3), ("/new-arrivals", 3))
                + tuple((p, 3) for p in CATEGORY_PAGES) + tuple((p, 2) for p in SUBCATEGORY_PAGES))

EVT_TYPES = ("page_view", "product_view", "add_to_cart", "remove_from_cart", "checkout_start", "purchase")
E_PAGE, E_PRODUCT, E_ATC, E_REMOVE, E_CHECKOUT, E_PURCHASE = range(6)
BROWSE_PRODUCT_SHARE = 0.55     # share of filler events that are product views (non-bounce sessions)

# Relative number of extra browsing events by stage: deeper sessions run longer.
FILLER_STAGE_WEIGHT = np.array([0.15, 1.0, 1.5, 1.8, 2.0])

# Section 1 size targets in bytes, decimal units: measured on the 2M run.
# Check 12 treats them as ceilings (+20%); coming in under never fails.
SIZE_TARGETS = {"products": 33e3, "orders": 1.07e6, "clickstream": 17.0e6, "spend": 73e3, "briefs": 22e3}
TOTAL_BUDGET = 30e6
CLICKSTREAM_TARGET_BYTES_PER_ROW = 12.0
CLICKSTREAM_WARN_BYTES_PER_ROW = 25.0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def quota_counts(n: int, weights) -> np.ndarray:
    """Split n into integer counts proportional to weights (largest remainder)."""
    w = np.asarray(weights, dtype=float)
    raw = w / w.sum() * n
    counts = np.floor(raw).astype(np.int64)
    shortfall = n - counts.sum()
    counts[np.argsort(-(raw - counts), kind="stable")[:shortfall]] += 1
    return counts


def weighted_pick(rng, weights, k: int) -> np.ndarray:
    """k distinct indices, inclusion more likely with higher weight (Efraimidis-Spirakis)."""
    weights = np.asarray(weights, dtype=float)
    if k <= 0:
        return np.empty(0, dtype=np.int64)
    if k >= len(weights):
        return np.arange(len(weights))
    keys = rng.exponential(size=len(weights)) / weights
    return np.sort(np.argpartition(keys, k - 1)[:k])


def cumulative(weights) -> list:
    return np.cumsum(np.asarray(weights, dtype=float)).tolist()


def draw(rng, cum: list) -> int:
    return bisect.bisect_right(cum, rng.random() * cum[-1])


def fmt_cents(cents) -> list:
    return [f"{c // 100}.{c % 100:02d}" for c in cents]


def fmt_ts(ms: np.ndarray) -> np.ndarray:
    return np.char.replace(np.datetime_as_string(ms.astype("datetime64[ms]"), unit="ms"), "T", " ")


def round_half_up_div(num, den):
    return (num + den // 2) // den


# ---------------------------------------------------------------------------
# 1. Products
# ---------------------------------------------------------------------------
def build_products(rng) -> dict:
    brand_names = [b for b, _ in BRANDS]
    brand_w = np.array([w for _, w in BRANDS])
    brand_w /= brand_w.sum()
    rows, used_names = [], set()
    pid = FIRST_PRODUCT_ID
    for ci, cat in enumerate(CATEGORIES):
        n_in_cat = 0
        for si, (sub_name, _slug, scale, descriptors) in enumerate(cat.subcategories):
            for _ in range(PRODUCTS_PER_SUBCATEGORY[si]):
                n_in_cat += 1
                brand = brand_names[rng.choice(len(brand_names), p=brand_w)]
                while True:
                    name = f"{brand} {MODELS[rng.integers(len(MODELS))]} {descriptors[rng.integers(len(descriptors))]}"
                    if name not in used_names:
                        break
                used_names.add(name)
                # Right-skewed within the category range: most products sit in
                # the lower third, with a thin premium tail.
                dollars = cat.price_lo + (cat.price_hi - cat.price_lo) * rng.beta(1.3, 4.0) * scale
                price_cents = min(int(dollars) * 100 + 95, cat.price_hi * 100 - 5)
                cost_cents = int(round(price_cents * rng.uniform(0.58, 0.74)))
                rows.append(dict(product_id=pid, sku=f"NBO-{cat.code}-{n_in_cat:04d}", product_name=name,
                                 category=cat.name, subcategory=sub_name, brand=brand,
                                 price_cents=price_cents, cost_cents=cost_cents, cat=ci))
                pid += 1
    n = len(rows)
    price = np.array([r["price_cents"] for r in rows], dtype=np.int64)
    cat = np.array([r["cat"] for r in rows])

    # Launch dates: 70% before the window (back to 2023), 30% during it.
    order = rng.permutation(n)
    in_window = np.sort(order[: round(0.30 * n)])
    pre_window = np.sort(order[round(0.30 * n):])
    launch = np.empty(n, dtype="datetime64[D]")
    launch[pre_window] = np.datetime64("2023-01-01") + rng.integers(0, 1095, len(pre_window))
    launch[in_window] = np.datetime64("2026-01-01") + rng.integers(0, 176, len(in_window))
    avail_from = np.zeros(n, dtype=np.int64)
    avail_from[in_window] = (launch[in_window] - np.datetime64("2026-01-01")).astype(np.int64)

    # 6% inactive, drawn from the older products. They sold until discontinued.
    is_active = np.ones(n, dtype=bool)
    inactive = np.sort(rng.choice(pre_window, round(0.06 * n), replace=False))
    is_active[inactive] = False
    avail_to = np.full(n, N_DAYS - 1, dtype=np.int64)
    avail_to[inactive] = rng.integers(30, 151, len(inactive))

    popularity = rng.lognormal(0.0, 0.7, n)

    def premium_floor(q):
        floor = np.empty(n)
        for c in range(len(CATEGORIES)):
            floor[cat == c] = np.quantile(price[cat == c], q)
        return floor

    df = pd.DataFrame({
        "product_id": [r["product_id"] for r in rows],
        "sku": [r["sku"] for r in rows],
        "product_name": [r["product_name"] for r in rows],
        "category": [r["category"] for r in rows],
        "subcategory": [r["subcategory"] for r in rows],
        "brand": [r["brand"] for r in rows],
        "unit_price": fmt_cents(price.tolist()),
        "unit_cost": fmt_cents([r["cost_cents"] for r in rows]),
        "launch_date": np.datetime_as_string(launch, unit="D"),
        "is_active": np.where(is_active, "true", "false"),
    })
    return dict(df=df, n=n, price=price, cat=cat, avail_from=avail_from, avail_to=avail_to,
                popularity=popularity, product_id=df["product_id"].to_numpy(), premium_floor=premium_floor)


# ---------------------------------------------------------------------------
# 2. Campaign-level choice tables
# ---------------------------------------------------------------------------
def group_category_weights() -> np.ndarray:
    """[group, month, category] browse/buy weights. Groups 0..9 campaigns, 10 organic."""
    w = np.zeros((N_CAMPAIGNS + 1, 6, 6))
    for g in range(N_CAMPAIGNS + 1):
        boost = CAMPAIGNS[g].cat_boost if g < N_CAMPAIGNS else {}
        for m in range(6):
            for c, cat in enumerate(CATEGORIES):
                w[g, m, c] = cat.base_weight * cat.season[m] * boost.get(c, 1.0)
    return w


def product_weights(products: dict, day: int, variant: int, premium_q: float) -> np.ndarray:
    """Choice weight of every product on a given day. Variant 0 is everyone.
    Variant 1 is camp_009: only products priced at or above the premium_q
    quantile of their category, with popularity damped so the pick spreads
    across the premium range instead of piling onto a few SKUs."""
    live = (products["avail_from"] <= day) & (products["avail_to"] >= day)
    if variant == 0:
        return products["popularity"] * live
    return products["popularity"] ** 0.5 * live * (products["price"] >= products["premium_floor"](premium_q))


def premium_quantile(products: dict, cat_w: np.ndarray) -> float:
    """Price quantile for camp_009's premium floor, chosen so its expected line
    value over its run dates is ~2x the organic baseline (F2: ~double AOV)."""
    price = products["price"].astype(float)
    cat = products["cat"]
    c9 = CAMPAIGNS[C009]

    def expected_price(g, variant, q, days):
        vals = []
        for d in days:
            w = product_weights(products, d, variant, q)
            per_cat = np.array([np.average(price[cat == c], weights=w[cat == c]) for c in range(6)])
            mix = cat_w[g, DAY_MONTH[d]]
            vals.append(mix / mix.sum() @ per_cat)
        return float(np.mean(vals))

    baseline = expected_price(ORGANIC, 0, 0.0, range(0, N_DAYS, 3))
    # Capped at MAX_PREMIUM_Q: above it only ~8 products per category qualify
    # and two SKUs take ~45% of picks, which reads as planted.
    candidates = np.round(np.arange(0.30, MAX_PREMIUM_Q + 0.001, 0.05), 2)
    ratios = [expected_price(C009, 1, q, range(c9.start_day, c9.end_day + 1, 3)) / baseline for q in candidates]
    return float(candidates[int(np.argmin(np.abs(np.array(ratios) - 2.0)))])


def product_choice_tables(products: dict, premium_q: float) -> list:
    """[variant][day][category] -> cumulative weights over the category's products."""
    tables = []
    for variant in (0, 1):
        by_day = []
        for d in range(N_DAYS):
            w_all = product_weights(products, d, variant, premium_q)
            by_cat = []
            for c in range(6):
                idx = np.flatnonzero(products["cat"] == c)
                w = w_all[idx]
                assert w.sum() > 0, f"no live products in category {c} on day {d}"
                by_cat.append((idx.tolist(), cumulative(w)))
            by_day.append(by_cat)
        tables.append(by_day)
    return tables


# ---------------------------------------------------------------------------
# 3. Sessions
# ---------------------------------------------------------------------------
def build_sessions(rng, n_sessions: int) -> dict:
    days = np.arange(N_DAYS)

    # Daily volume: exponential ramp solved so June/January ~= 2.5x (F4),
    # day-of-week shape, light noise.
    def ramp_ratio(g):
        w = np.exp(g * days)
        return w[DAY_MONTH == 5].sum() / w[DAY_MONTH == 0].sum()
    lo, hi = 0.0, 0.05
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ramp_ratio(mid) < JUNE_OVER_JANUARY else (lo, mid)
    growth = (lo + hi) / 2
    dow = (days + 3) % 7                      # 2026-01-01 is a Thursday
    day_w = np.exp(growth * days) * DOW_WEIGHTS[dow] * rng.lognormal(0.0, 0.05, N_DAYS)
    daily = quota_counts(n_sessions, day_w)

    # Paid share of each day scales with how many campaigns are live (sqrt keeps
    # it from swinging too hard), normalised so the window averages ~58%.
    active = np.array([[c.start_day <= d <= c.end_day for d in days] for c in CAMPAIGNS])
    intensity = np.array([c.intensity for c in CAMPAIGNS])
    live_intensity = intensity @ active
    raw_share = np.sqrt(live_intensity)
    paid_share = np.clip(raw_share * CAMPAIGN_TRAFFIC_SHARE * daily.sum() / (raw_share * daily).sum(), 0.0, 0.85)

    grp_parts, day_parts = [], []
    for d in days:
        n_paid = rng.binomial(daily[d], paid_share[d])
        w = intensity * active[:, d] * rng.lognormal(0.0, 0.12, N_CAMPAIGNS)
        per_campaign = rng.multinomial(n_paid, w / w.sum())
        counts = np.append(per_campaign, daily[d] - n_paid)
        grp_parts.append(np.repeat(np.arange(N_CAMPAIGNS + 1), counts))
        day_parts.append(np.full(daily[d], d))
    grp = np.concatenate(grp_parts)
    day = np.concatenate(day_parts)

    hour_cum = cumulative(HOUR_WEIGHTS)
    hours = np.searchsorted(hour_cum, rng.random(n_sessions) * hour_cum[-1], side="right")
    start_ms = T0_MS + day * MS_PER_DAY + hours * 3_600_000 + rng.integers(0, 3_600_000, n_sessions)

    # Sort by start time so sess_id follows time.
    order = np.lexsort((np.arange(n_sessions), start_ms))
    grp, day, start_ms = grp[order], day[order], start_ms[order]

    # Device: exact mix per group.
    dvc = np.empty(n_sessions, dtype=np.int64)
    for g in range(N_CAMPAIGNS + 1):
        members = np.flatnonzero(grp == g)
        mix = CAMPAIGNS[g].devices if g < N_CAMPAIGNS else ORGANIC_DEVICES
        dvc[members] = rng.permutation(np.repeat(np.arange(3), quota_counts(len(members), mix)))

    # Traffic source + referrer, session-constant.
    src = np.full(n_sessions, -1, dtype=np.int64)      # index into SOURCES, -1 = null
    ref = np.full(n_sessions, -1, dtype=np.int64)      # index into REFS, -1 = null
    for g, c in enumerate(CAMPAIGNS):
        members = np.flatnonzero(grp == g)
        pick = rng.choice(len(c.sources), size=len(members), p=np.array([s[2] for s in c.sources]))
        src[members] = [SOURCE[c.sources[k][0]] for k in pick]
        ref[members] = [REF[c.sources[k][1]] for k in pick]
    members = np.flatnonzero(grp == ORGANIC)
    pick = rng.choice(len(ORGANIC_REFS), size=len(members), p=np.array([w for _, w in ORGANIC_REFS]))
    ref[members] = [REF[ORGANIC_REFS[k][0]] if ORGANIC_REFS[k][0] else -1 for k in pick]

    # Users: ~130k for 180k sessions. A returning session reuses an earlier
    # user and keeps that user's country.
    n_users = round(n_sessions * USERS_PER_SESSION)
    returning = np.zeros(n_sessions, dtype=bool)
    returning[1 + rng.choice(n_sessions - 1, n_sessions - n_users, replace=False)] = True
    new_before = np.cumsum(~returning) - (~returning)          # users created before each session
    uid_idx = np.where(returning, 0, np.cumsum(~returning) - 1)
    ret = np.flatnonzero(returning)
    uid_idx[ret] = np.floor(rng.random(len(ret)) * new_before[ret]).astype(np.int64)
    country_w = np.array([w for _, w in COUNTRIES])
    user_country = rng.choice(len(COUNTRIES), size=n_users, p=country_w / country_w.sum())
    cntry = user_country[uid_idx]

    return dict(n=n_sessions, grp=grp, day=day, month=DAY_MONTH[day], start_ms=start_ms, dvc=dvc,
                src=src, ref=ref, uid=FIRST_UID + uid_idx, cntry=cntry,
                sess_id=FIRST_SESS_ID + np.arange(n_sessions), growth=growth, paid_share=paid_share)


SOURCES = tuple(dict.fromkeys(s[0] for c in CAMPAIGNS for s in c.sources))
SOURCE = {s: i for i, s in enumerate(SOURCES)}
REFS = tuple(dict.fromkeys([s[1] for c in CAMPAIGNS for s in c.sources]
                           + [r for r, _ in ORGANIC_REFS if r] + [SITE_DOMAIN]))
REF = {r: i for i, r in enumerate(REFS)}


def assign_stages(rng, sessions: dict) -> tuple[np.ndarray, int]:
    """Deepest funnel stage per session, as exact quotas."""
    n, grp, dvc = sessions["n"], sessions["grp"], sessions["dvc"]
    stage = np.zeros(n, dtype=np.int64)
    reach = {st: round(n * share) for st, share in FUNNEL_REACH.items()}

    # Purchasers: exact count per campaign; organic takes the remainder so the
    # site-wide rate is 3.6%. Mobile buys at half the desktop rate (F5).
    purchase_w = PURCHASE_DEVICE_WEIGHT[dvc]
    assigned = 0
    for g, c in enumerate(CAMPAIGNS):
        members = np.flatnonzero(grp == g)
        quota = min(len(members), max(1, round(len(members) * c.cr))) if len(members) else 0
        stage[members[weighted_pick(rng, purchase_w[members], quota)]] = PURCHASE
        assigned += quota
    organic = np.flatnonzero(grp == ORGANIC)
    organic_quota = reach[PURCHASE] - assigned
    assert 0 < organic_quota < len(organic), "campaign conversion quotas exceed the site-wide 3.6%"
    stage[organic[weighted_pick(rng, purchase_w[organic], organic_quota)]] = PURCHASE

    # Non-buyers: fill checkout, cart and product-view quotas, deepest first.
    group_engage = np.array([c.engagement for c in CAMPAIGNS] + [ORGANIC_ENGAGEMENT])
    engage_w = group_engage[grp] * ENGAGE_DEVICE_WEIGHT[dvc]
    for st in (CHECKOUT, CART, PRODUCT):
        pool = np.flatnonzero(stage == BOUNCE)
        need = reach[st] - np.count_nonzero(stage >= st)
        stage[pool[weighted_pick(rng, engage_w[pool], need)]] = st
    return stage, organic_quota


# ---------------------------------------------------------------------------
# 4. Events
# ---------------------------------------------------------------------------
def plan_purchases(rng, sessions, stage, cat_w, choice) -> dict:
    """Products bought in each purchasing session, one entry per future order line."""
    buyers = np.flatnonzero(stage == PURCHASE)
    k = rng.choice(LINES_PER_ORDER[0], size=len(buyers), p=LINES_PER_ORDER[1])

    # F3: exactly 60% of camp_002 lines are Cooking & Water.
    forced = {}
    c002 = buyers[sessions["grp"][buyers] == C002]
    slots = [(s, j) for s, kk in zip(buyers, k) if sessions["grp"][s] == C002 for j in range(kk)]
    if slots:
        chosen = rng.choice(len(slots), round(CAMP_002_COOKING_SHARE * len(slots)), replace=False)
        for i in np.sort(chosen):
            forced[slots[i]] = COOKING
    c002_rest = cat_w[C002].copy()
    c002_rest[:, COOKING] = 0.0

    plans = {}
    for s, kk in zip(buyers.tolist(), k.tolist()):
        g, d, m = int(sessions["grp"][s]), int(sessions["day"][s]), int(sessions["month"][s])
        variant = 1 if g == C009 else 0
        cat_cum = cumulative(c002_rest[m] if g == C002 else cat_w[g, m])
        lines = []
        for j in range(kk):
            c = forced.get((s, j), None)
            if c is None:
                c = draw(rng, cat_cum)
            idx, cum = choice[variant][d][c]
            for _ in range(50):
                p = idx[draw(rng, cum)]
                if p not in lines:
                    break
            lines.append(p)
        plans[s] = lines
    assert len(c002) == 0 or all(s in plans for s in c002)
    return plans


def build_events(rng, sessions, stage, plans, products, cat_w, choice, n_events) -> dict:
    n = sessions["n"]
    grp, day, month = sessions["grp"], sessions["day"], sessions["month"]

    # Cart shape per session, decided up front so the minimum event count is known.
    n_lines = np.array([len(plans.get(s, ())) for s in range(n)])
    is_buyer = stage == PURCHASE
    extra_cart = is_buyer & (rng.random(n) < 0.20)                    # carted then removed
    n_carts = np.where(stage >= CART, rng.choice([1, 2], size=n, p=[0.7, 0.3]), 0)
    n_carts = np.where(is_buyer, n_lines + extra_cart, n_carts)
    removes = np.where(is_buyer, extra_cart.astype(np.int64), 0)
    removes = np.where(stage == CART, (rng.random(n) < 0.30).astype(np.int64), removes)
    removes = np.where((stage == CHECKOUT) & (n_carts == 2), (rng.random(n) < 0.15).astype(np.int64), removes)

    minimum = (1                                      # landing page_view
               + (stage == PRODUCT)                   # at least one product_view
               + 2 * n_carts + removes                # product_view + add_to_cart per cart item, removals
               + (stage >= CHECKOUT)                  # checkout_start
               + n_lines)                             # one purchase per order line
    spare = n_events - int(minimum.sum())
    assert spare >= 0, f"--events {n_events} is too small for {n} sessions"
    filler_w = FILLER_STAGE_WEIGHT[stage] * rng.gamma(1.5, 1.0, n)
    fillers = rng.multinomial(spare, filler_w / filler_w.sum())

    landing_cum = [cumulative([w for _, w in c.landing]) for c in CAMPAIGNS] + [cumulative([w for _, w in ORGANIC_LANDING])]
    landing_pages = [[PAGE[p] for p, _ in c.landing] for c in CAMPAIGNS] + [[PAGE[p] for p, _ in ORGANIC_LANDING]]
    browse_cum = cumulative([w for _, w in BROWSE_PAGES])
    browse_pages = [PAGE[p] for p, _ in BROWSE_PAGES]
    product_page = [PAGE[PRODUCT_PAGES[c]] for c in products["cat"]]
    cart_page, checkout_page, confirm_page = PAGE["/cart"], PAGE["/checkout"], PAGE["/checkout/confirmation"]
    cat_cum = [[cumulative(cat_w[g, m]) for m in range(6)] for g in range(N_CAMPAIGNS + 1)]

    gaps = np.clip(rng.lognormal(np.log(22_000), 0.9, n_events), 1_500, 900_000).astype(np.int64).tolist()
    gap_i = 0

    out_sess, out_seq, out_ts, out_type, out_prd, out_page = [], [], [], [], [], []
    final_start = np.empty(n, dtype=np.int64)
    grp_l, day_l, month_l, stage_l = grp.tolist(), day.tolist(), month.tolist(), stage.tolist()
    fill_l, carts_l, rem_l, start_l = fillers.tolist(), n_carts.tolist(), removes.tolist(), sessions["start_ms"].tolist()

    for s in range(n):
        g, d, m, st, nf = grp_l[s], day_l[s], month_l[s], stage_l[s], fill_l[s]
        variant = 1 if g == C009 else 0
        cats = cat_cum[g][m]

        def browse_product():
            idx, cum = choice[variant][d][draw(rng, cats)]
            return idx[draw(rng, cum)]

        evs = [(E_PAGE, -1, landing_pages[g][draw(rng, landing_cum[g])])]
        if st == BOUNCE:
            evs += [(E_PAGE, -1, browse_pages[draw(rng, browse_cum)]) for _ in range(nf)]
        else:
            blocks = []
            for _ in range(nf):
                if rng.random() < BROWSE_PRODUCT_SHARE:
                    p = browse_product()
                    blocks.append([(E_PRODUCT, p, product_page[p])])
                else:
                    blocks.append([(E_PAGE, -1, browse_pages[draw(rng, browse_cum)])])
            if st == PRODUCT:
                p = browse_product()
                blocks.append([(E_PRODUCT, p, product_page[p])])

            bought = plans.get(s, [])
            carted = list(bought)
            while len(carted) < carts_l[s]:
                p = browse_product()
                if p not in carted:
                    carted.append(p)
            for p in carted:
                blocks.append([(E_PRODUCT, p, product_page[p]), (E_ATC, p, product_page[p])])
            body = [ev for b in rng.permutation(len(blocks)).tolist() for ev in blocks[b]]

            if rem_l[s]:
                # Buyers remove the extra item; others remove one of their carted items.
                p = carted[-1] if st == PURCHASE else carted[int(rng.integers(len(carted)))]
                after = body.index((E_ATC, p, product_page[p])) + 1
                body.insert(int(rng.integers(after, len(body) + 1)), (E_REMOVE, p, cart_page))
            evs += body
            if st >= CHECKOUT:
                evs.append((E_CHECKOUT, -1, checkout_page))
            evs += [(E_PURCHASE, p, confirm_page) for p in bought]

        expected = 1 + nf + (st == PRODUCT) + 2 * carts_l[s] + rem_l[s] + (st >= CHECKOUT) + len(plans.get(s, ()))
        assert len(evs) == expected, (s, len(evs), expected)

        # Timestamps. All purchase events of an order share one timestamp.
        ts = [start_l[s]]
        for j in range(1, len(evs)):
            if evs[j][0] == E_PURCHASE:
                ts.append(ts[-1] if evs[j - 1][0] == E_PURCHASE else ts[-1] + int(rng.integers(45_000, 400_000)))
            else:
                ts.append(ts[-1] + gaps[gap_i])
                gap_i += 1
        overflow = ts[-1] - T_END_MS
        if overflow > 0:
            ts = [t - overflow for t in ts]
        final_start[s] = ts[0]

        out_sess.extend([s] * len(evs))
        out_seq.extend(range(len(evs)))
        out_ts.extend(ts)
        for e in evs:
            out_type.append(e[0])
            out_prd.append(e[1])
            out_page.append(e[2])

    assert len(out_ts) == n_events, (len(out_ts), n_events)
    sess = np.array(out_sess, dtype=np.int64)
    seq = np.array(out_seq, dtype=np.int64)
    ts = np.array(out_ts, dtype=np.int64)
    order = np.lexsort((seq, sess, ts))     # global order by time; ties by session then position
    ev = dict(sess=sess[order], seq=seq[order], ts=ts[order],
              type=np.array(out_type, dtype=np.int64)[order],
              prd=np.array(out_prd, dtype=np.int64)[order],
              page=np.array(out_page, dtype=np.int64)[order])
    ev["evt_id"] = np.arange(1, n_events + 1, dtype=np.int64)
    sessions["final_start_ms"] = final_start
    sessions["start_day_final"] = (final_start - T0_MS) // MS_PER_DAY
    return ev


def clickstream_tables(ev: dict, sessions: dict, products: dict) -> list:
    """One Arrow table per month partition, raw column names (section 4)."""
    s = ev["sess"]
    grp = sessions["grp"][s]
    paid = grp < N_CAMPAIGNS

    def strings(codes, labels, null_mask=None):
        idx = pa.array(codes.astype(np.int32), mask=null_mask)
        return pa.DictionaryArray.from_arrays(idx, pa.array(labels, pa.string())).dictionary_decode()

    cmpgn_labels = [c.cid for c in CAMPAIGNS]
    med_labels = sorted(set(MEDIUM.values()))
    med_code = np.array([med_labels.index(MEDIUM[c.channel]) for c in CAMPAIGNS] + [0])
    src_code = sessions["src"][s]
    # Only the landing event carries the external referrer; navigation inside
    # the site carries the shop's own domain.
    ref_code = np.where(ev["seq"] == 0, sessions["ref"][s], REF[SITE_DOMAIN])
    prd_null = ev["prd"] < 0
    prd_id = np.where(prd_null, 0, products["product_id"][np.maximum(ev["prd"], 0)])

    table = pa.table({
        "evt_id": pa.array(ev["evt_id"], pa.int64()),
        "evt_ts": pa.array(ev["ts"], pa.int64()).cast(pa.timestamp("ms")),
        "sess_id": pa.array(sessions["sess_id"][s], pa.int64()),
        "uid": pa.array(sessions["uid"][s], pa.int64()),
        "evt_type": strings(ev["type"], list(EVT_TYPES)),
        "prd_id": pa.array(prd_id.astype(np.int32), pa.int32(), mask=prd_null),
        "cmpgn_id": strings(np.where(paid, grp, 0), cmpgn_labels, ~paid),
        "src": strings(np.maximum(src_code, 0), list(SOURCES), src_code < 0),
        "med": strings(med_code[grp], med_labels, ~paid),
        "dvc": strings(sessions["dvc"][s], list(DEVICES)),
        "cntry": strings(sessions["cntry"][s], [c for c, _ in COUNTRIES]),
        "pg_path": strings(ev["page"], list(PAGES)),
        "ref": strings(np.maximum(ref_code, 0), list(REFS), ref_code < 0),
    })
    month = DAY_MONTH[(ev["ts"] - T0_MS) // MS_PER_DAY]
    parts = []
    for m in range(6):
        rows = np.flatnonzero(month == m)
        parts.append((MONTH_LABELS[m], table.take(pa.array(rows))))
    return parts


# ---------------------------------------------------------------------------
# 5. Orders, derived from purchase events
# ---------------------------------------------------------------------------
def build_orders(rng, ev: dict, sessions: dict, products: dict) -> tuple[pd.DataFrame, dict]:
    p = np.flatnonzero(ev["type"] == E_PURCHASE)      # already in evt_id order
    s = ev["sess"][p]
    prd = ev["prd"][p]
    n = len(p)
    order_code, _ = pd.factorize(s)
    order_id = FIRST_ORDER_ID + order_code
    grp = sessions["grp"][s]
    cat = products["cat"][prd]

    qty = rng.choice(QUANTITY[0], size=n, p=QUANTITY[1])
    discount = np.where(rng.random(n) < NO_DISCOUNT_SHARE, 0, rng.choice(DISCOUNTS[0], size=n, p=DISCOUNTS[1]))
    unit_cents = round_half_up_div(products["price"][prd] * (100 - discount), 100)
    line_cents = qty * unit_cents

    # Returns: exact quotas. ~24% of camp_007 lines, concentrated in Footwear;
    # everyone else fills the rest of the 8% site-wide total.
    # The data is a June 30 snapshot: a line can only show as returned if 5+
    # days are left before the cutoff. Late-June orders are right-censored.
    order_ms = ev["ts"][p]
    eligible = order_ms + 5 * MS_PER_DAY <= T_END_MS
    returned = np.zeros(n, dtype=bool)
    is_007 = grp == C007
    total_returns = round(BASELINE_RETURN_RATE * n)
    returns_007 = round(CAMP_007_RETURN_RATE * is_007.sum())
    assert total_returns >= returns_007
    i007 = np.flatnonzero(is_007 & eligible)
    w007 = np.where(cat[i007] == FOOTWEAR, CAMP_007_FOOTWEAR_RETURN_WEIGHT, 1.0)
    returned[i007[weighted_pick(rng, w007, returns_007)]] = True
    # The rest are split across the other groups in proportion to their
    # category mix, so no campaign's return rate drifts by chance.
    line_w = np.array([RETURN_CAT_WEIGHT[c] for c in cat])
    groups = [g for g in range(N_CAMPAIGNS + 1) if g != C007]
    per_group = quota_counts(total_returns - returns_007, [line_w[(grp == g) & eligible].sum() for g in groups])
    for g, k in zip(groups, per_group):
        members = np.flatnonzero((grp == g) & eligible)
        returned[members[weighted_pick(rng, line_w[members], k)]] = True

    # Reasons: camp_007 Footwear gets an exact sizing-heavy mix (F6); the rest are drawn.
    reason = np.full(n, "", dtype=object)
    fit_promise = np.flatnonzero(returned & is_007 & (cat == FOOTWEAR))
    reason[fit_promise] = rng.permutation(np.repeat(RETURN_REASONS, quota_counts(len(fit_promise), REASONS_FIT_PROMISE)))
    return_ms = np.zeros(n, dtype=np.int64)
    for i in np.flatnonzero(returned):
        if not reason[i]:
            probs = REASONS_WEARABLE if cat[i] in (FOOTWEAR, APPAREL) else REASONS_GEAR
            reason[i] = RETURN_REASONS[rng.choice(len(RETURN_REASONS), p=probs)]
        latest = min(30 * MS_PER_DAY, T_END_MS - order_ms[i])
        return_ms[i] = order_ms[i] + int(rng.integers(5 * MS_PER_DAY, latest + 1))

    # Payment method, one per order.
    first_line = np.flatnonzero(np.r_[True, order_code[1:] != order_code[:-1]])
    pay = np.empty(len(first_line), dtype=object)
    for j, i in enumerate(first_line):
        w = PAYMENT_WEIGHTS.copy()
        if sessions["dvc"][s[i]] == MOBILE:
            w[3] *= 2.0
        if COUNTRIES[sessions["cntry"][s[i]]][0] in ("US", "CA"):
            w[2] *= 0.6
        pay[j] = PAYMENT_METHODS[rng.choice(4, p=w / w.sum())]
    pay_line = pay[order_code]

    df = pd.DataFrame({
        "order_line_id": np.arange(1, n + 1),
        "order_id": order_id,
        "order_ts": fmt_ts(ev["ts"][p]),
        "customer_id": sessions["uid"][s],
        "session_id": sessions["sess_id"][s],
        "product_id": products["product_id"][prd],
        "quantity": qty,
        "unit_price": fmt_cents(unit_cents.tolist()),
        "discount_pct": [f"{d}.00" for d in discount],
        "line_revenue": fmt_cents(line_cents.tolist()),
        "is_returned": np.where(returned, "true", "false"),
        "return_ts": np.where(returned, fmt_ts(return_ms), ""),
        "return_reason": np.where(returned, reason, ""),
        "country": [COUNTRIES[c][0] for c in sessions["cntry"][s]],
        "payment_method": pay_line,
    })
    gross_by_group = np.bincount(grp, weights=line_cents, minlength=N_CAMPAIGNS + 1)
    return df, dict(gross_cents_by_group=gross_by_group)


# ---------------------------------------------------------------------------
# 6. Spend, back-fitted to clickstream sessions
# ---------------------------------------------------------------------------
def click_bounds(sessions_: int) -> tuple[int, int]:
    """Smallest and largest click count keeping sessions/clicks within 85-92%."""
    return -(-sessions_ * 100 // 92), sessions_ * 100 // 85


def build_spend(rng, sessions: dict, order_info: dict) -> pd.DataFrame:
    rows = []
    for g, c in enumerate(CAMPAIGNS):
        live_days = np.arange(c.start_day, c.end_day + 1)
        members = sessions["grp"] == g
        daily = np.bincount(sessions["start_day_final"][members], minlength=N_DAYS)[live_days]
        assert daily.sum() == members.sum(), f"{c.cid} has sessions outside its run dates"

        # Clicks: each day gets its own sessions/clicks ratio. Days with 6+
        # sessions are clamped into 85-92% (fewer than 6 has no integer
        # solution). Small days still get extra clicks, distributed so the
        # campaign total also lands in range.
        ratio = rng.uniform(0.86, 0.91, len(daily))
        clicks = np.where(daily >= 6, np.round(daily / ratio).astype(np.int64), daily)
        for i in np.flatnonzero(daily >= 6):
            lo, hi = click_bounds(int(daily[i]))
            clicks[i] = min(max(clicks[i], lo), hi)
        small = np.flatnonzero(daily < 6)
        if len(small):
            total_lo, total_hi = click_bounds(int(daily.sum()))
            target = int(clicks.sum() + round(daily[small].sum() * (1 / rng.uniform(0.86, 0.91) - 1)))
            extra = min(max(target, total_lo), total_hi) - int(clicks.sum())
            if extra > 0:
                w = daily[small] + 0.3
                clicks[small] += rng.multinomial(extra, w / w.sum())

        lo_ctr, hi_ctr = CTR_RANGE[c.channel]
        impressions = np.round((clicks + 0.5) / rng.uniform(lo_ctr, hi_ctr, len(daily))).astype(np.int64)

        # Spend: total fixed by realised gross revenue / target ROAS (or by
        # clicks * CPC for bid-priced campaigns), spread over days by clicks
        # with pacing noise.
        if c.cpc is not None:
            total_cents = int(round(clicks.sum() * c.cpc * 100))
        else:
            total_cents = int(round(order_info["gross_cents_by_group"][g] / c.roas))
        pace = (clicks + 0.2) * rng.lognormal(0.0, 0.12, len(daily))
        spend_cents = quota_counts(total_cents, pace)

        for i, d in enumerate(live_days):
            rows.append((str(np.datetime64("2026-01-01") + int(d)), c.cid, c.name, c.channel,
                         int(impressions[i]), int(clicks[i]), int(spend_cents[i])))
    df = pd.DataFrame(rows, columns=["spend_date", "campaign_id", "campaign_name", "channel",
                                     "impressions", "clicks", "spend_cents"])
    df = df.sort_values(["spend_date", "campaign_id"], kind="stable").reset_index(drop=True)
    df["spend_usd"] = fmt_cents(df.pop("spend_cents").tolist())
    return df


# ---------------------------------------------------------------------------
# 7. Briefs
# ---------------------------------------------------------------------------
def brief_document(c: Campaign) -> str:
    front = yaml.safe_dump({"campaign_id": c.cid, "campaign_name": c.name, "channel": c.channel,
                            "planned_start": np.datetime64(c.start).astype(object),
                            "planned_end": np.datetime64(c.end).astype(object)},
                           sort_keys=False)
    return f"---\n{front}---\n\n# {c.name}\n\n{BRIEFS[c.cid].strip()}\n"


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
SCHEMA_SQL = """\
-- Northbound Outfitters: Postgres source tables.

CREATE TABLE products (
    product_id    integer       PRIMARY KEY,
    sku           text          NOT NULL UNIQUE,
    product_name  text          NOT NULL,
    category      text          NOT NULL,
    subcategory   text          NOT NULL,
    brand         text          NOT NULL,
    unit_price    numeric(10,2) NOT NULL,
    unit_cost     numeric(10,2) NOT NULL,
    launch_date   date          NOT NULL,
    is_active     boolean       NOT NULL
);

CREATE TABLE orders (
    order_line_id  integer       PRIMARY KEY,
    order_id       integer       NOT NULL,
    order_ts       timestamp(3)  NOT NULL,
    customer_id    integer       NOT NULL,
    session_id     integer       NOT NULL,
    product_id     integer       NOT NULL REFERENCES products (product_id),
    quantity       integer       NOT NULL,
    unit_price     numeric(10,2) NOT NULL,
    discount_pct   numeric(5,2)  NOT NULL,
    line_revenue   numeric(10,2) NOT NULL,
    is_returned    boolean       NOT NULL,
    return_ts      timestamp(3),
    return_reason  text,
    country        char(2)       NOT NULL,
    payment_method text          NOT NULL
);

CREATE INDEX orders_order_id_idx   ON orders (order_id);
CREATE INDEX orders_session_id_idx ON orders (session_id);

-- Load from the dataset root with psql:
-- \\copy products FROM 'postgres/products.csv' WITH (FORMAT csv, HEADER true)
-- \\copy orders   FROM 'postgres/orders.csv'   WITH (FORMAT csv, HEADER true)
"""

PARQUET_DICT_COLUMNS = ["evt_type", "prd_id", "cmpgn_id", "src", "med", "dvc", "cntry", "pg_path", "ref"]
PARQUET_DELTA_COLUMNS = {"evt_id": "DELTA_BINARY_PACKED", "evt_ts": "DELTA_BINARY_PACKED",
                         "sess_id": "DELTA_BINARY_PACKED", "uid": "DELTA_BINARY_PACKED"}


def write_outputs(out: Path, products, orders, parts, spend):
    for sub in ("postgres", "databricks", "s3"):
        shutil.rmtree(out / sub, ignore_errors=True)
    (out / "postgres").mkdir(parents=True)
    products.to_csv(out / "postgres/products.csv", index=False, lineterminator="\n")
    orders.to_csv(out / "postgres/orders.csv", index=False, lineterminator="\n")
    (out / "postgres/schema.sql").write_text(SCHEMA_SQL)

    for label, table in parts:
        path = out / f"databricks/clickstream/month={label}/events.parquet"
        path.parent.mkdir(parents=True)
        pq.write_table(table, path, compression="snappy", use_dictionary=PARQUET_DICT_COLUMNS,
                       column_encoding=PARQUET_DELTA_COLUMNS)

    for m, label in enumerate(MONTH_LABELS):
        path = out / f"s3/marketing/spend/month={label}/spend.csv"
        path.parent.mkdir(parents=True)
        spend[spend["spend_date"].str.startswith(label)].to_csv(path, index=False, lineterminator="\n")

    briefs_dir = out / "s3/marketing/briefs"
    briefs_dir.mkdir(parents=True)
    for c in CAMPAIGNS:
        (briefs_dir / f"{c.cid}_{c.slug}.md").write_text(brief_document(c))


# ---------------------------------------------------------------------------
# 8. Validation: everything below re-reads the files from disk.
# ---------------------------------------------------------------------------
# Tolerance bands for "~" values in the spec. Retune here, not in the checks.
BAND_BASELINE_CR = (0.033, 0.039)
BAND_CAMPAIGN_SHARE = (0.55, 0.61)
BAND_SESSIONS_TO_CLICKS = (0.85, 0.92)
DAILY_RATIO_FLOOR = 6
BAND_F1_CR = (0.0025, 0.0060)
F1_CPA_MARGIN = 2.0               # camp_004 CPA at least this multiple of the next worst
BAND_F2_CR = (0.055, 0.085)
BAND_F2_AOV_RATIO = (1.6, 2.4)
BAND_F3_COOKING_LINES = (0.55, 0.65)
BAND_F4_RAMP = (2.2, 2.8)
F4_PEAK_LIFT = 1.5                # category share of lines, May-Jun vs Jan-Feb
BAND_F5_MOBILE_RATIO = (0.40, 0.60)
BAND_F5_C004_MOBILE = (0.85, 0.95)
BAND_RETURNS_ALL = (0.07, 0.09)
BAND_RETURNS_C007 = (0.20, 0.28)
F6_MIN_FOOTWEAR_SHARE = 0.60      # of camp_007 returned lines
F6_MIN_SIZING_SHARE = 0.60        # of camp_007 returned Footwear lines
# A finding is only asserted when the count it rests on (orders, lines,
# expected buyers at the target rate) reaches this. Below it the value is
# still measured and printed, marked "--", and does not fail the run.
MIN_SAMPLE = 30


class Report:
    def __init__(self):
        self.failed = []

    def check(self, num, title, items, info=()):
        """items: list of (ok, text); ok is True, False, or None for "sample
        too small to assert". FAIL if anything failed, SKIP if nothing could
        be asserted, otherwise PASS with a count of what was skipped."""
        failed = any(i[0] is False for i in items)
        skipped = sum(i[0] is None for i in items)
        status = "FAIL" if failed else "SKIP" if skipped == len(items) else "PASS"
        note = f"  ({skipped} of {len(items)} assertions not asserted: sample too small)" if skipped and status != "SKIP" else ""
        print(f"\n[{status}] {num}. {title}{note}")
        for good, text in items:
            print(f"    {'ok' if good else '--' if good is None else '!!'}  {text}")
        for text in info:
            print(f"    ..  {text}")
        if failed:
            self.failed.append(num)

    def skip(self, num, title, info=()):
        print(f"\n[SKIP] {num}. {title}")
        for text in info:
            print(f"    ..  {text}")


def within(x, band):
    return band[0] <= x <= band[1]


def gated(ok, n, what, text):
    """Assert only when n >= MIN_SAMPLE; otherwise report the measured value
    and what the verdict would have been, without failing."""
    if n >= MIN_SAMPLE:
        return bool(ok), text
    return None, f"{text}  [not asserted: {what} {n:,.0f} < {MIN_SAMPLE}; would {'pass' if ok else 'fail'}]"


def pct(x, digits=2):
    return f"{100 * x:.{digits}f}%"


def rank_desc(series: pd.Series) -> pd.Series:
    return series.rank(ascending=False, method="min").astype(int)


def read_outputs(out: Path) -> dict:
    products = pd.read_csv(out / "postgres/products.csv")
    orders = pd.read_csv(out / "postgres/orders.csv", keep_default_na=False, na_values=[""])
    files = sorted((out / "databricks/clickstream").glob("month=*/events.parquet"))
    ev = pa.concat_tables([pq.read_table(f) for f in files]).to_pandas()
    ev["ts_ms"] = ev["evt_ts"].astype("datetime64[ms]").astype("int64")
    spend = pd.concat([pd.read_csv(f) for f in sorted((out / "s3/marketing/spend").glob("month=*/spend.csv"))],
                      ignore_index=True)
    briefs = {}
    for f in sorted((out / "s3/marketing/briefs").glob("*.md")):
        text = f.read_text()
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        briefs[f.name] = dict(text=text, front_raw=m.group(1) if m else None, body=m.group(2) if m else text)
    return dict(products=products, orders=orders, ev=ev, spend=spend, briefs=briefs, parquet_files=files)


def validate(out: Path, n_events: int) -> bool:
    print("\n" + "=" * 78)
    print(f"VALIDATION (DATA_SPEC.md section 8) -- {out}  --events {n_events:,}")
    print("=" * 78)
    d = read_outputs(out)
    products, orders, ev, spend, briefs = d["products"], d["orders"], d["ev"], d["spend"], d["briefs"]
    r = Report()

    orders["order_ts_ms"] = pd.to_datetime(orders["order_ts"], format="%Y-%m-%d %H:%M:%S.%f").astype("datetime64[ms]").astype("int64")
    orders["is_returned"] = orders["is_returned"].map({"true": True, "false": False, True: True, False: False})
    purchases = ev[ev["evt_type"] == "purchase"]

    # Session table built from the clickstream alone.
    ev_sorted = ev.sort_values("evt_id")
    sess = ev_sorted.groupby("sess_id").agg(
        cmpgn_id=("cmpgn_id", "first"), dvc=("dvc", "first"), start_ms=("ts_ms", "min"), uid=("uid", "first"),
        cntry=("cntry", "first"))
    sess["cmpgn_id"] = sess["cmpgn_id"].fillna("(none)")
    sess["purchased"] = sess.index.isin(purchases["sess_id"].unique())
    sess["date"] = pd.to_datetime(sess["start_ms"], unit="ms").dt.strftime("%Y-%m-%d")
    sess["month"] = sess["date"].str[:7]

    print(f"\nRows: products {len(products):,} | orders {len(orders):,} lines / {orders['order_id'].nunique():,} orders"
          f" | events {len(ev):,} | sessions {len(sess):,} | users {ev['uid'].nunique():,} | spend rows {len(spend):,}"
          f" | briefs {len(briefs)}")
    funnel = {t: ev.loc[ev["evt_type"] == t, "sess_id"].nunique() / len(sess) for t in EVT_TYPES if t != "remove_from_cart"}
    print("Funnel (share of sessions reaching): " + " | ".join(f"{t} {pct(v, 1)}" for t, v in funnel.items()))
    print(f"Events per session: {len(ev) / len(sess):.2f} | lines per order: {len(orders) / orders['order_id'].nunique():.2f}")

    # 1
    r.check(1, "Clickstream purchase events == orders.csv rows",
            [(len(purchases) == len(orders), f"purchase events {len(purchases):,} vs order lines {len(orders):,}")])

    # 2
    missing = ~orders["session_id"].isin(sess.index)
    r.check(2, "Every orders.session_id exists in the clickstream",
            [(not missing.any(), f"{missing.sum()} order lines with unknown session_id")])

    # 3
    missing = ~orders["product_id"].isin(products["product_id"])
    r.check(3, "Every orders.product_id exists in products.csv",
            [(not missing.any(), f"{missing.sum()} order lines with unknown product_id")])

    # 4
    joined = orders.merge(purchases[["sess_id", "prd_id", "ts_ms", "uid", "cntry"]],
                          left_on=["session_id", "product_id"], right_on=["sess_id", "prd_id"], how="left")
    unmatched = joined["ts_ms"].isna().sum()
    ts_mismatch = (joined["ts_ms"] != joined["order_ts_ms"]).sum()
    r.check(4, "Every orders.order_ts equals the evt_ts of its source purchase event",
            [(len(joined) == len(orders), f"join on (session_id, product_id) is one-to-one: {len(joined):,} rows"),
             (unmatched == 0, f"{unmatched} order lines without a source purchase event"),
             (ts_mismatch == 0, f"{ts_mismatch} order lines whose order_ts differs from evt_ts"),
             ((joined["uid"] == joined["customer_id"]).all(), "customer_id == clickstream uid on every line"),
             ((joined["cntry"] == joined["country"]).all(), "country == clickstream cntry on every line")])

    # 5
    camp_ids = set(spend["campaign_id"]) | set(ev["cmpgn_id"].dropna())
    camp_names = set(spend["campaign_name"])
    bad_cols = [c for c in orders.columns if re.search(r"camp|cmpgn|utm|source|medium|channel|src|med$", c)]
    str_cells = orders.drop(columns="order_ts_ms").astype(str)
    leaked = int(str_cells.apply(lambda col: col.isin(camp_ids | camp_names) | col.str.contains(r"camp_\d", regex=True)).sum().sum())
    r.check(5, "No orders row carries a campaign reference",
            [(not bad_cols, f"campaign-like columns in orders: {bad_cols or 'none'}"),
             (leaked == 0, f"cells holding a campaign id or name: {leaked}")],
            info=[f"orders columns: {', '.join(c for c in orders.columns if c != 'order_ts_ms')}"])

    # 6
    paid = sess[sess["cmpgn_id"] != "(none)"]
    daily = paid.groupby(["cmpgn_id", "date"]).size().rename("sessions").reset_index()
    sp = spend.rename(columns={"campaign_id": "cmpgn_id", "spend_date": "date"})
    m = daily.merge(sp[["cmpgn_id", "date", "clicks"]], on=["cmpgn_id", "date"], how="outer")
    no_spend_row = m["clicks"].isna().sum()
    m = m.fillna({"sessions": 0, "clicks": 0})
    big = m[m["sessions"] >= DAILY_RATIO_FLOOR]
    big_ratio = big["sessions"] / big["clicks"]
    big_bad = (~big_ratio.between(*BAND_SESSIONS_TO_CLICKS)).sum()
    tot = m.groupby("cmpgn_id")[["sessions", "clicks"]].sum()
    tot["ratio"] = tot["sessions"] / tot["clicks"]
    items = [(no_spend_row == 0, f"campaign-days with sessions but no spend row: {no_spend_row}"),
             (big_bad == 0, f"campaign-days with >= {DAILY_RATIO_FLOOR} sessions outside 85-92%: {big_bad} of {len(big)}"
                            + (f" (ratio range {big_ratio.min():.3f}-{big_ratio.max():.3f})" if len(big) else ""))]
    for cid, row in tot.iterrows():
        items.append((within(row["ratio"], BAND_SESSIONS_TO_CLICKS),
                      f"{cid} total: {int(row['sessions']):,} sessions / {int(row['clicks']):,} clicks = {pct(row['ratio'], 1)}"))
    r.check(6, "Sessions are 85-92% of spend.csv clicks (daily where >= 6 sessions; campaign totals)", items,
            info=[f"campaign-days below the {DAILY_RATIO_FLOOR}-session floor (not asserted): "
                  f"{(m['sessions'] < DAILY_RATIO_FLOOR).sum()} of {len(m)}"])

    # 7
    brief_ids = {}
    for name, b in briefs.items():
        try:
            brief_ids[name] = (yaml.safe_load(b["front_raw"]) or {}).get("campaign_id")
        except Exception:
            brief_ids[name] = None
    click_camps = sorted(ev["cmpgn_id"].dropna().unique())
    no_spend = [c for c in click_camps if c not in set(spend["campaign_id"])]
    no_brief = [c for c in click_camps if c not in set(brief_ids.values())]
    r.check(7, "Every clickstream campaign_id has spend rows and a brief",
            [(not no_spend, f"campaigns without spend: {no_spend or 'none'}"),
             (not no_brief, f"campaigns without a brief: {no_brief or 'none'}")],
            info=[f"{len(click_camps)} campaigns in clickstream: {', '.join(click_camps)}"])

    # 8
    lo_ms, hi_ms = ev["ts_ms"].min(), ev["ts_ms"].max()
    r.check(8, "All event timestamps inside 2026-01-01 .. 2026-06-30",
            [(lo_ms >= T0_MS and hi_ms <= T_END_MS,
              f"min {fmt_ts(np.array([lo_ms]))[0]}, max {fmt_ts(np.array([hi_ms]))[0]}")])

    # 9
    e = ev_sorted
    ids_ok = (e["evt_id"].to_numpy() == np.arange(1, len(e) + 1)).all()
    ts_mono = (np.diff(e["ts_ms"].to_numpy()) >= 0).all()
    first_type = e.groupby("sess_id")["evt_type"].first()
    def first_id(t, keys):
        return e[e["evt_type"] == t].groupby(keys)["evt_id"].min()
    atc_first = first_id("add_to_cart", ["sess_id", "prd_id"]).rename("atc_id")
    pv_first = first_id("product_view", ["sess_id", "prd_id"]).rename("pv_id")
    co_first = first_id("checkout_start", "sess_id").rename("co_id")
    atc_any = first_id("add_to_cart", "sess_id").rename("atc_any_id")

    pur = e[e["evt_type"] == "purchase"].join(atc_first, on=["sess_id", "prd_id"]).join(co_first, on="sess_id")
    pur_bad = (pur["atc_id"].isna() | (pur["atc_id"] > pur["evt_id"]) | pur["co_id"].isna() | (pur["co_id"] > pur["evt_id"])).sum()
    rem = e[e["evt_type"] == "remove_from_cart"].join(atc_first, on=["sess_id", "prd_id"])
    rem_bad = (rem["atc_id"].isna() | (rem["atc_id"] > rem["evt_id"])).sum()
    co = e[e["evt_type"] == "checkout_start"].join(atc_any, on="sess_id")
    co_bad = (co["atc_any_id"].isna() | (co["atc_any_id"] > co["evt_id"])).sum()
    atc = e[e["evt_type"] == "add_to_cart"].join(pv_first, on=["sess_id", "prd_id"])
    atc_bad = (atc["pv_id"].isna() | (atc["pv_id"] > atc["evt_id"])).sum()
    const_cols = ["uid", "cmpgn_id", "src", "med", "dvc", "cntry"]
    nunique = e.groupby("sess_id")[const_cols].nunique(dropna=False)
    not_const = {c: int((nunique[c] > 1).sum()) for c in const_cols}
    r.check(9, "Within every session, events are time-ordered and funnel-valid",
            [(ids_ok, "evt_id runs 1..N with no gaps"),
             (ts_mono, "evt_ts never decreases in evt_id order (so within every session too)"),
             ((first_type == "page_view").all(), f"sessions not starting with page_view: {(first_type != 'page_view').sum()}"),
             (pur_bad == 0, f"purchases without an earlier add_to_cart (same product) and checkout_start: {pur_bad}"),
             (rem_bad == 0, f"remove_from_cart without an earlier add_to_cart (same product): {rem_bad}"),
             (co_bad == 0, f"checkout_start without an earlier add_to_cart: {co_bad}"),
             (atc_bad == 0, f"add_to_cart without an earlier product_view (same product): {atc_bad}"),
             (sum(not_const.values()) == 0, f"sessions where a session-constant column varies: {not_const}")])

    # 10
    required = {
        "products": (products, list(products.columns)),
        "orders": (orders, [c for c in orders.columns if c not in ("return_ts", "return_reason")]),
        "clickstream": (ev, ["evt_id", "evt_ts", "sess_id", "uid", "evt_type", "dvc", "cntry", "pg_path"]),
        "spend": (spend, list(spend.columns)),
    }
    items = []
    for name, (df, cols) in required.items():
        nulls = {c: int(df[c].isna().sum()) for c in cols if df[c].isna().any()}
        items.append((not nulls, f"{name}: nulls in non-nullable columns: {nulls or 'none'}"))
    prd_null_types = sorted(ev.loc[ev["prd_id"].isna(), "evt_type"].unique())
    items.append((set(prd_null_types) <= {"page_view", "checkout_start"},
                  f"prd_id is null only on: {', '.join(prd_null_types)}"))
    paid_null = ev["cmpgn_id"].isna()
    items.append(((ev["src"].isna() == paid_null).all() and (ev["med"].isna() == paid_null).all(),
                  "src and med are null exactly when cmpgn_id is null"))
    r.check(10, "No nulls in non-nullable columns", items,
            info=[f"distinct pg_path {ev['pg_path'].nunique()}, ref {ev['ref'].nunique()}, src {ev['src'].nunique()}, "
                  f"med {sorted(ev['med'].dropna().unique())}"])

    # ---- campaign scorecard, shared by checks 11, 13, 14 ----
    o = orders.merge(sess[["cmpgn_id", "dvc"]], left_on="session_id", right_index=True, how="left")
    o = o.merge(products[["product_id", "category"]], on="product_id", how="left")
    o["net_revenue"] = np.where(o["is_returned"], 0.0, o["line_revenue"])
    camp = pd.DataFrame({
        "sessions": sess.groupby("cmpgn_id").size(),
        "buyers": sess.groupby("cmpgn_id")["purchased"].sum(),
        "orders": o.groupby("cmpgn_id")["order_id"].nunique(),
        "lines": o.groupby("cmpgn_id").size(),
        "gross": o.groupby("cmpgn_id")["line_revenue"].sum(),
        "net": o.groupby("cmpgn_id")["net_revenue"].sum(),
        "returned": o.groupby("cmpgn_id")["is_returned"].sum(),
    }).fillna(0)
    camp = camp.join(spend.groupby("campaign_id")[["spend_usd", "clicks", "impressions"]].sum())
    camp["cr"] = camp["buyers"] / camp["sessions"]
    camp["aov"] = camp["gross"] / camp["orders"]
    camp["cpa"] = camp["spend_usd"] / camp["orders"]
    camp["gross_roas"] = camp["gross"] / camp["spend_usd"]
    camp["net_roas"] = camp["net"] / camp["spend_usd"]
    camp["return_rate"] = camp["returned"] / camp["lines"]
    paid_c = camp.drop(index="(none)")
    paid_c = paid_c.assign(gross_rank=rank_desc(paid_c["gross_roas"]), net_rank=rank_desc(paid_c["net_roas"]))

    print("\nCampaign scorecard (sessions from clickstream, revenue from orders, spend from S3):")
    view = camp.copy()
    view["gross_rank"] = paid_c["gross_rank"]
    view["net_rank"] = paid_c["net_rank"]
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(view[["sessions", "clicks", "spend_usd", "orders", "lines", "cr", "aov", "cpa", "gross_roas",
                    "gross_rank", "net_roas", "net_rank", "return_rate"]].to_string(
            formatters={"cr": lambda x: pct(x), "return_rate": lambda x: pct(x, 1), "aov": "{:,.2f}".format,
                        "cpa": "{:,.2f}".format, "spend_usd": "{:,.2f}".format, "gross_roas": "{:.2f}".format,
                        "net_roas": "{:.2f}".format, "gross_rank": lambda x: "" if pd.isna(x) else f"{int(x)}",
                        "net_rank": lambda x: "" if pd.isna(x) else f"{int(x)}"}))

    # 11
    total_rev = o["line_revenue"].sum()
    attributed = o.loc[o["cmpgn_id"] != "(none)", "line_revenue"].sum()
    overall_cr = sess["purchased"].mean()
    paid_share = (sess["cmpgn_id"] != "(none)").mean()
    aov_all = o["line_revenue"].sum() / o["order_id"].nunique()
    c4, c9 = paid_c.loc["camp_004"], paid_c.loc["camp_009"]
    cpa_sorted = paid_c["cpa"].sort_values(ascending=False)
    c2 = o[o["cmpgn_id"] == "camp_002"]
    c2_cook_lines = (c2["category"] == "Cooking & Water").mean()
    c2_app_lines = (c2["category"] == "Apparel").mean()
    c2_cook_rev = c2.loc[c2["category"] == "Cooking & Water", "line_revenue"].sum() / c2["line_revenue"].sum()
    monthly_sessions = sess.groupby("month").size()
    ramp = monthly_sessions.get("2026-06", 0) / max(monthly_sessions.get("2026-01", 0), 1)
    o["month"] = o["order_ts"].str[:7]
    cat_month = o.groupby(["category", "month"]).size().unstack(fill_value=0).reindex(columns=MONTH_LABELS, fill_value=0)
    share = cat_month / cat_month.sum(axis=0)
    dev = sess.groupby("dvc")["purchased"].mean()
    # Mantel-Haenszel rate ratio: mobile vs desktop conversion compared within
    # each traffic group, so camp_004's mobile-heavy mix can't drive the number.
    tab = sess[sess["dvc"].isin(["mobile", "desktop"])].groupby(["cmpgn_id", "dvc"])["purchased"].agg(["sum", "count"]).unstack("dvc", fill_value=0)
    n_grp = tab[("count", "mobile")] + tab[("count", "desktop")]
    mh_ratio = ((tab[("sum", "mobile")] * tab[("count", "desktop")] / n_grp).sum()
                / (tab[("sum", "desktop")] * tab[("count", "mobile")] / n_grp).sum())
    no4 = sess[sess["cmpgn_id"] != "camp_004"].groupby("dvc")["purchased"].mean()
    dev_paid = sess[sess["cmpgn_id"] != "(none)"].groupby("dvc")["purchased"].mean()
    c4_mobile = (sess.loc[sess["cmpgn_id"] == "camp_004", "dvc"] == "mobile").mean()
    c7 = o[o["cmpgn_id"] == "camp_007"]
    c7_ret = c7[c7["is_returned"]]
    c7_ftw_share = (c7_ret["category"] == "Footwear").mean() if len(c7_ret) else 0.0
    c7_ftw_ret = c7_ret[c7_ret["category"] == "Footwear"]
    c7_sizing = (c7_ftw_ret["return_reason"] == "sizing").mean() if len(c7_ftw_ret) else 0.0
    brief_007 = next((b["body"] for n_, b in briefs.items() if n_.startswith("camp_007")), "")
    brief_002 = next((b["body"] for n_, b in briefs.items() if n_.startswith("camp_002")), "")

    c7_lines = int(paid_c.loc["camp_007", "lines"])
    min_lines = int(paid_c["lines"].min())
    min_lines_at = paid_c["lines"].idxmin()
    items = [
        gated(within(overall_cr, BAND_BASELINE_CR), len(sess) * 0.036, "expected buyers at 3.6%",
              f"baseline: site-wide session conversion {pct(overall_cr)} (target ~3.6%)"),
        (within(paid_share, BAND_CAMPAIGN_SHARE), f"traffic mix: {pct(paid_share, 1)} of sessions carry a campaign (target ~58%); "
                                                  f"campaigns account for {pct(attributed / total_rev, 1)} of gross revenue"),
        # F1
        (c4["spend_usd"] == paid_c["spend_usd"].max(), f"F1 camp_004 highest spend: ${c4['spend_usd']:,.2f} "
                                                       f"(next ${paid_c['spend_usd'].nlargest(2).iloc[1]:,.2f})"),
        (c4["clicks"] == paid_c["clicks"].max(), f"F1 camp_004 highest clicks: {int(c4['clicks']):,} "
                                                 f"(next {int(paid_c['clicks'].nlargest(2).iloc[1]):,})"),
        gated(within(c4["cr"], BAND_F1_CR), c4["sessions"] * 0.004, "expected buyers at 0.4%",
              f"F1 camp_004 conversion {pct(c4['cr'])} on {int(c4['sessions']):,} sessions (target ~0.4%)"),
        gated(cpa_sorted.index[0] == "camp_004" and cpa_sorted.iloc[0] >= F1_CPA_MARGIN * cpa_sorted.iloc[1],
              c4["orders"], "camp_004 orders",
              f"F1 camp_004 worst CPA by a wide margin: ${c4['cpa']:,.2f} vs next worst {cpa_sorted.index[1]} ${cpa_sorted.iloc[1]:,.2f}"),
        # F2
        gated(within(c9["cr"], BAND_F2_CR), c9["sessions"] * 0.068, "expected buyers at 6.8%",
              f"F2 camp_009 conversion {pct(c9['cr'])} on {int(c9['sessions']):,} sessions (target ~6.8%)"),
        gated(within(c9["aov"] / aov_all, BAND_F2_AOV_RATIO), c9["orders"], "camp_009 orders",
              f"F2 camp_009 AOV ${c9['aov']:,.2f} = {c9['aov'] / aov_all:.2f}x site AOV ${aov_all:,.2f} over {int(c9['orders'])} orders (target ~2x)"),
        (c9["gross_rank"] == 1, f"F2 camp_009 best gross ROAS: {c9['gross_roas']:.2f}"),
        (c9["sessions"] == paid_c["sessions"].min() and rank_desc(paid_c["spend_usd"])["camp_009"] >= N_CAMPAIGNS - 1,
         f"F2 camp_009 nearly invisible: {pct(c9['sessions'] / paid_c['sessions'].sum(), 1)} of campaign sessions, "
         f"spend rank {rank_desc(paid_c['spend_usd'])['camp_009']} of {N_CAMPAIGNS}"),
        # F3
        gated(within(c2_cook_lines, BAND_F3_COOKING_LINES) and c2_cook_lines > c2_app_lines, len(c2), "camp_002 lines",
         f"F3 camp_002 order lines in Cooking & Water {pct(c2_cook_lines, 1)} (target ~60%), Apparel {pct(c2_app_lines, 1)}, "
         f"{len(c2)} lines"),
        ("apparel" in brief_002.lower() and "cooking" not in brief_002.lower(),
         "F3 camp_002 brief targets Apparel and never mentions Cooking"),
        # F4
        (within(ramp, BAND_F4_RAMP), f"F4 sessions June / January = {ramp:.2f}x "
                                     f"({monthly_sessions.get('2026-01', 0):,} -> {monthly_sessions.get('2026-06', 0):,}, target ~2.5x)"),
    ]
    for cat in ("Tents & Shelter", "Footwear"):
        peak = cat_month.loc[cat].idxmax()
        early = share.loc[cat, ["2026-01", "2026-02"]].mean()
        late = share.loc[cat, ["2026-05", "2026-06"]].mean()
        n_cat = int(cat_month.loc[cat, ["2026-01", "2026-02", "2026-05", "2026-06"]].sum())
        items.append(gated(peak in ("2026-05", "2026-06") and late >= F4_PEAK_LIFT * early, n_cat,
                           f"{cat} lines Jan-Feb + May-Jun",
                      f"F4 {cat}: peak month {peak}, share of order lines {pct(early, 1)} Jan-Feb -> {pct(late, 1)} May-Jun "
                      f"({late / early if early else float('inf'):.2f}x)"))
    items += [
        # F5
        gated(within(mh_ratio, BAND_F5_MOBILE_RATIO), min(tab[("sum", "mobile")].sum(), tab[("sum", "desktop")].sum()),
              "buyers on the smaller of mobile/desktop",
         f"F5 mobile converts at {mh_ratio:.2f}x desktop within traffic groups (Mantel-Haenszel). Pooled, for reference: "
         f"all sessions {dev['mobile'] / dev['desktop']:.2f}x ({pct(dev['mobile'])} vs {pct(dev['desktop'])}), "
         f"campaign traffic {dev_paid['mobile'] / dev_paid['desktop']:.2f}x, excluding camp_004 {no4['mobile'] / no4['desktop']:.2f}x"),
        (within(c4_mobile, BAND_F5_C004_MOBILE), f"F5 camp_004 traffic is {pct(c4_mobile, 1)} mobile (target ~90%)"),
        # F6
        gated(within(paid_c.loc["camp_007", "return_rate"], BAND_RETURNS_C007), c7_lines, "camp_007 lines",
              f"F6 camp_007 return rate {pct(paid_c.loc['camp_007', 'return_rate'], 1)} on {c7_lines} lines (target ~24%)"),
        gated(c7_ftw_share >= F6_MIN_FOOTWEAR_SHARE, len(c7_ret), "camp_007 returned lines",
              f"F6 camp_007 returns that are Footwear: {pct(c7_ftw_share, 1)} of {len(c7_ret)}"),
        gated(c7_sizing >= F6_MIN_SIZING_SHARE, len(c7_ftw_ret), "camp_007 returned Footwear lines",
              f"F6 camp_007 Footwear returns with reason 'sizing': {pct(c7_sizing, 1)} of {len(c7_ftw_ret)}"),
        (paid_c.loc["camp_007", "gross_rank"] <= 3,
         f"F6 camp_007 gross ROAS rank {paid_c.loc['camp_007', 'gross_rank']} (top three)"),
        gated(paid_c.loc["camp_007", "net_rank"] >= 8, min_lines, f"fewest lines in any campaign ({min_lines_at})",
              f"F6 camp_007 net ROAS rank {paid_c.loc['camp_007', 'net_rank']} (outside top seven)"),
        (bool(re.search(r"true[- ]to[- ]size", brief_007, re.I)), "F6 camp_007 brief makes a true-to-size promise"),
    ]
    r.check(11, "Planted findings F1-F6 present at stated magnitude (queried from the files)", items,
            info=[f"F3 camp_002 Cooking & Water share of gross revenue: {pct(c2_cook_rev, 1)}",
                  f"F2 camp_009 spread: {o.loc[o['cmpgn_id'] == 'camp_009', 'product_id'].nunique()} distinct products over "
                  f"{int(c9['lines'])} lines, most-bought product {pct(o.loc[o['cmpgn_id'] == 'camp_009', 'product_id'].value_counts(normalize=True).max() if c9['lines'] else 0, 1)} of lines",
                  f"F6 camp_007 share of gross revenue returned: {pct(1 - paid_c.loc['camp_007', 'net'] / paid_c.loc['camp_007', 'gross'], 1)}"])

    # 12
    sizes = file_sizes(out)
    full = n_events >= FULL_SCALE_EVENTS
    info = [f"{k:<12} {v / 1e6:9.3f} MB   target ~{SIZE_TARGETS[k] / 1e6:.3f} MB" for k, v in sizes.items() if k in SIZE_TARGETS]
    total = sum(v for k, v in sizes.items() if k != "parquet_max")
    bpr = sizes["clickstream"] / len(ev)
    info.append(f"total        {total / 1e6:9.3f} MB   budget < {TOTAL_BUDGET / 1e6:.0f} MB")
    info.append(f"clickstream bytes/row {bpr:.1f} (full-scale target ~{CLICKSTREAM_TARGET_BYTES_PER_ROW:.0f}, "
                f"warn above {CLICKSTREAM_WARN_BYTES_PER_ROW:.0f})")
    info.append(f"orders bytes/row {sizes['orders'] / len(orders):.1f}, products bytes/row {sizes['products'] / len(products):.1f}, "
                f"spend bytes/row {sizes['spend'] / len(spend):.1f}, briefs avg {sizes['briefs'] / max(len(briefs), 1):,.0f} bytes")
    words = {n_: len(re.findall(r"\b[\w'’-]+\b", b["body"])) for n_, b in briefs.items()}
    info.append(f"brief body words: min {min(words.values())}, max {max(words.values())} (spec 300-400)")
    if bpr > CLICKSTREAM_WARN_BYTES_PER_ROW:
        info.append(f"WARNING clickstream is {bpr:.1f} bytes/row, above {CLICKSTREAM_WARN_BYTES_PER_ROW:.0f}")
    if full:
        r.check(12, "File sizes at most 20% over section 1 targets (under target always passes)",
                [(sizes[k] <= 1.20 * SIZE_TARGETS[k], f"{k} {sizes[k] / 1e6:.3f} MB = {sizes[k] / SIZE_TARGETS[k]:.2f}x target")
                 for k in SIZE_TARGETS]
                + [(total < TOTAL_BUDGET, f"total {total / 1e6:.2f} MB < 30 MB"),
                   (sizes["parquet_max"] < 100 * 2 ** 20, "largest Parquet file under GitHub's 100 MiB limit"),
                   (bpr <= CLICKSTREAM_WARN_BYTES_PER_ROW, f"clickstream {bpr:.1f} bytes/row <= {CLICKSTREAM_WARN_BYTES_PER_ROW:.0f}")],
                info=info)
    else:
        r.skip(12, f"File sizes vs section 1 targets: skipped below {FULL_SCALE_EVENTS:,} events", info=info)

    # 13
    ret = orders["is_returned"]
    ts_null_ok = (orders["return_ts"].isna() == ~ret).all()
    reason_null_ok = (orders["return_reason"].isna() == ~ret).all()
    rt = orders[ret]
    lag_days = (pd.to_datetime(rt["return_ts"], format="%Y-%m-%d %H:%M:%S.%f") -
                pd.to_datetime(rt["order_ts"], format="%Y-%m-%d %H:%M:%S.%f")).dt.total_seconds() / 86400
    after_window = (rt["return_ts"] > "2026-06-30 23:59:59.999").sum()
    r.check(13, "Returns: ~8% overall, ~24% camp_007, return_ts consistent",
            [gated(within(ret.mean(), BAND_RETURNS_ALL), len(orders), "order lines",
                   f"overall return rate {pct(ret.mean(), 1)} ({int(ret.sum())} of {len(orders)} lines)"),
             gated(within(paid_c.loc["camp_007", "return_rate"], BAND_RETURNS_C007), c7_lines, "camp_007 lines",
                   f"camp_007 return rate {pct(paid_c.loc['camp_007', 'return_rate'], 1)} on {c7_lines} lines"),
             (ts_null_ok, "return_ts null exactly when is_returned is false"),
             (reason_null_ok, "return_reason null exactly when is_returned is false"),
             (len(lag_days) == 0 or (lag_days.between(5, 30).all()),
              f"return_ts - order_ts in 5-30 days (observed {lag_days.min():.1f}-{lag_days.max():.1f})" if len(lag_days)
              else "no returned lines"),
             (after_window == 0, f"return_ts on or before 2026-06-30 (snapshot cutoff): {after_window} later")],
            info=[f"right-censoring: return rate on orders from the last 30 days {pct(orders.loc[orders['order_ts'] >= '2026-06-01', 'is_returned'].mean(), 1)}"
                  f" vs before {pct(orders.loc[orders['order_ts'] < '2026-06-01', 'is_returned'].mean(), 1)}",
                  "non-camp_007 return rate "
                  f"{pct(o.loc[o['cmpgn_id'] != 'camp_007', 'is_returned'].mean(), 1)}; reasons overall: "
                  + ", ".join(f"{k} {v}" for k, v in orders['return_reason'].value_counts().items())])

    # 14
    g7, n7 = paid_c.loc["camp_007", "gross_rank"], paid_c.loc["camp_007", "net_rank"]
    order_gross = paid_c.sort_values("gross_roas", ascending=False)
    order_net = paid_c.sort_values("net_roas", ascending=False)
    r.check(14, "Ranking inversion: camp_007 top three on gross ROAS, outside top seven on net",
            [(g7 <= 3, f"gross revenue per dollar: rank {g7} of {N_CAMPAIGNS}"),
             gated(n7 >= 8, min_lines, f"fewest lines in any campaign ({min_lines_at})",
                   f"net revenue per dollar: rank {n7} of {N_CAMPAIGNS}")],
            info=["gross: " + ", ".join(f"{i} {v:.2f}" for i, v in order_gross["gross_roas"].items()),
                  "net:   " + ", ".join(f"{i} {v:.2f}" for i, v in order_net["net_roas"].items())])

    # 15
    items = []
    spend_ids = set(spend["campaign_id"])
    per_campaign = {cid: [n_ for n_ in briefs if n_.startswith(cid + "_")] for cid in sorted(spend_ids)}
    items.append((all(len(v) == 1 for v in per_campaign.values()),
                  "exactly one brief per campaign: " + ", ".join(f"{k}={len(v)}" for k, v in per_campaign.items())))
    for name, b in briefs.items():
        try:
            fm = yaml.safe_load(b["front_raw"])
            ok = isinstance(fm, dict) and fm.get("campaign_id") == name[:8] and fm.get("campaign_id") in spend_ids
            names_ok = set(spend.loc[spend["campaign_id"] == fm.get("campaign_id"), "campaign_name"]) == {fm.get("campaign_name")}
            items.append((ok and names_ok, f"{name}: YAML ok, campaign_id {fm.get('campaign_id')} matches filename and spend"
                                           + ("" if names_ok else " (campaign_name mismatch)")))
        except Exception as exc:
            items.append((False, f"{name}: frontmatter does not parse ({exc})"))
    items.append((set(brief_ids.values()) == spend_ids, "brief campaign set == spend campaign set"))
    r.check(15, "Briefs: one per campaign, valid YAML frontmatter, ids match filename and spend", items)

    print("\n" + "=" * 78)
    if r.failed:
        print(f"VALIDATION FAILED: checks {', '.join(map(str, r.failed))}")
    else:
        print("VALIDATION PASSED")
    print("=" * 78)
    return not r.failed


# ---------------------------------------------------------------------------
# 9. Size report
# ---------------------------------------------------------------------------
def file_sizes(out: Path) -> dict:
    parquet = list((out / "databricks/clickstream").glob("month=*/events.parquet"))
    return {
        "products": (out / "postgres/products.csv").stat().st_size,
        "orders": (out / "postgres/orders.csv").stat().st_size,
        "clickstream": sum(f.stat().st_size for f in parquet),
        "spend": sum(f.stat().st_size for f in (out / "s3/marketing/spend").glob("month=*/spend.csv")),
        "briefs": sum(f.stat().st_size for f in (out / "s3/marketing/briefs").glob("*.md")),
        "schema": (out / "postgres/schema.sql").stat().st_size,
        "parquet_max": max(f.stat().st_size for f in parquet),
    }


def size_report(out: Path):
    print("\nFILE SIZES")
    files = sorted(p for p in out.rglob("*") if p.is_file())
    for f in files:
        print(f"  {f.stat().st_size:>12,}  {f.relative_to(out)}")
    print(f"  {sum(f.stat().st_size for f in files):>12,}  total")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--events", type=int, default=FULL_SCALE_EVENTS, help="total clickstream events (default 2,000,000)")
    ap.add_argument("--out", type=Path, default=Path("output"), help="output directory (default ./output)")
    args = ap.parse_args(argv)

    rng = np.random.default_rng(SEED)
    n_sessions = round(args.events * SESSIONS_PER_EVENT)
    print(f"Generating {args.events:,} events across {n_sessions:,} sessions into {args.out}/ (seed {SEED})")

    products = build_products(rng)                                          # 1
    cat_w = group_category_weights()                                        # 2
    premium_q = premium_quantile(products, cat_w)
    choice = product_choice_tables(products, premium_q)
    sessions = build_sessions(rng, n_sessions)                              # 3
    stage, organic_buyers = assign_stages(rng, sessions)
    plans = plan_purchases(rng, sessions, stage, cat_w, choice)
    ev = build_events(rng, sessions, stage, plans, products, cat_w, choice, args.events)   # 4
    parts = clickstream_tables(ev, sessions, products)
    orders, order_info = build_orders(rng, ev, sessions, products)          # 5
    spend = build_spend(rng, sessions, order_info)                          # 6
    write_outputs(args.out, products["df"], orders, parts, spend)           # 7 (briefs written here)

    organic_sessions = int((sessions["grp"] == ORGANIC).sum())
    print(f"  daily growth {sessions['growth']:.5f}/day, paid share by day {sessions['paid_share'].min():.2f}-"
          f"{sessions['paid_share'].max():.2f}, camp_009 premium floor = category price quantile {premium_q:.2f}, "
          f"organic conversion {organic_buyers / organic_sessions:.2%}")

    ok = validate(args.out, args.events)                                    # 8
    size_report(args.out)                                                   # 9
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Brief bodies (section 6). Frontmatter is generated from CAMPAIGNS above.
# Targeting claims, creative angle and success metric live in the prose on
# purpose: F3 and F6 depend on them being read, not looked up.
# ---------------------------------------------------------------------------
BRIEFS = {
"camp_001": """
## Objective

Own the high-intent search moment before spring hiking season starts. When someone types "best hiking backpack" or "45 litre pack" in January, they are three to eight weeks away from a trip and still comparing options. We want to be in that comparison, with a landing experience that closes the gap between research and purchase faster than the big multi-brand retailers can.

## Channel and timing

Google Ads, search only, no display or video. Planned run 5 January to 30 April 2026. Budget is front-loaded into February and March, when trip planning peaks, and tapers through April as intent shifts from research to last-minute buying.

## Target audience

Hikers aged 25 to 50 in the US, UK and Germany who are planning day hikes and their first multi-day trips. Mostly people who already own some gear and are upgrading rather than starting from zero. We keep keywords technical (litre sizes, frame types, back length, fit terms) to filter out casual browsers.

## Target categories

Backpacks first, Hiking Packs specifically, with Daypacks as the volume line. Sleep Systems is the secondary category: pack buyers planning overnights tend to look at pads and bags in the same session, and we want those pages one click away.

## Creative angle

Practical and specific. Headlines lead with capacity and weight rather than lifestyle, for example "45L, 1.3 kg, built for three-day loops." Sitelinks go straight to the relevant category page, never the homepage. We are deliberately not running brand-awareness copy here. This is a harvesting campaign, and the copy should read like a spec sheet written by someone who hikes.

## Success metric

Return on ad spend of 4.0 or better on attributed revenue across the full run. Secondary: cost per click under $2.20 on non-brand terms. If ROAS sits below 3.0 by mid-March we pull budget back to brand terms only and rethink the keyword set.

## Risks

Search competition from the large outdoor retailers spikes in March and our CPCs will follow it up. We are also relying on category pages that have not been redesigned since last year, so landing page conversion is the variable we control least. Worth a check-in with the web team before launch.
""",
"camp_002": """
## Objective

Make Northbound the default answer for merino and synthetic base layers. Base layers are the gateway purchase in Apparel: a low price point, a high repeat rate, and once a customer trusts our sizing on a base layer they come back for shells and trousers. This campaign is the first step in growing Apparel from a supporting category into a leading one.

## Channel and timing

Meta, Facebook and Instagram, feed and stories placements. Planned run 10 February to 31 May 2026, covering the cold end of winter and the spring shoulder season, when layering matters most and people are finally replacing the tired layers they wore all winter.

## Target audience

Active adults 25 to 45 who hike, ski tour or run outdoors through the colder months. Interest targeting on trail running, ski touring and layering systems, plus a lookalike audience built from past Apparel buyers. Europe weighted, with Germany, the Netherlands and the Nordics as priority markets.

## Target categories

Apparel, and specifically Base Layers. Every creative, every landing page and every audience in this campaign points at the base layer range. Shell Jackets and Trousers are welcome add-ons but they are not the goal. Anything outside Apparel that this campaign happens to sell is incidental.

## Creative angle

"One layer, three seasons." Short-form video of a single merino crew worn on a frozen February ridge, a wet April trail run and a still May evening at camp with the brew-up going. Carousels show the fabric close up. The landing page is a dedicated base layer page, not the general Apparel category, so the message stays tight from ad to cart.

## Success metric

We judge this on Apparel. Target: at least half of attributed order lines in Apparel, and ROAS of 3.5 or better on attributed revenue. If the campaign drives sales but not in Apparel, we will treat that as a targeting failure rather than a win.

## Notes

We are confident the audience is right. Past Apparel buyers are our most loyal segment and the lookalike should find more people like them. The main risk is creative fatigue after week six, and we have a second creative set ready to rotate in when frequency climbs past three.
""",
"camp_003": """
## Objective

Capture tent demand as the camping season opens. Tent searches start climbing in March and peak in late May, and most buyers decide within two or three sessions. We want Northbound on the first results page for capacity and weight searches through the whole climb, not just the peak.

## Channel and timing

Google Ads, search plus shopping. Planned run 1 March to 30 June 2026. Budget ramps month on month to follow search volume, with the heaviest weeks around the late-May holiday weekends in the US and UK.

## Target audience

Backpackers and family campers in the US, Canada and the UK. Two clear groups: lightweight backpackers searching for one- and two-person tents by weight, and families searching for space and weather protection. Ad groups are split along that line so copy can speak to each.

## Target categories

Tents & Shelter. Tents are the core, with Footprints as the natural attach item and Tarps as a smaller line for the ultralight crowd. We are not trying to sell sleeping bags or packs off this campaign. If they come along, fine, but nothing is optimised for them.

## Creative angle

"Pitched in five minutes, dry all night." Shopping images show the tent pitched in real conditions rather than on white backgrounds. Search copy leads with packed weight for the backpacking group and floor area for families. Footprint bundles get their own sitelink because the attach rate on bundles was strong last season.

## Success metric

ROAS of 4.0 or better on attributed revenue, and Tents & Shelter making up at least 60% of attributed revenue. We will also watch impression share on the top twenty tent keywords and want to hold above 40% through May.

## Risks

Stock depth on the two-person models is the real constraint. If the popular colours sell through in May we will be paying for clicks that land on out-of-stock pages. Merchandising has promised a June replenishment, which we are planning around but not counting on. A second, smaller risk is weather: a cold, wet May pushed demand later last year and could do it again.
""",
"camp_004": """
## Objective

Put Northbound in front of a younger audience at real scale. Our customer base skews older than the category, and TikTok is where the next generation of hikers is discovering gear. This campaign is about volume first: reach, clicks and new visitors who have never heard of us before today.

## Channel and timing

TikTok, Spark Ads boosting creator posts plus in-feed ads. Planned run 1 February to 15 June 2026. This is our largest paid budget of the half, and we expect it to become our biggest acquisition channel by the end of the year.

## Target audience

18 to 30, broad interest targeting on hiking, camping, van life and outdoor travel, US and UK first. Mobile-first by definition. We are intentionally keeping targeting wide and letting the algorithm find the buyers; narrow targeting would choke the reach we are paying for.

## Target categories

The whole range, really. In practice Apparel and Backpacks lead because they look good on camera, but we are not restricting creators. If a creator wants to film a stove boiling at sunrise, that is on brand.

## Creative angle

Trailhead Stories. Twelve outdoor creators each film a day on the trail with Northbound gear: the drive in, the trailhead, the summit, the pack-down. Formats include "what's in my pack", gear reveals and honest first impressions. The landing page collects all creator content in one place with shoppable links.

## Success metric

Reach and clicks first. Target: at least twice the click volume of any other campaign, cost per click under $1.60, and a conversion rate in line with the site average once the audience warms up. We are not going to judge a reach campaign on last-click ROAS in its first quarter; that would be measuring it against a job it was not built to do.

## Notes

The creators are the proof. Their audiences are engaged, the comment sections are full of gear questions, and the early test posts outperformed anything we have run on Meta. We are confident conversion will follow the attention. Spend is weighted to the later months, when outdoor content peaks on the platform.
""",
"camp_005": """
## Objective

Sell sleeping bags and pads to people extending their camping season into the cold months. Winter and shoulder-season campers are a smaller group than summer campers, but they spend more per order and they research carefully, which suits a considered category like Sleep Systems.

## Channel and timing

Meta, Facebook and Instagram, feed placements with a retargeting layer. Planned run 12 January to 12 April 2026. We stop before peak summer so the budget goes into the window where warmth ratings genuinely matter to the buyer.

## Target audience

Experienced campers aged 28 to 55 in the US, Canada, Germany and the Nordics with interests in winter camping, ski touring and backpacking. Retargeting picks up anyone who viewed a sleeping bag page in the last thirty days.

## Target categories

Sleep Systems. Sleeping Bags lead, with insulated Sleeping Pads as the second line, because a warm bag on a cold pad still means a cold night and our customers know it. Pillows are an easy add-on but not a focus.

## Creative angle

"Sleep warm at minus ten." Side-by-side creative showing the comfort and limit ratings in plain language, plus short clips of a frosty tent at dawn with someone climbing out looking rested. Copy explains R-values without assuming the reader already knows what they are.

## Success metric

ROAS of 3.5 or better on attributed revenue, with Sleep Systems at least 60% of attributed revenue. We also want the bag-plus-pad combination in at least one in five attributed orders, because the combination is the right answer for the customer and the better basket for us.

## Risks

A mild winter would soften demand, and our down bags are priced at the upper end of the range, so the creative has to earn that price rather than apologise for it. Retargeting frequency needs a cap at four per week; last year we annoyed people with seven or eight.

## Notes

We expect most conversions on desktop after a mobile first touch. That pattern is normal for considered purchases and not a reason to cut mobile placements.
""",
"camp_006": """
## Objective

Keep Northbound present in the review content that people read just before they buy. Independent gear reviews are one of the last stops before a purchase, and when our products are reviewed well we want a clean, trackable path from the review straight to the product page.

## Channel and timing

Affiliate, always-on. Planned run 1 January to 30 June 2026, the full half. Two partners: Trail Review Hub, a large independent review site, and Summit Journal, a long-form outdoor magazine with a strong gear section.

## Target audience

Researchers. People reading a "best tents of 2026" roundup or a long-term pack review are close to a decision and comparing a shortlist. They skew desktop, read to the end, and tend to buy the item that was reviewed rather than browse around the site.

## Target categories

Broad, following whatever the partners review. In practice Tents & Shelter and Backpacks get the most coverage, with Footwear reviews picking up in spring. We supply samples to both partners but have no editorial control, and we do not want any.

## Creative angle

There is no creative in the usual sense. The partners write what they write. Our job is making sure every product mentioned has a working deep link, current pricing and stock, and that the product pages answer the questions the reviews raise.

## Success metric

ROAS of 4.0 or better after commission and placement fees. Commission is 8% of attributed revenue; placement fees cover homepage features in roundup season. We also track the share of reviewed products that appear in attributed orders, as a sign the links are doing their job.

## Risks

A bad review of a flagship product would hurt, and we cannot prevent one. Both partners are also courted by every brand in the category, so placement fees are drifting up each quarter. We should agree fees for the second half before June rather than after it.

## Notes

This is our steadiest channel. It is not exciting, it does not spike, and that is exactly why we keep it running all year.
""",
"camp_007": """
## Objective

Grow Footwear by removing the biggest objection to buying boots online: fit. Our research says shoppers abandon boot purchases because they are not sure the size will be right. This campaign answers that directly with our fit promise and turns Footwear into a growth category for the summer.

## Channel and timing

Google Ads, search plus shopping. Planned run 15 March to 30 June 2026, timed to catch people buying boots for summer hiking with enough time to break them in before their trips.

## Target audience

Hikers in the US, UK and Germany searching for hiking boots and trail runners, especially people searching by size, width or "true to size" phrasing. A second ad group targets people comparing named competitor models against ours.

## Target categories

Footwear. Hiking Boots lead, with Trail Runners as the second line. Sandals are in the shopping feed but not bid up.

## Creative angle

The fit promise, front and centre. Every ad says it: "True to size, every time. Order your usual size." Our lasts are built true to size, so there is no need to size up or down and no need to order two pairs to compare. The landing page carries the promise, a short video from our product lead on how the lasts are measured, and the size chart. We want shoppers to feel confident enough to order one pair in their normal size and stop worrying about it.

## Success metric

Gross ROAS of 4.5 or better on attributed revenue. This is a revenue campaign and we will judge it on revenue per dollar spent. Secondary: Footwear share of total site revenue up two points over the run. Returns are tracked by the operations team and sit outside this campaign's scorecard.

## Risks

Competitors run heavy discounting on boots in May. We are choosing not to match it and to win on confidence instead. Shopping feed approvals for the new boot models have been slow, so the first two weeks may lean on search alone.

## Notes

We are confident this is the right message at the right time. Fit is the objection, and we are answering it more clearly than anyone else in the category.
""",
"camp_008": """
## Objective

Sell travel and hiking packs into summer trip season. June is when people book their trips and realise their old pack will not do, and we want the replacement to be ours. Secondary aim: test whether TikTok can sell a specific category rather than just raise awareness of the brand.

## Channel and timing

TikTok, in-feed ads with a small Spark Ads budget behind two creators. Planned run 1 April to 30 June 2026. Shorter and narrower than Trailhead Stories, and deliberately so.

## Target audience

22 to 35, interests in travel, backpacking, hiking and festivals, US, UK and Ireland. We are aiming at the overlap between travel and hiking: people taking one trip with both a city and a trail in it.

## Target categories

Backpacks. Travel Packs and carry-on sized Hiking Packs lead. Daypacks appear as the second item in the "packed and ready" flat-lay content but are not the focus.

## Creative angle

"Packed and ready." Time-lapse packing videos: everything for a ten-day trip going into a 40-litre pack, then the pack going into an overhead bin. Then the same pack on a trail two days later. Clear, satisfying, no voiceover needed. Every video ends on the pack's capacity and weight.

## Success metric

ROAS of 3.0 or better on attributed revenue, which is lower than our search targets on purpose because this is a prospecting audience. Cost per click under $1.40. Backpacks at least 60% of attributed revenue.

## Risks

We are running alongside Trailhead Stories on the same platform, so the two campaigns will compete for some of the same audience and drive each other's costs up. We have set frequency caps and excluded the creator audiences from this campaign to limit the overlap, but some will happen.

## Notes

If this works, it is the template for running a category-specific campaign on TikTok in the second half: one category, one clear format, one number to judge it on. If it does not, we will have learned that cheaply. Either result is useful.
""",
"camp_009": """
## Objective

A small test with two specialist publishers whose readers are serious about the mountains. Neither partner has a big audience, and we are not expecting meaningful volume. The question is whether a few thousand very committed readers are worth reaching at all, compared with the broad channels we run everywhere else.

## Channel and timing

Affiliate. Planned run 20 January to 20 May 2026. Two partners: Alpine Dispatch, a paid newsletter for alpinists and ski mountaineers, and The Ridge Letter, a long-form trip report site with a small, loyal readership.

## Target audience

Experienced mountaineers, expedition planners and long-distance hikers. Mostly desktop readers who read the whole piece and come back to it. Older and more affluent than our average customer, and much less price sensitive than anyone we reach on social.

## Target categories

The premium end of Tents & Shelter and Sleep Systems: four-season tents, expedition sleeping bags, insulated pads. These readers buy the top model or nothing, and the partners only want to feature products they would take on a real trip themselves.

## Creative angle

None of our own. Each partner writes a single feature per month built around a trip, with our products used and linked naturally inside it. No banner placements, no discount codes, no hard sell. Both partners were very clear that their readers would leave if the content read as an advert.

## Success metric

Break-even or better: ROAS of 2.5, with cost per order under $60. Honestly, if this pays for itself we will call it a success and a learning, not a channel. We are not planning to scale it and the budget is capped at a level where losing it all would not matter.

## Risks

Very small numbers. A handful of orders either way will swing every metric we look at, so we will not read too much into individual months. We should look at the whole run before drawing any conclusions about whether specialist audiences work for us.
""",
"camp_010": """
## Objective

Grow Cooking & Water as a basket builder. Stoves, cookware and filters are rarely the first thing someone buys from us, but they are often the second and third, and a customer who buys a stove usually comes back for fuel and a pot. We want more first orders that include a kitchen item.

## Channel and timing

Meta, Facebook and Instagram, feed and reels placements. Planned run 15 February to 10 June 2026, building into the main camping months.

## Target audience

Campers and backpackers aged 25 to 50 across the US, UK, Germany and France, plus a broad interest audience around outdoor cooking and camp food. We will test a lookalike of past Cooking & Water buyers against the interest audience in the first four weeks and keep whichever wins.

## Target categories

Cooking & Water. Stoves and integrated stove systems lead, Water Filters second, Cookware as the attach item. We also want to see whether a kitchen-led ad pulls Backpacks or Tents into the same basket, which would make the campaign more valuable than its own category numbers suggest.

## Creative angle

"Camp Kitchen." Short recipe clips filmed at camp: a two-pot dinner, a proper coffee at sunrise, filtered stream water into a pan. Food first, gear second. The gear is visible in every shot but the hook is always the meal, because nobody stops scrolling for a stove on a white background.

## Success metric

ROAS of 3.5 or better on attributed revenue, and an average order value above $70 on attributed orders, which would show the kitchen items pulling other products along with them into the basket.

## Risks

Low average prices in this category make ROAS hard to hit unless baskets grow. If AOV stays near the price of a single stove, the campaign will look weak on ROAS even if it is doing its job as a basket builder, and we should be ready to explain that rather than cut it early.

## Notes

The recipe content can be reused on our own channels and in email after the campaign ends, which is part of the value even if it never shows up in the attributed numbers.
""",
}


if __name__ == "__main__":
    sys.exit(main())
