# Lesson Resources

Everything you need to follow along with each lesson: links, settings, SQL and commands to copy, and the results to expect. The videos explain the why. This folder is for copy and paste.

| Lesson | Resources |
|---|---|
| 2.1 Sign Up and Deploy Your Cluster | [2-1](2-1_sign-up-and-deploy-cluster.md) |
| 2.2 Tour the Platform and Set Auto-Suspend | [2-2](2-2_tour-the-platform.md) |
| 2.3 Set Up Sample Data | [2-3](2-3_set-up-sample-data.md) |
| 2.4 Connect Postgres and S3 | [2-4](2-4_connect-postgres-and-s3.md) |
| 2.5 Set Up and Connect Databricks | [2-5](2-5_set-up-and-connect-databricks.md) |
| 3.2 Set Up a Semantic Layer | [3-2](3-2_set-up-semantic-layer.md) |
| 3.3 Query Director: Querying Our Data | [3-3](3-3_query-director.md) |
| 3.4 Configure the Semantic Layer | [3-4](3-4_configure-semantic-layer.md) |
| 3.5 Govern What the AI Is Allowed to See | [3-5](3-5_governance.md) |
| 3.6 Bring the Semantic Layer to Your BI Tool | [3-6](3-6_connect-tableau.md) |
| 4.2 Connect Claude Code | [4-2](4-2_connect-claude-code.md) |
| 4.3 Connect Cursor | [4-3](4-3_connect-cursor.md) |
| 4.4 Connect Codex | [4-4](4-4_connect-codex.md) |
| 4.5 Bonus: Connect Google Antigravity | [4-5](4-5_connect-antigravity.md) |

## Elsewhere in this repository

- [`output/`](../output/): the Northbound Outfitters dataset
- [`usl/customer_360.sql`](../usl/customer_360.sql): the semantic layer model (lesson 3.2)
- [`written-guides/`](../written-guides/): step-by-step setup for AWS S3, Aurora, Databricks and Tableau

## Names used throughout the course

| Thing | Name |
|---|---|
| Postgres source in Zetaris | `shop` |
| S3 source in Zetaris | `marketing` (tables `spend`, `briefs`) |
| Databricks source in Zetaris | `website` (table `clickstream`) |
| Semantic layer | `lightning.metastore.northbound.customer_360` |
| AI agent role | `ai_analyst` |

## When you're done: tear everything down

Zetaris Hobby is free, but AWS keeps billing for the resources in your account, even when the cluster is suspended. When you finish the course, follow the [teardown guide](../written-guides/tear-down-everything.md). In short:

1. **Zetaris:** terminate the cluster, then remove the AWS credentials.
2. **AWS Aurora:** delete the `northbound` database, then its security group.
3. **AWS CloudFormation:** delete the Zetaris stack.
4. **AWS S3:** empty and delete the stack's workspace bucket and your marketing bucket.
5. **AWS IAM:** delete the read-only user.
6. **Databricks:** delete the service principal for Zetaris.
7. **Check your bill** for the next few days. On day 1 the total still goes up (the teardown day arrives with a delay). From day 2 on, it should stop climbing.
