# 2.4 Connect Postgres and S3 to Zetaris

## Before you start

**Wake up Aurora.** It pauses after five minutes without activity, and waking up takes about 15 seconds, longer than Zetaris waits. Run any query first (e.g. the count from lesson 2.3). If a connection times out, that's almost always the reason: wait a few seconds and try again.

## Postgres → `shop`

**Register Data Source → Database**

| Field | Value |
|---|---|
| Database type | PostgreSQL |
| Name | `shop` |
| JDBC URL | `jdbc:postgresql://<your-aurora-cluster-endpoint>:5432/northbound` |
| JDBC driver | `org.postgresql.Driver` (preselected) |
| User | `postgres` |
| Password | your database password |
| Fetch size | `1000` (default) |
| Additional parameter | `sslmode` = `require` |
| Tables | `orders`, `products` (skip the indexes and keys) |

Check in the SQL Workspace:

```sql
SELECT count(*) FROM shop.orders;
```

**Expected:** 11,192

## S3 → `marketing`

**Register Data Source → File Source & API**, create the database:

| Field | Value |
|---|---|
| Database name | `marketing` |
| Description | `Marketing files in S3. Daily ad spend and campaign briefs` |

Then add two tables with **Create Table**. Use the access key of the read-only IAM user from the [S3 guide](../written-guides/2-3_create-an-S3-bucket.md), and leave **Endpoint** and **Session token** empty.

**Table `spend`**

| Field | Value |
|---|---|
| Type | File store |
| File format | CSV |
| Storage provider | Amazon S3 |
| File path | the folder `marketing/spend/` (not a single file), via the folder icon |
| Delimiter | `,` |
| `header` | `true` |
| `inferSchema` | `true` |
| `isS3BucketPublic` | `false` |
| `recursiveFileLookup` | `true` |

> **Don't skip `recursiveFileLookup`.** The spend files sit in folders like `month=2026-01`. Without this parameter, Spark adds an extra `month` column that Zetaris' catalog doesn't know about, which breaks things later.

**Table `briefs`**

| Field | Value |
|---|---|
| Type | File store |
| File format | Markdown |
| Storage provider | Amazon S3 |
| File path | the folder `marketing/briefs/` |
| Scan type | File Scan |
| Path glob filter | `*.md` |

Zetaris catalogs each brief as a document, with type, size and a preview of the content.

Check:

```sql
SELECT count(*) FROM marketing.spend;
```

```sql
SELECT count(*) FROM marketing.briefs;
```

**Expected:** 1,192 and 10
