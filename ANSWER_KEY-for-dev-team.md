# Northbound Dataset: Answer Key

Oct 9, 2026 · @Andreas

Six findings are planted in the Northbound Outfitters course data, and each one needs at least two of the three sources to surface. This doc is the answer key for the dev team: what is planted, the numbers it came out at in the full 2M-event build, and where else the data is worth poking.

## Ground rules

This doc, `generate.py` and `DATA_SPEC.md` stay in the internal repo. Only the generated files and the neutral `README.md` ship to students.

- **Never publish** `generate.py`, `DATA_SPEC.md` or this doc next to the data. All three name the findings.
- **Don't quote numbers from this doc in student material.** Let the agent or the student discover them on camera.
- **Don't hint in the README.** It is deliberately silent on per-month counts, brief section names and anything comparative.
- **Everything here comes from the 2M build:** seed 20260101, `python generate.py`. Reruns are byte-identical.

## The six findings at a glance

All six pass validation at 2M with every assertion live. Each needs at least two sources, and F2, F3 and F6 also need the brief text or all three tables.

| # | Finding | Measured at 2M | Postgres | Databricks | S3 spend | S3 briefs |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | Expensive traffic trap: camp_004 (TikTok) has the most spend and clicks, worst CPA | $46,913 spend, 32,354 clicks, 0.40% conversion, CPA $408 vs next worst $63 | yes | yes | yes | |
| F2 | Quiet winner: camp_009 (affiliate) is tiny but has the best ROAS | 1.4% of campaign sessions, 6.78% conversion, AOV 1.89x site, gross ROAS 8.73 | yes | yes | yes | |
| F3 | Brief that lied: camp_002 (Meta) targets Apparel, sells Cooking & Water | 59.9% of its lines are Cooking & Water (42.7% of revenue), Apparel 18.6% | yes | yes | | yes |
| F4 | Seasonality: traffic ramps, Tents and Footwear peak in May to June | Sessions June / Jan 2.52x; Tents line share 7.5% to 21.7%, Footwear 10.7% to 29.0% | yes | yes | | |
| F5 | Mobile drag: mobile converts at about half of desktop; camp_004 is 90% mobile | 0.52x within campaigns (0.41x pooled); camp_004 90.0% mobile | | yes | | |
| F6 | Returns trap: camp_007 (Google) ranks 3rd on gross ROAS, 8th on net | 24.0% return rate, 93% of returns Footwear, 78% of those sizing; gross 4.58 to net 3.48 | yes | yes | yes | yes |

## Each finding in detail

Orders carry no campaign column, so every campaign answer runs `orders.session_id` to `events.sess_id` to `cmpgn_id`, and then on to spend or the brief. Table names below: `orders`, `products` (Postgres), `events` (clickstream), `spend` (S3).

### F1: the expensive traffic trap

1. Which campaign gets the most clicks and spend? camp_004, with 32,354 clicks and $46,913, about 1.8x the next campaign on both.
2. What does it convert at? 0.40% of 28,674 sessions, against 3.60% site-wide.
3. What does an order cost? $408, against $63 for the next worst campaign (camp_008).
4. Why? That question hands off to F5.

```sql
WITH s AS (SELECT sess_id, MAX(cmpgn_id) AS cmpgn_id,
                  MAX(CASE WHEN evt_type = 'purchase' THEN 1 ELSE 0 END) AS bought
           FROM events GROUP BY sess_id)
SELECT s.cmpgn_id, COUNT(*) AS sessions, AVG(bought) AS conversion,
       sp.spend / NULLIF(SUM(bought), 0) AS cpa
FROM s JOIN (SELECT campaign_id, SUM(spend_usd) AS spend FROM spend GROUP BY 1) sp
  ON sp.campaign_id = s.cmpgn_id
GROUP BY s.cmpgn_id, sp.spend;
```

### F2: the quiet winner

1. camp_009 is the smallest campaign: 1,430 sessions (1.4% of campaign traffic) and the lowest spend, $4,030.
2. Yet it converts at 6.78% and its AOV is $362.69, 1.89x the site average of $191.60.
3. Result: the best gross ROAS by far, 8.73 against 4.71 for the runner-up.
4. It needs all three sources: clickstream for attribution, orders for revenue and S3 for spend. Clickstream volume alone ranks it last.

Its buyers spread over 50 products. The most-bought one is only 4.8% of its lines, so no single SKU gives it away.

### F3: the brief that lied

1. The camp_002 brief (Base Layer Push) says its target is Apparel and that it is judged on Apparel order lines.
2. In fact 59.9% of its 564 order lines are Cooking & Water and only 18.6% are Apparel. By revenue, Cooking & Water is 42.7%.
3. The campaign still performs: gross ROAS 4.25, mid-table. It just sells the wrong thing.
4. SQL alone can't find this, because the target only exists in the brief prose. The frontmatter holds no target category.

A nice detail for the AI module: the brief's creative shows a camp scene "with the brew-up going", a plausible reason the audience bought stoves. The brief never mentions Cooking.

### F4: seasonality

- Sessions go from 18,118 in January to 45,647 in June (2.52x).
- Tents & Shelter rises from 7.5% of order lines in January to February to 21.7% in May to June. Footwear rises from 10.7% to 29.0%. Both peak in June.
- Apparel moves the other way: 32.2% of lines in January, 10.4% in June.
- Everything that runs over time shows this, so it is the baseline any trend chart has to explain.

### F5: the mobile drag

1. Within each traffic group, mobile converts at 0.52x of desktop.
2. Pooled across all sessions it looks worse, 0.41x (2.24% vs 5.50%), and 0.35x on campaign traffic. The pooled number is inflated because camp_004 is both 90% mobile and the worst converter.
3. Excluding camp_004, the pooled ratio goes back to 0.51x.
4. Per campaign, mobile sits at 0.40x to 0.60x of desktop everywhere except camp_004, where it is 0.99x (8 buyers from 2,007 desktop sessions, about 15 expected). So inside the current build the mobile mix does not explain any of camp_004's weakness. See Known compromises: this undercuts the F1-to-F5 chain and needs a fix before shooting.

### F6: the returns trap

1. On gross revenue per dollar, camp_007 (Fit Promise Footwear) is 3rd at 4.58.
2. `line_revenue` is revenue at the time of sale. Nothing in the column name says returns aren't netted out.
3. Netting out returns (`WHERE NOT is_returned`) drops it to 3.48, 8th of 10.
4. Its return rate is 24.0% of lines, against 6.8% for the other campaigns. 93% of its returns are Footwear, and 78% of those give the reason `sizing`.
5. Its brief promises "True to size, every time" and says returns are outside the campaign's scorecard. That closes the loop between the brief text and the numbers.

This is the visible correction for the AI module: the obvious query is defensibly wrong, and only schema exploration fixes it.

## Campaign scorecard at 2M

Sorted by gross ROAS. Net ROAS excludes returned lines. Ranks 2 to 7 on net are bunched within 0.44 of each other and can reshuffle if anything is retuned, so course material should quote camp_007's 8th place, never the order of ranks 2 to 7.

| Campaign | Channel | Sessions | Spend (USD) | Orders | Conversion | AOV (USD) | CPA (USD) | Gross ROAS | Net ROAS (rank) | Return rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| camp_009 Expedition Partners | affiliate | 1,430 | 4,029.85 | 97 | 6.78% | 362.69 | 41.54 | 8.73 | 8.03 (1) | 6.6% |
| camp_006 Trail Review Partners | affiliate | 11,304 | 20,730.11 | 497 | 4.40% | 196.46 | 41.71 | 4.71 | 4.42 (2) | 6.6% |
| camp_007 Fit Promise Footwear | google_ads | 10,675 | 19,799.43 | 459 | 4.30% | 197.56 | 43.14 | 4.58 | 3.48 (8) | 24.0% |
| camp_001 Spring Trail Search | google_ads | 9,882 | 15,988.40 | 415 | 4.20% | 172.21 | 38.53 | 4.47 | 4.15 (3) | 7.0% |
| camp_003 Shelter Season | google_ads | 11,675 | 25,306.89 | 467 | 4.00% | 238.44 | 54.19 | 4.40 | 4.13 (4) | 6.4% |
| camp_010 Camp Kitchen | meta | 7,644 | 11,280.29 | 298 | 3.90% | 164.28 | 37.85 | 4.34 | 4.07 (5) | 6.2% |
| camp_005 Sleep Warm | meta | 5,155 | 7,775.11 | 196 | 3.80% | 170.18 | 39.67 | 4.29 | 4.03 (6) | 7.1% |
| camp_002 Base Layer Push | meta | 8,945 | 10,366.80 | 322 | 3.60% | 136.83 | 32.20 | 4.25 | 3.98 (7) | 5.5% |
| camp_008 Packed & Ready | tiktok | 8,771 | 18,301.61 | 289 | 3.29% | 197.58 | 63.33 | 3.12 | 2.93 (9) | 5.9% |
| camp_004 Trailhead Stories | tiktok | 28,674 | 46,913.30 | 115 | 0.40% | 172.82 | 407.94 | 0.42 | 0.39 (10) | 7.5% |
| No campaign (direct, organic) | | 75,845 | | 3,325 | 4.38% | 190.04 | | | | 7.0% |

Totals: 180,000 sessions, 6,480 orders, 11,192 lines, 8.0% of lines returned. Campaigns carry 57.9% of sessions but only 49.1% of gross revenue. That gap is the unattributed share an honest agent has to name.

## Traps and other things worth looking at

These aren't graded findings, but each one trips up an agent or a student who doesn't explore first. Several are good on-camera moments.

| Trap | What is true in the data | What a careless query gets wrong |
| --- | --- | --- |
| Gross revenue | `line_revenue` is quantity times discounted unit price at sale time; returns are only in `is_returned` | Reports gross as revenue; F6 inverts |
| No campaign in orders | Attribution runs `orders.session_id` to `events.sess_id` to `cmpgn_id` | Gives up, or joins on `customer_id` and smears campaigns across a user's sessions |
| Unattributed traffic | 42% of sessions and 51% of gross revenue have no campaign | Sums campaign revenue and calls it total revenue |
| Simpson's paradox on device | Mobile is 0.52x desktop within campaigns, 0.41x pooled | Quotes the pooled gap as the device effect |
| Right-censoring | Lines ordered after 2026-06-25 cannot show a return (snapshot ends 2026-06-30) | Reads late-June return rates as an improvement |
| Clicks are not sessions | Sessions are 85 to 92% of spend clicks per campaign-day | Treats spend clicks as visits, or flags the gap as broken tracking |
| Line vs order grain | `orders` has one row per line; 6,480 orders over 11,192 lines | Counts rows as orders, so AOV comes out ~42% low |
| One purchase event per line | All purchase events of an order share one timestamp; match on (`session_id`, `product_id`) | Joins on timestamp, or on `session_id` alone, and fans out |
| Two prices | `products.unit_price` is list price; `orders.unit_price` is after discount (30% of lines discounted, 5 to 30%) | Rebuilds revenue from list price |
| Users vs sessions | 130,000 users over 180,000 sessions; `customer_id` = `uid` | Treats sessions as customers |
| Raw clickstream names | `src`, `med`, `dvc`, `cntry`, `prd_id`, `cmpgn_id`; `ref` is external only on a session's first event | Guesses `med` or `dvc`; counts `northboundoutfitters.com` as a referrer |
| Month partitions | Partitioned by event month, so a session crossing midnight on a month's last day sits in two files | Counts sessions per file and double counts |
| Product availability | 90 products launch inside the window; 18 inactive products sold until a discontinuation date | Treats zero early sales as a demand signal |

Two campaign-calendar details worth knowing: from January 1 to 4 only camp_006 is live, and the briefs' planned dates match the spend dates exactly. If a later version wants a "plan vs actual" moment, that second one is the place to add it.

## How the generator makes them hold

The findings come from exact quotas and back-fitted spend, not from hoping random draws land, and validation re-reads the files to check them. `python generate.py` builds 2M events in about 7 seconds and exits non-zero if any check fails.

- **Clickstream first, orders derived.** Every `purchase` event becomes exactly one order line, so purchase events and order rows reconcile at 11,192.
- **Exact quotas.** Funnel depth, buyers per campaign, device mix, camp_002's Cooking & Water share and returns per campaign are set as exact counts. The seeded generator only picks *which* sessions or lines get them.
- **Spend is back-fitted.** Daily clicks come from daily sessions at 85 to 92%. Each campaign's total spend = realised gross revenue divided by a target ROAS, so the gross ranking is exact. camp_004 is the exception: it is priced at clicks times a $1.45 CPC, so "highest spend" follows from "highest clicks".
- **camp_009 premium skew.** Its buyers choose only among products at or above the 75th price percentile of each category, with popularity damped. Its category mix leans into Tents and Sleep Systems. The percentile is capped at 0.75 because higher caps concentrate picks on two SKUs.
- **Returns.** 24% of camp_007's lines are returned, weighted 6:1 toward Footwear, with an exact sizing-heavy reason mix. Everyone else shares the rest of an 8% total, in proportion to their category mix. Only lines ordered 5 or more days before the June 30 cutoff can be returned.
- **Sample-size guard.** Below 2M, findings that rest on fewer than 30 orders, lines or expected buyers print as "not asserted" with the measured value, and don't fail the run.

Knobs to retune, all near the top of `generate.py`:

| Knob | Controls | Current value |
| --- | --- | --- |
| `Campaign.cr` | Conversion per campaign | 0.004 (camp_004) to 0.068 (camp_009) |
| `Campaign.roas` | Target gross ROAS; spend is back-fitted to it | 8.73 down to 3.12; camp_004 uses `cpc` instead |
| `Campaign.intensity` | Traffic weight versus other live campaigns | 0.22 (camp_009) to 3.5 (camp_004) |
| `Campaign.devices` | Desktop, mobile, tablet mix | camp_004 0.07 / 0.90 / 0.03 |
| `PURCHASE_DEVICE_WEIGHT` | Mobile vs desktop buying propensity (F5) | 1.0 / 0.5 / 0.75 |
| `CAMP_002_COOKING_SHARE` | F3 line share | 0.60 |
| `CAMP_007_RETURN_RATE`, `BASELINE_RETURN_RATE` | F6 and the overall return rate | 0.24, 0.08 |
| `MAX_PREMIUM_Q` | camp_009 premium floor cap | 0.75 |
| `JUNE_OVER_JANUARY` | F4 traffic ramp | 2.5 |
| `BAND_*`, `MIN_SAMPLE` | Validation tolerances and guard | validation block in generate.py |

After any retune, rerun the full build and read check 14 first: the F6 inversion depends on every other campaign's net ROAS, so it is the one that breaks silently.

## Known compromises and open questions

One item needs a decision before shooting; the rest are documented trade-offs.

- [ ] **F5 chain breaks inside camp_004.** Mobile and desktop convert the same within camp_004 (0.99x: 8 desktop buyers from 2,007 sessions, ~15 expected). Every other campaign shows 0.40x to 0.60x. Proposed fix: split each campaign's buyer quota exactly by device weight, so the device effect is exact everywhere. That changes the random stream, so the whole dataset regenerates and all numbers in this doc move slightly.
- [ ] **Load instructions.** The README has a placeholder until the data has been loaded on each platform.
- [ ] **S3 text as a table.** Still open from the spec: can Zetaris register a folder of Markdown files as a source? If not, only the brief output format changes.

- **F2 AOV is 1.89x, not 2.0x.** Getting closer to 2.0x by price weighting alone needs a stricter premium floor, which puts 35 to 53% of picks on two SKUs. 1.89x is within the 1.6 to 2.4 band.
- **Net ranks 2 to 7 are bunched** (4.42 to 3.98). camp_007's 8th place has a 0.50 margin and is stable; the order above it is not.
- **Right-censoring is faint.** Only orders from June 26 to 30 can't show a return. The monthly return rate barely moves (June 7.8% vs 8.1% earlier), so the effect only shows at day level.
- **Check 6 has 4 campaign-days below the 6-session floor.** Integer clicks can't put 1 to 5 sessions inside 85 to 92%, so those days are reported, not asserted.
- **`checkout_start` has no `prd_id`.** A checkout covers the whole cart. The alternative is one event per cart item.
- **Brief dates match spend dates exactly.** There is no plan-vs-actual drift to discover, which keeps the briefs simple but gives up a possible extra finding.
