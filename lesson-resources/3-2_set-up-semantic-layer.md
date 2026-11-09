# 3.2 Set Up a Semantic Layer

## 1. Namespace

**Unified Semantic Layer → Add Namespace** → `northbound`. Zetaris creates it under `lightning.metastore`.

## 2. The model (DDL)

Open `northbound` → **Create USL**:

- **USL name:** `customer_360`
- **DDL:** paste or upload [`usl/customer_360.sql`](../usl/customer_360.sql)

Six tables with business names, and the relationships as primary and foreign keys. `campaign` and `web_session` don't exist in any source: they're derived during activation and connect everything.

**Description** (click **Add description…** on the model):

```text
Northbound Outfitters customer journey from campaign to visit to order, across Postgres, Databricks and S3.
```

## 3. Activate the tables

Activating tells Zetaris where each table's data comes from. Nothing is copied.

**`product`**: on the table, **⋮ → Activate from Data Source Table**, then drag `shop` → `products` onto it. This works because the columns match one to one.

**All other tables**: **⋮ → Activate from SQL**, paste the query, **Preview**, **Activate**. Only the `SELECT` goes into the dialog.

```sql
-- order_line (from Postgres)
SELECT COALESCE(CAST(order_line_id AS int), 0) AS order_line_id,
       CAST(order_id AS int)                  AS order_id,
       order_ts                               AS ordered_at,
       CAST(customer_id AS bigint)            AS customer_id,
       CAST(session_id AS bigint)             AS session_id,
       CAST(product_id AS int)                AS product_id,
       CAST(quantity AS int)                  AS quantity,
       CAST(unit_price AS decimal(10,2))      AS unit_price,
       CAST(discount_pct AS decimal(5,2))     AS discount_pct,
       CAST(line_revenue AS decimal(10,2))    AS revenue,
       CAST(is_returned AS boolean)           AS is_returned,
       return_ts                              AS returned_at,
       return_reason,
       CAST(country AS string)                AS country,
       payment_method
FROM shop.orders
```

```sql
-- campaign (derived from S3: one row per campaign)
SELECT COALESCE(campaign_id, '') AS campaign_id,
       max(campaign_name)        AS campaign_name,
       max(channel)              AS channel
FROM marketing.spend
GROUP BY campaign_id
```

```sql
-- campaign_spend (from S3)
SELECT CAST(spend_date AS date)          AS spend_date,
       campaign_id,
       CAST(impressions AS int)          AS impressions,
       CAST(clicks AS int)               AS clicks,
       CAST(spend_usd AS decimal(10,2))  AS spend_usd
FROM marketing.spend
```

```sql
-- web_session (derived from Databricks: one row per visit)
SELECT COALESCE(CAST(sess_id AS bigint), 0) AS session_id,
       CAST(max(uid) AS bigint)             AS customer_id,
       max(cmpgn_id)                        AS campaign_id,
       max(src)                             AS traffic_source,
       max(med)                             AS traffic_medium,
       max(dvc)                             AS device,
       max(cntry)                           AS country,
       min(evt_ts)                          AS started_at
FROM website.clickstream
GROUP BY sess_id
```

```sql
-- web_event (from Databricks)
SELECT COALESCE(CAST(evt_id AS bigint), 0) AS event_id,
       CAST(sess_id AS bigint)             AS session_id,
       evt_ts                              AS event_at,
       evt_type                            AS event_type,
       CAST(prd_id AS int)                 AS product_id,
       pg_path                             AS page_path,
       ref                                 AS referrer
FROM website.clickstream
```

## Expected

All six tables turn blue (**6 active**). Row counts:

| Table | Rows |
|---|---:|
| product | 300 |
| campaign | 10 |
| campaign_spend | 1,192 |
| web_session | 180,000 |
| web_event | 2,000,000 |
| order_line | 11,192 |

Check any of them like this:

```sql
SELECT count(*) FROM lightning.metastore.northbound.customer_360.order_line
```

## Known pitfalls

- **Drag-and-drop activation maps columns by position and doesn't cast types.** That's why only `product` uses it. For the others, an error like *"Integer is not a valid external type for schema of bigint"* means: use **Activate from SQL** with the casts above.
- **All columns are nullable on purpose:** activation rejects a `NOT NULL` column fed by a nullable source column.
- If **Preview** fails for `order_line`, activate anyway and check the row count.
