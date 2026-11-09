# Northbound Outfitters Dataset

Synthetic e-commerce data for Northbound Outfitters, a direct-to-consumer outdoor gear retailer selling into Europe and North America.

**This data is synthetic.** The company, products, brands, customers, campaigns and partner sites are invented. Any resemblance to real businesses or people is coincidental.

- **Period:** 2026-01-01 to 2026-06-30 inclusive (181 days)
- **Snapshot:** the data reflects the state of every system at the end of 2026-06-30
- **Currency:** USD, two decimal places
- **Timestamps:** UTC, millisecond precision, stored without a time zone

## Sources

The data is split across three platforms. Each one holds the data that platform would hold in a real business.

| Platform | Holds | In a real business |
|---|---|---|
| Postgres | Product catalog, orders | The operational database behind the shop. It records what is sold, to whom, at what price, and whether it came back. |
| Databricks | Website clickstream | The analytics platform where raw behavioural events from the website land: page views, product views, carts and checkouts. |
| S3 | Marketing spend, campaign briefs | The marketing team's file store. It holds daily cost exports from ad platforms and the planning documents written for each campaign. |

## File layout

```text
.
├── postgres/
│   ├── schema.sql                      CREATE TABLE statements for products and orders
│   ├── products.csv
│   └── orders.csv
├── databricks/
│   └── clickstream/
│       ├── month=2026-01/events.parquet
│       ├── ...                         one folder per month
│       └── month=2026-06/events.parquet
└── s3/
    └── marketing/
        ├── spend/
        │   ├── month=2026-01/spend.csv
        │   ├── ...                     one folder per month
        │   └── month=2026-06/spend.csv
        └── briefs/
            ├── camp_001_spring-trail-search.md
            ├── ...                     one file per campaign
            └── camp_010_camp-kitchen.md
```

| Dataset | Rows | Size |
|---|---|---|
| `postgres/products.csv` | 300 | 33 KB |
| `postgres/orders.csv` | 11,192 (6,480 orders) | 1.07 MB |
| `databricks/clickstream/` | 2,000,000 events (180,000 sessions) | 17.0 MB |
| `s3/marketing/spend/` | 1,192 | 73 KB |
| `s3/marketing/briefs/` | 10 files | 22 KB |
| **Total** | | **18.2 MB** |

CSV files are comma-separated with a header row. An empty field is a null. Booleans are written as `true` and `false`.

The clickstream and spend data are partitioned by month, using Hive-style folder names (`month=YYYY-MM`). Most engines read the folder as one table and expose `month` as a column. Clickstream events are partitioned by the month of `evt_ts`, so a session that crosses midnight at the end of a month can appear in two files.

## Join keys

| From | Column | To | Column | Relationship |
|---|---|---|---|---|
| `orders` | `product_id` | `products` | `product_id` | many to one |
| `orders` | `session_id` | clickstream | `sess_id` | many to one: an order line belongs to one session |
| `orders` | `customer_id` | clickstream | `uid` | the same person identifier in both systems |
| clickstream | `prd_id` | `products` | `product_id` | many to one |
| clickstream | `cmpgn_id` | spend | `campaign_id` | many to many: join on campaign, and on date where needed |
| clickstream | `cmpgn_id` | briefs | `campaign_id` (frontmatter) | many to one |
| spend | `campaign_id` | briefs | `campaign_id` (frontmatter) | many to one |

Each `purchase` event in the clickstream corresponds to exactly one row in `orders`. Match them on `orders.session_id = sess_id` and `orders.product_id = prd_id`. The order's `order_ts` equals the event's `evt_ts`.

All identifiers are integers except `campaign_id` / `cmpgn_id`, which are strings of the form `camp_001`.

## Data dictionary

### Postgres: `products.csv`

One row per product in the catalog.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `product_id` | integer | no | Primary key, 1001 to 1300. |
| `sku` | text | no | Stock keeping unit, `NBO-{category code}-{number}`, e.g. `NBO-TNT-0001`. Unique. |
| `product_name` | text | no | Display name: brand, model and descriptor. |
| `category` | text | no | One of six top-level categories (see below). |
| `subcategory` | text | no | One of three subcategories within the category (see below). |
| `brand` | text | no | Manufacturer brand. 12 brands in total. |
| `unit_price` | numeric(10,2) | no | Current list price in USD, before any discount. |
| `unit_cost` | numeric(10,2) | no | Cost to Northbound per unit, in USD. |
| `launch_date` | date | no | Date the product was first offered for sale. Ranges from 2023 to June 2026. |
| `is_active` | boolean | no | Whether the product is currently offered for sale. |

Category tree:

| Category | Subcategories |
|---|---|
| Tents & Shelter | Tents, Tarps, Footprints |
| Backpacks | Daypacks, Hiking Packs, Travel Packs |
| Sleep Systems | Sleeping Bags, Sleeping Pads, Pillows |
| Footwear | Hiking Boots, Trail Runners, Sandals |
| Apparel | Shell Jackets, Base Layers, Trousers |
| Cooking & Water | Stoves, Cookware, Water Filters |

### Postgres: `orders.csv`

One row per order line. An order with three different products has three rows sharing one `order_id`.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `order_line_id` | integer | no | Primary key, sequential. |
| `order_id` | integer | no | Order identifier. Repeats across the lines of the same order. |
| `order_ts` | timestamp(3) | no | Time the order was placed. |
| `customer_id` | integer | no | Customer identifier. Same value as `uid` in the clickstream. |
| `session_id` | integer | no | Website session in which the order was placed. Same value as `sess_id` in the clickstream. |
| `product_id` | integer | no | Product ordered. Foreign key to `products.product_id`. |
| `quantity` | integer | no | Units of the product on this line: 1, 2 or 3. |
| `unit_price` | numeric(10,2) | no | Price charged per unit on this line, after discount. |
| `discount_pct` | numeric(5,2) | no | Discount applied to the list price, in percent. 0 when no discount applied. |
| `line_revenue` | numeric(10,2) | no | Revenue for the line at the time of sale: `quantity * unit_price`, rounded to cents. |
| `is_returned` | boolean | no | Whether the line has been returned. |
| `return_ts` | timestamp(3) | yes | Time the return was received. Null when `is_returned` is false. |
| `return_reason` | text | yes | Reason given for the return: `sizing`, `quality`, `not_as_described`, `changed_mind`, `damaged_in_transit`. Null when `is_returned` is false. |
| `country` | char(2) | no | ISO 3166-1 alpha-2 country of the customer. 14 countries in Europe and North America. |
| `payment_method` | text | no | `card`, `paypal`, `klarna` or `apple_pay`. One method per order. |

`schema.sql` contains the matching `CREATE TABLE` statements, including the primary keys and the foreign key from `orders.product_id` to `products.product_id`.

### Databricks: `clickstream/month=*/events.parquet`

One row per event on the website. Parquet, snappy-compressed.

The clickstream uses abbreviated column names, as raw analytics exports often do. The Postgres and S3 sources use full names. The descriptions below give the meaning of each abbreviation.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `evt_id` | int64 | no | Event ID. Sequential, ordered by `evt_ts`. |
| `evt_ts` | timestamp(ms) | no | Event timestamp. |
| `sess_id` | int64 | no | Session ID. A session is one visit to the website. |
| `uid` | int64 | no | User ID. The same user can have several sessions. Matches `orders.customer_id`. |
| `evt_type` | string | no | Event type: `page_view`, `product_view`, `add_to_cart`, `remove_from_cart`, `checkout_start`, `purchase`. |
| `prd_id` | int32 | yes | Product ID for product-level events. Null on `page_view` and `checkout_start`. |
| `cmpgn_id` | string | yes | Campaign ID (`camp_001` to `camp_010`) the session arrived from. Null for sessions not attributed to a campaign. |
| `src` | string | yes | UTM source: the site or platform that sent the session, e.g. `google`, `facebook`. Null when `cmpgn_id` is null. |
| `med` | string | yes | UTM medium: `cpc`, `paid_social` or `affiliate`. Null when `cmpgn_id` is null. |
| `dvc` | string | no | Device type: `desktop`, `mobile` or `tablet`. |
| `cntry` | string | no | ISO 3166-1 alpha-2 country of the visitor. |
| `pg_path` | string | no | Path of the page the event happened on. 51 distinct values (see below). |
| `ref` | string | yes | Referrer domain. On the first event of a session it is the external site the visitor came from, null if there was none. On later events it is `northboundoutfitters.com`. |

`uid`, `cmpgn_id`, `src`, `med`, `dvc` and `cntry` are constant within a session.

Event types:

| `evt_type` | Meaning | `prd_id` |
|---|---|---|
| `page_view` | A non-product page was viewed | null |
| `product_view` | A product detail page was viewed | set |
| `add_to_cart` | A product was added to the cart | set |
| `remove_from_cart` | A product was removed from the cart | set |
| `checkout_start` | The visitor started checkout | null |
| `purchase` | An order was placed. One event per product in the order, all with the same timestamp. | set |

`pg_path` patterns:

| Pattern | Page |
|---|---|
| `/` | Home page |
| `/c/{category}` | Category listing, e.g. `/c/backpacks` |
| `/c/{category}/{subcategory}` | Subcategory listing, e.g. `/c/backpacks/daypacks` |
| `/product/{category}` | Product detail page, grouped by category. The product itself is in `prd_id`. |
| `/lp/{name}` | Campaign landing page |
| `/cart`, `/checkout`, `/checkout/confirmation` | Cart and checkout |
| `/search`, `/sale`, `/new-arrivals`, `/wishlist` | Search and merchandising pages |
| `/account`, `/account/orders` | Customer account |
| `/journal`, `/journal/gear-guides`, `/journal/trip-reports` | Editorial content |
| `/help/shipping`, `/help/returns`, `/help/size-guide`, `/about` | Help and company pages |

### S3: `marketing/spend/month=*/spend.csv`

One row per campaign per day the campaign was running. Campaigns run over different date ranges within the period.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `spend_date` | date | no | Day the spend applies to. |
| `campaign_id` | string | no | Campaign ID, `camp_001` to `camp_010`. |
| `campaign_name` | string | no | Campaign name. |
| `channel` | string | no | Ad channel: `google_ads`, `meta`, `tiktok` or `affiliate`. |
| `impressions` | integer | no | Ad impressions reported by the channel for the day. |
| `clicks` | integer | no | Ad clicks reported by the channel for the day. |
| `spend_usd` | numeric(10,2) | no | Amount spent on the campaign that day, in USD. |

### S3: `marketing/briefs/*.md`

One campaign brief per campaign, written by the marketing team before launch. File names follow the pattern `{campaign_id}_{slug}.md`.

Each file is Markdown that opens with a YAML frontmatter block between `---` lines:

```markdown
---
campaign_id: camp_001
campaign_name: Spring Trail Search
channel: google_ads
planned_start: 2026-01-05
planned_end: 2026-04-30
---

# Spring Trail Search

## Objective
...
```

The frontmatter holds identity and scheduling only:

| Field | Type | Description |
|---|---|---|
| `campaign_id` | string | Campaign ID. Matches `campaign_id` in spend and `cmpgn_id` in the clickstream. |
| `campaign_name` | string | Campaign name. Matches `campaign_name` in spend. |
| `channel` | string | Ad channel. Matches `channel` in spend. |
| `planned_start` | date | Planned first day of the campaign. |
| `planned_end` | date | Planned last day of the campaign. |

Everything else is in the Markdown body: the campaign plan as written by the marketing team, in free text under section headings.

## Loading the data

_To be added._
