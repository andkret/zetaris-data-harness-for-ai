# 2.5 Set Up and Connect Databricks

## Links

- Written guide: [Set up Databricks Free Edition and a service principal for Zetaris](../written-guides/2-5_set-up-databricks-free-edition.md)
- The clickstream data: [`output/databricks/clickstream/`](../output/databricks/clickstream/)

## Databricks: load the clickstream

1. **Catalog** → `workspace` → **Create schema** `northbound`
2. In `northbound`: **Create → Volume** `raw`
3. Upload the `clickstream` folder from `output/databricks/` into the volume.

Turn the files into a table, in the **SQL Editor** with the **Serverless Starter Warehouse**:

```sql
CREATE OR REPLACE TABLE workspace.northbound.clickstream AS
SELECT
  evt_id,
  CAST(evt_ts AS TIMESTAMP) AS evt_ts,
  sess_id,
  uid,
  evt_type,
  prd_id,
  cmpgn_id,
  src,
  med,
  dvc,
  cntry,
  pg_path,
  ref,
  month
FROM read_files('/Volumes/workspace/northbound/raw/', format => 'parquet');
```

> **Why the `CAST`?** The Parquet files store timestamps without a time zone, so Databricks reads them as `TIMESTAMP_NTZ`. Many tools reading through JDBC don't support that type yet, and Zetaris silently drops the column. Casting to `TIMESTAMP` fixes it.

Check:

```sql
SELECT count(*) FROM workspace.northbound.clickstream;
```

**Expected:** 2,000,000

Give the service principal read access (use your service principal's client ID):

```sql
GRANT USE CATALOG ON CATALOG workspace TO `<client-id>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.northbound TO `<client-id>`;
```

## Zetaris → `website`

**Register Data Source → Database**, type **Databricks**, name `website`.

**JDBC URL** (from your warehouse's **Connection details**):

```text
jdbc:databricks://<server-hostname>:443/northbound;httpPath=<http-path>;AuthMech=11;Auth_Flow=1;ConnCatalog=workspace;OAuth2ClientId=<client-id>;OAuth2Secret=<secret>
```

- The schema `northbound` goes **right after the port**. That's where Zetaris looks for it.
- `AuthMech=11` + `Auth_Flow=1` = OAuth with the service principal's client ID and secret.
- Leave **Username** and **Password** empty.
- Zetaris masks the URL after saving.

Check in the SQL Workspace:

```sql
SELECT evt_type, count(*) AS events
FROM website.clickstream
GROUP BY evt_type
ORDER BY events DESC;
```

**Expected:** about a million page views, down to **11,192 purchases**, the same number as the order lines in Postgres.

## Known pitfalls

| Error | Fix |
|---|---|
| `No suitable driver` | The URL needs `jdbc:databricks://`, with both slashes. |
| Unknown host | Copy the full server hostname, including the `dbc-…` prefix. |
| `No tables found` | Put `/northbound` right after `:443`. |
| `401` | Use the OAuth parameters in the URL, not username and password. |
| "No existing owner" when giving warehouse permissions | Click the cog icon in the permissions dialog → **Assign new owner** → yourself, then save again. |
