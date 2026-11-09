# 3.6 Bring the Semantic Layer to Your BI Tool

BI tools can't see the semantic layer directly. So we publish a metric as a view on top of it, and put the view into a data mart, which Tableau sees as a schema.

## Links

- Written guide: [Connect Tableau to Zetaris Cloud](../written-guides/3-6_create-zetaris-tableau-connection.md) (driver, truststore, properties file, connection)

## 1. Publish the metric as a view

In **Workbench → SQL Workspace**, one statement at a time.

A container, the folder for published views:

```sql
CREATE SCHEMASTORE CONTAINER marketing_metrics
```

The view: the ROAS query from lesson 3.3, without the `ORDER BY`. It reads only from the semantic layer:

```sql
CREATE SCHEMASTORE VIEW campaign_roas WITH CONTAINER marketing_metrics AS
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
```

Check:

```sql
SELECT * FROM marketing_metrics.campaign_roas
```

**Expected:** 10 rows, Expedition Partners at 8.73.

## 2. Put it into a data mart

**Virtual Data Mart → Create Data Mart**

| Field | Value |
|---|---|
| Name | `marketing_reports` |
| Description | `Published marketing metrics for BI tools, built on the customer_360 semantic layer.` |

Drag `marketing_metrics` → `campaign_roas` from the Data Explorer onto the canvas, then click **Save**.

> The **Save** button only appears after you've added a table. Without saving, the mart stays empty, and Tableau shows no tables.

## 3. In Tableau

Connect as described in the [written guide](../written-guides/3-6_create-zetaris-tableau-connection.md), then:

1. **Schema:** `marketing_reports`, drag `campaign_roas` onto the canvas
2. **Sheet 1:** `Campaign Name` → Rows, `roas` → Columns
3. Toolbar: **Sort Descending**, **Show Mark Labels** (the **T**)
4. `Channel` → **Color**

If the view changes later, refresh the data source in Tableau.
