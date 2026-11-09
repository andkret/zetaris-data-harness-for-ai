# Course Dataset Specification

Synthetic e-commerce dataset for the Zetaris Cloud course. Three platforms, one
business, one generator.

The point of this data is to make federated query necessary rather than optional.
Each source holds one third of the funnel and no single source can answer the
questions that matter. Keep that property intact when changing anything here.

---

## 0. Scope and ground rules

**Business:** `Northbound Outfitters`, a direct-to-consumer outdoor gear store.
Six categories, 300 SKUs, selling into Europe and North America.

*(The vertical is cosmetic. To swap it, change the category tree and product name
generator in section 2 and the brief text in section 6. Nothing else depends on it.)*

**Date range:** fixed, `2026-01-01` through `2026-06-30` inclusive. 181 days.
Never generate relative to the current date. Students must get byte-identical files
to what is shown on camera.

**Seed:** fixed at `20260101`. Every run produces identical output. Any randomness
must draw from a single seeded generator passed through the whole script.

**Currency:** USD throughout. Two decimal places. Store as numeric, not string.

**Three target platforms:**

| Platform | Holds | Role in the funnel |
|---|---|---|
| Postgres | products, orders | Money out. Revenue, margin, what sold. |
| Databricks | clickstream | Behaviour. Sessions, funnel, attribution. |
| S3 | campaign spend, campaign briefs | Money in. Ad spend and stated intent. |

**Deliberate omission:** `campaign_id` must NOT appear in the Postgres orders table.
Attribution has to run orders to session to clickstream. If campaign lands in
Postgres the whole federation demo collapses into a two-table join. This is the
single most important constraint in this document.

---

## 1. Output manifest

| # | File(s) | Rows | Format | Target size |
|---|---|---|---|---|
| 1 | `postgres/products.csv` | 300 | CSV | ~33 KB |
| 2 | `postgres/orders.csv` | ~11,200 | CSV | ~1.07 MB |
| 3 | `databricks/clickstream/month=2026-{01..06}/events.parquet` | 2,000,000 | Parquet (snappy) | ~17.0 MB total |
| 4 | `s3/marketing/spend/month=2026-{01..06}/spend.csv` | ~1,200 | CSV | ~73 KB |
| 5 | `s3/marketing/briefs/camp_0{01..10}_*.md` | 10 files | Markdown + YAML frontmatter | ~22 KB |

Targets are the sizes measured on the full 2M run (seed `20260101`, total ~18.2 MB).
They are ceilings, not bands: a file may come in smaller, never more than 20% larger.

Plus `postgres/schema.sql` with `CREATE TABLE` statements and `COPY` hints.

Total repo payload target: **under 30 MB**. The generator must print actual
file sizes at the end so this is checked, not assumed.

### Size discipline

Two rules, both non-negotiable, because breaking either blows the GitHub budget:

1. **All IDs are integers.** No UUIDs anywhere. A random 36-char `event_id` on
   2M rows costs ~40 MB on its own because it defeats compression. Sequential
   `int64` delta-encodes to roughly a byte per row.
2. **Clickstream is Parquet, never CSV.** The same 2M events as CSV is ~340 MB,
   over GitHub's 100 MiB per-file hard block. Write with snappy compression and
   dictionary encoding on all low-cardinality string columns.

---

## 2. `products.csv` (Postgres)

300 rows, 50 per category.

| Column | Type | Notes |
|---|---|---|
| `product_id` | int | 1001–1300, sequential |
| `sku` | string | `NBO-{CAT3}-{nnnn}`, e.g. `NBO-TNT-0042` |
| `product_name` | string | `{brand} {model} {descriptor}`, e.g. `Caldera Ridge 2P Tent` |
| `category` | string | see tree below |
| `subcategory` | string | see tree below |
| `brand` | string | 12 invented brands, unevenly distributed |
| `unit_price` | numeric(10,2) | per-category range below |
| `unit_cost` | numeric(10,2) | 58–74% of `unit_price`, drawn per product |
| `launch_date` | date | 70% before 2026-01-01 (back to 2023), 30% during the window |
| `is_active` | boolean | 94% true |

### Category tree and price ranges

| Category | Subcategories | Price range |
|---|---|---|
| Tents & Shelter | Tents, Tarps, Footprints | $80 – $700 |
| Backpacks | Daypacks, Hiking Packs, Travel Packs | $40 – $320 |
| Sleep Systems | Sleeping Bags, Sleeping Pads, Pillows | $30 – $450 |
| Footwear | Hiking Boots, Trail Runners, Sandals | $60 – $260 |
| Apparel | Shell Jackets, Base Layers, Trousers | $25 – $380 |
| Cooking & Water | Stoves, Cookware, Water Filters | $15 – $180 |

Price distribution within a category should be right-skewed, not uniform. Most
products cluster in the lower third with a thin premium tail. That makes average
order value an interesting number rather than a flat one.

Product names must be invented. No real brands.

---

## 3. `orders.csv` (Postgres)

One row per order line item. `order_id` repeats across lines of the same order.
Target ~11,000 rows from ~6,500 orders, averaging 1.7 lines per order.

| Column | Type | Notes |
|---|---|---|
| `order_line_id` | int | sequential primary key |
| `order_id` | int | repeats within an order |
| `order_ts` | timestamp | matches the source purchase event exactly |
| `customer_id` | int | maps to `user_id` in clickstream |
| `session_id` | int | **the join key to clickstream** |
| `product_id` | int | FK to products |
| `quantity` | int | 1 (82%), 2 (14%), 3 (4%) |
| `unit_price` | numeric(10,2) | catalog price with discount applied |
| `discount_pct` | numeric(5,2) | 0 for ~70% of lines, else 5–30 |
| `line_revenue` | numeric(10,2) | `quantity * unit_price`, rounded to cents. **Gross. Not return-adjusted.** |
| `is_returned` | boolean | ~8% baseline, see F6 |
| `return_ts` | timestamp, nullable | 5–30 days after `order_ts`, null when not returned |
| `return_reason` | string, nullable | sizing, quality, not_as_described, changed_mind, damaged_in_transit |
| `country` | string | ISO-2, matches the session's country |
| `payment_method` | string | card, paypal, klarna, apple_pay |

**On returns.** `line_revenue` is deliberately gross. Net revenue requires filtering
on `is_returned`, and nothing in the column name warns you. This is the single most
useful trap in the dataset for the AI module: an agent that writes the obvious
query gets a defensibly wrong answer, and an agent that explores the schema first
does not. See F6.

**Generation order matters.** Build the clickstream first, then derive orders from
its purchase events. Do not generate the two independently. Exactly one order line
per `purchase` event, so the row counts reconcile and a student who counts
purchases in Databricks and rows in Postgres gets the same number.

No campaign column. See section 0.

---

## 4. Clickstream (Databricks)

2,000,000 events across ~180,000 sessions, averaging ~11 events per session.
Six Parquet files partitioned by month.

### Column naming: deliberately raw

Postgres and S3 use clean, self-describing column names. The clickstream does not.
It uses the abbreviated naming a real analytics export actually arrives with.

| Column | Type | Notes |
|---|---|---|
| `evt_id` | int64 | sequential, globally ordered by `evt_ts` |
| `evt_ts` | timestamp(ms) | within the fixed window |
| `sess_id` | int64 | ~180,000 distinct |
| `uid` | int64 | ~130,000 distinct, so some users return |
| `evt_type` | string | enum, see below |
| `prd_id` | int32, nullable | null on `page_view` of non-product pages |
| `cmpgn_id` | string, nullable | null for direct and organic sessions |
| `src` | string, nullable | utm source. Null when `cmpgn_id` is null |
| `med` | string, nullable | utm medium: cpc, paid_social, affiliate |
| `dvc` | string | desktop, mobile, tablet |
| `cntry` | string | ISO-2 |
| `pg_path` | string | ~50 distinct values |
| `ref` | string, nullable | ~15 distinct values |

This is not decoration. If every source already has perfect column names, the
semantic layer module has nothing to demonstrate, and the MCP module skips the
step where the unified layer is what makes the data legible to an LLM. `src`,
`med` and `dvc` are genuinely ambiguous out of context. The USL resolving them
into `utm_source`, `utm_medium` and `device_type` is the module doing visible
work rather than asserted work.

Keep it mild. Abbreviated, not cryptic. One source, not all three.

**Column names are abbreviated. Values are not.** `evt_type` holds readable words
(`page_view`, `add_to_cart`, `purchase`), not codes. Decided: coded values would
make the same semantic-layer argument a second time while charging the viewer a
decoding tax on every result set for 60 minutes.

### Event types and funnel

`page_view`, `product_view`, `add_to_cart`, `remove_from_cart`, `checkout_start`,
`purchase`.

Baseline funnel across all sessions:

- 100% reach `page_view`
- ~62% reach `product_view`
- ~14% reach `add_to_cart`
- ~6% reach `checkout_start`
- ~3.6% reach `purchase`

Sessions are coherent. Events are ordered in time, a `purchase` is always preceded
by `checkout_start` and an `add_to_cart` for that product, and a
`remove_from_cart` only follows an `add_to_cart` for the same product.

### Session-constant attributes

`cmpgn_id`, `src`, `med`, `dvc`, `cntry` are fixed for the
life of a session. This is both realistic (first-touch attribution) and a large
compression win.

### Traffic mix

About 58% of sessions carry a `campaign_id`. The remaining 42% are direct and
organic with nulls in the campaign columns. Do not attribute everything, the
unattributed share is part of what makes the spend analysis honest.

---

## 5. `spend.csv` (S3)

Ten campaigns across four channels. Daily rows per active campaign, roughly 1,200
rows total, split into six monthly files.

| Column | Type | Notes |
|---|---|---|
| `spend_date` | date | |
| `campaign_id` | string | `camp_001` … `camp_010` |
| `campaign_name` | string | |
| `channel` | string | google_ads, meta, tiktok, affiliate |
| `impressions` | int | |
| `clicks` | int | |
| `spend_usd` | numeric(10,2) | |

**Reconciliation:** daily `clicks` for a campaign should be modestly above the
number of sessions that campaign generated that day in the clickstream, landing
in the 85–92% sessions-to-clicks range. Clicks and sessions are genuinely
different things in real life, so an exact match would look fake. A wild
mismatch would look broken.

Campaigns do not all run the full window. Average ~120 active days each, with
staggered start and end dates.

---

## 6. Campaign briefs (S3)

Ten Markdown files, 300–400 words each, one per campaign. Filename pattern
`camp_00N_{slug}.md`.

Each brief contains: campaign ID, name, channel, planned run dates, objective,
target audience, **target categories**, creative angle, and the success metric
the team said they would judge it on.

These are the unstructured half of the S3 source. They exist so the AI module can
do something SQL cannot: read what the campaign said it would do and compare it
against what the numbers say it did.

Write them as a real marketer would. Some vagueness, some overconfidence, a stated
target that does not always survive contact with reality.

### File format: Markdown with minimal YAML frontmatter

Each brief opens with a fenced metadata block, then the prose body:

```markdown
---
campaign_id: camp_002
campaign_name: Base Layer Push
channel: meta
planned_start: 2026-02-10
planned_end: 2026-05-31
---

# Base Layer Push

## Objective
...
```

**Frontmatter stays minimal on purpose.** Identity and scheduling only. The
targeting claims, the stated success metric and the creative angle live in the
prose, because F3 and F6 depend on those being *read* rather than looked up. A
`target_categories: [Apparel]` field would reduce the best finding in the set to
a string comparison.

**No structured companion file.** These are documents, and a marketing brief in a
CSV column would read as theoretical to anyone who has seen a real one. Sunny and
Vinay asked specifically for unstructured data in S3, and Ben's own pitch leads on
unstructured files and RAG-ready data, so text files are what the vendor wants
showcased.

**Open question for Ben, Tuesday:** which S3 file formats can Zetaris register as
a source, and can it treat a folder of text files as a table? If it cannot, the
brief output format is one function in `generate.py` and ten regenerated files.
No joins change, no findings break. Do not pre-compromise the design against this.

---

## 7. Planted findings

Generated data is uniform by default, and a federated query that returns "all
campaigns performed about the same" is a dead demo. These patterns must be built
in deliberately. Each one requires a different combination of sources, which is
the whole argument of the course.

**F1 — The expensive traffic trap.** `camp_004` (TikTok) has the highest spend and
the highest click volume of any campaign, but converts at ~0.4% against the 3.6%
baseline. Worst cost per acquisition by a wide margin.
*Needs: S3 spend + Databricks sessions + Postgres revenue.*

**F2 — The quiet winner.** `camp_009` (affiliate) is nearly invisible on traffic
volume and spend, but converts at ~6.8% with roughly double the baseline average
order value. Best return on ad spend in the set. Anyone looking only at the
clickstream will miss it entirely.
*Needs: all three sources. This is the hero query.*

**F3 — The brief that lied.** `camp_002` (Meta) has a brief explicitly targeting
Apparel. Around 60% of its order lines land in Cooking & Water instead.
The campaign works, just not at what it was aimed at.
*Needs: the S3 brief text plus Postgres category revenue. SQL alone cannot surface
this, which makes it the Claude module's moment.*

**F4 — Seasonality.** Sessions ramp roughly 2.5x from January to June. Tents &
Shelter and Footwear peak hard in May and June. Gives every time-series chart
something to actually show.

**F5 — The mobile drag.** Mobile converts at about half the desktop rate across
all campaigns. `camp_004` is ~90% mobile traffic, which partially explains F1.
A causal chain Claude can find and explain rather than just report.

**F6 — The returns trap.** `camp_007` (google_ads) ranks top three on gross revenue
per dollar spent and eighth of ten on net revenue once returns are deducted. Its
return rate is ~24% against the 8% baseline, concentrated in Footwear with
`return_reason = sizing`. Its brief leans hard on a true-to-size fit promise.

This is the most valuable finding in the set for the AI module, for three reasons.
The obvious query gets it wrong, so there is a visible correction. Catching it
requires noticing that `line_revenue` is gross, which rewards schema exploration
over pattern matching. And the full explanation needs the brief text, so it closes
the loop between the unstructured S3 source and the Postgres numbers.
*Needs: all three sources plus the brief text.*

Keep the effects visible but not cartoonish. A student should be able to spot them
in a query result without the numbers looking hand-placed.

### Why these six, specifically

The common failure of an MCP demo is the agent behaving as a SQL translator. One
question, one query, one answer, and the viewer concludes they could have written
that themselves.

These findings are built so the interesting questions take three or four hops.
F1 raises a *why* that F5 answers. F6 inverts the answer F1 and F2 suggest. F3 and
F6 both need text that no amount of SQL will produce. And the 42% unattributed
traffic from section 4 means campaign revenue never sums to total revenue, so any
agent doing the arithmetic honestly has to discover the gap and say so.

Before shooting, verify that the headline questions genuinely need more than one
query. If a single statement answers everything, the demo undersells the product
no matter how good the product is.

---

## 7b. What the semantic layer exposes

The MCP server hands Claude the datamart, not the raw sources. So the datamart
design is part of the deliverable, and the data has to support a clean one.

Target datamart `DM_MARKETING_PERFORMANCE`:

| Object | Source | Purpose |
|---|---|---|
| `dim_product` | Postgres | catalog, category tree, price, cost |
| `fct_order_lines` | Postgres | gross and net revenue, returns |
| `fct_events` | Databricks | raw clickstream, columns renamed |
| `fct_sessions` | Databricks | one row per session, funnel flags, first-touch campaign |
| `fct_campaign_spend` | S3 | daily spend, impressions, clicks |
| `dim_campaign_brief` | S3 | brief documents: frontmatter plus full prose body |

Two things this layer must do, because they are the argument for its existence:

1. **Rename the clickstream.** `src` to `utm_source`, `dvc` to `device_type`, and
   so on. An LLM reading `med` guesses. An LLM reading `utm_medium` knows.
2. **Expose `net_revenue` as a derived field** alongside gross. Not to defuse F6,
   but to show the fix: once the semantic layer defines net revenue once,
   every downstream tool and agent gets it right by default. That is a
   better argument for a semantic layer than any slide.

`fct_sessions` should be a layer-level aggregation over `fct_events`, not a
generated file. Building it in the USL rather than shipping it means the
semantic layer module has something real to construct on camera.

---

## 8. Validation

The generator ends with a validation pass that prints pass or fail per check and
exits non-zero on any failure. Do not skip this, the reconciliation checks are the
difference between a demo that holds up on camera and one that falls apart when a
viewer runs their own count.

1. Clickstream `purchase` event count equals `orders.csv` row count exactly.
2. Every `orders.session_id` exists in the clickstream.
3. Every `orders.product_id` exists in `products.csv`.
4. Every `orders.order_ts` equals the `event_ts` of its source purchase event.
5. No `orders` row carries a campaign reference of any kind.
6. Clickstream sessions fall within 85–92% of `spend.csv` clicks, asserted at two
   levels: on every campaign-day with at least 6 sessions, and on each campaign's
   full-window total. Days below 6 sessions are counted and reported but not
   asserted, because 1–5 sessions have no integer click count inside the band
   (5/6 = 83%, 5/5 = 100%). Generation still applies the ratio on every day,
   small ones included; only the assertion skips them.
7. Every `campaign_id` in the clickstream has both a spend file entry and a brief.
8. All event timestamps fall inside 2026-01-01 to 2026-06-30.
9. Within every session, events are time-ordered and funnel-valid.
10. No nulls in any non-nullable column.
11. Each planted finding F1 through F6 is present at the stated magnitude, checked
    by an actual query against the generated data rather than by assumption.
12. Printed file sizes are no more than 20% above the targets in section 1.
    Smaller is always fine.
13. Returns: `is_returned` is true for ~8% of lines overall and ~24% of `camp_007`
    lines. `return_ts` is null exactly when `is_returned` is false, and otherwise
    falls 5–30 days after `order_ts`.
14. Ranking inversion holds: `camp_007` sits in the top three by gross revenue per
    dollar spent and outside the top seven by net. Assert both, this is F6 and it
    silently breaks if any other parameter is retuned.
15. Every campaign has exactly one brief file, its frontmatter parses as valid
    YAML, and `campaign_id` matches the filename and the spend file.

**Sample-size guard (checks 11, 13, 14).** A rate or ranking is only asserted
when the count it rests on reaches 30: orders, order lines, returned lines, or
buyers expected at the target conversion rate. Below that, the check still
prints the measured value, the count, and whether it would have passed, marked
as not asserted, and it does not fail the run. A check where nothing could be
asserted reports SKIP. At 2M every guarded assertion clears the threshold, so
the full run is checked in full. The guard exists so a sample run reads as
"too small to tell" rather than as a false failure, while still showing the
number, so a broken calculation stays distinguishable from a thin sample.

---

## 9. Build order

1. Products.
2. Campaign definitions, including run dates and the F1–F5 parameters.
3. Sessions, with campaign, device, country and timestamp assigned.
4. Events within each session, following the funnel.
5. Orders derived from purchase events.
6. Spend, back-fitted to campaign session counts per day.
7. Briefs, written against the campaign definitions.
8. Validation.
9. Size report.

**Generate at 20,000 events first and inspect the output before scaling to 2M.**
A distribution problem found after a full run costs a lot more than one found in
two seconds.

---

## 10. Implementation notes

Single Python script, `generate.py`, with a `--events` flag defaulting to
2,000,000 so the sample run is one argument away. Polars or pandas plus pyarrow.
No network calls. No dependency on anything outside `requirements.txt`.

**This script does not ship to students.** It hard-codes the planted findings from
section 7, so publishing it alongside the data puts the answer key next to the
exam. Keep it in the internal repo and publish only the generated files, plus a
neutral README describing the data without naming the findings.

Still write it clearly. You will be reading it again in six months when a number
needs retuning.
