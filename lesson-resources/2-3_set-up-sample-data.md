# 2.3 Set Up Sample Data

## Links

- The dataset: [`output/`](../output/) in this repository, described in [`output/README.md`](../output/README.md)
- Written guide: [Create an S3 bucket and read-only credentials](../written-guides/2-3_create-an-S3-bucket.md)
- Written guide: [Create an Aurora PostgreSQL database](../written-guides/2-3_create-aurora-postgres-db.md)

## S3: upload the marketing data

Upload the folder `output/s3/marketing` to your bucket.

> **Mac users:** Finder creates hidden `.DS_Store` files, and they'd end up in your data. Either select them in the upload list and click **Remove**, or delete them first, in a terminal from the repository root:
> ```bash
> find output -name .DS_Store -delete
> ```

You should end up with 16 files: 6 spend files (one per month) and 10 briefs.

## Aurora: create and load the tables

Run these in a terminal **in the `output` folder**. The first two commands come from AWS: **Aurora and RDS → DB clusters → `northbound-postgres` → Connectivity & security**.

Download AWS' certificate bundle, so the connection is verified, not just encrypted:

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

Store your database endpoint:

```bash
export RDSHOST="<your-aurora-cluster-endpoint>"
```

Create the tables `products` and `orders`:

```bash
psql "host=$RDSHOST port=5432 dbname=northbound user=postgres sslmode=verify-full sslrootcert=./global-bundle.pem" -f postgres/schema.sql
```

Load the data. Products first, because every order points to a product:

```bash
psql "host=$RDSHOST port=5432 dbname=northbound user=postgres sslmode=verify-full sslrootcert=./global-bundle.pem" \
  -c "\copy products FROM 'postgres/products.csv' WITH (FORMAT csv, HEADER true)" \
  -c "\copy orders FROM 'postgres/orders.csv' WITH (FORMAT csv, HEADER true)"
```

Check:

```bash
psql "host=$RDSHOST port=5432 dbname=northbound user=postgres sslmode=verify-full sslrootcert=./global-bundle.pem" \
  -c "SELECT count(*) FROM orders;"
```

**Expected:** `COPY 300`, `COPY 11192`, and a count of **11,192** order lines.

`global-bundle.pem` is in this repository's `.gitignore`.

## Start over

If you need to reload the data, drop both tables and run the commands again:

```bash
psql "host=$RDSHOST port=5432 dbname=northbound user=postgres sslmode=verify-full sslrootcert=./global-bundle.pem" \
  -c "DROP TABLE IF EXISTS orders, products CASCADE;"
```
