# 3.5 Govern What the AI Is Allowed to See

The goal: an agent that can read the semantic layer, but not the raw sources, and not `product.unit_cost`.

## 1. Role

**Management → Roles → +**

| Field | Value |
|---|---|
| Name | `ai_analyst` |
| Level | General |
| Description | `Read-only access for AI agents to the customer_360 semantic layer.` |

**Management → Permissions**, role `AI_ANALYST`: **Unified Semantic Layer → View** → **Save**.

## 2. User

**Management → Users → +**: an email for the agent (e.g. `ai-agents@your-company.com`), a display name and a password. Save, then assign the role `AI_ANALYST` to the user.

## 3. Grant read access to the semantic layer

**Unified Semantic Layer → `northbound` → `customer_360` → Access Control**

1. **Assign Roles** → `AI_ANALYST`
2. **Click the `AI_ANALYST` row**, check **SELECT** on `lightning.metastore.northbound.customer_360.*` → **Apply**

> Assigning the role alone doesn't give access. The SELECT grant does.

The same in SQL:

```sql
GRANT SELECT ON USL NAMESPACE lightning.metastore.northbound.customer_360 TO ROLE 'ai_analyst'
```

## 4. Column policy on `unit_cost`

**`customer_360` → Column Access**, table `product`:

1. **Policy Editor → New Policy**, name `hide_unit_cost`
2. Set `unit_cost` to **DENY** → **Apply Column** → **Save Policies**
3. **Role Policies**, row `ai_analyst`: choose `hide_unit_cost`
4. **Users**, row of your agent user: check that **Role Policy** shows `hide_unit_cost`. If it says *Select…*, choose `hide_unit_cost` there too.
5. **Save Policies** again.

| Option | What it does |
|---|---|
| Grant | Column visible |
| Mask / Encrypt | Values changed |
| Deny | Column stays, values come back empty |
| Hide | Column removed |

> **Known issue:** assigning a policy to a role can reset the user's *Role Policy* field to *Select…*, and then the policy doesn't apply. Always check step 4, and test as the agent user (below) after every change.

## 5. Test as the agent

Log in as the agent user (a private browser window keeps your admin session open) and run:

```sql
SELECT product_name, list_price, unit_cost
FROM lightning.metastore.northbound.customer_360.product
LIMIT 5
```

**Expected:** names and prices, `unit_cost` empty. No error.

```sql
SELECT * FROM shop.orders LIMIT 5
```

**Expected:** a privilege error. The agent can only reach the semantic layer, not the sources.

## 6. API token for the agent

As the agent user: **Management → API Tokens → +**, name it, set an expiry (`+30d`), copy it. It's shown only once. The token carries exactly this user's permissions.

To connect an AI agent with it, see the lessons in chapter 4. The question asked in the video:

```text
Which product categories have the highest margin?
```
