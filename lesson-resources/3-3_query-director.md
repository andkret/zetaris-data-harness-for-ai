# 3.3 Query Director: Querying Our Data

## The question

How much revenue did each marketing campaign bring in for every dollar we spent? Run this in **Workbench → SQL Workspace**:

```sql
WITH revenue AS (
  SELECT s.campaign_id, sum(o.revenue) AS revenue
  FROM lightning.metastore.northbound.customer_360.order_line o
  JOIN lightning.metastore.northbound.customer_360.web_session s
    ON o.session_id = s.session_id
  WHERE s.campaign_id IS NOT NULL
  GROUP BY s.campaign_id
),
spend AS (
  SELECT campaign_id, sum(spend_usd) AS spend
  FROM lightning.metastore.northbound.customer_360.campaign_spend
  GROUP BY campaign_id
)
SELECT c.campaign_name,
       c.channel,
       spend.spend,
       revenue.revenue,
       round(revenue.revenue / spend.spend, 2) AS roas
FROM lightning.metastore.northbound.customer_360.campaign c
JOIN spend        ON spend.campaign_id   = c.campaign_id
LEFT JOIN revenue ON revenue.campaign_id = c.campaign_id
ORDER BY roas DESC
```

Revenue and spend are aggregated separately before the join. Joining them directly through sessions would repeat each day's spend for every order line.

## Expected

| Campaign | Channel | ROAS |
|---|---|---:|
| Expedition Partners | affiliate | 8.73 |
| Trail Review Partners | affiliate | 4.71 |
| Fit Promise Footwear | google_ads | 4.58 |
| Spring Trail Search | google_ads | 4.47 |
| Shelter Season | google_ads | 4.40 |
| Camp Kitchen | meta | 4.34 |
| Sleep Warm | meta | 4.29 |
| Base Layer Push | meta | 4.25 |
| Packed & Ready | tiktok | 3.12 |
| Trailhead Stories | tiktok | 0.42 |

## Engines

On the Hobby plan, queries run on **Spark**. Presto, for fast interactive queries, comes with the paid plans.
