# 3.4 Configure the Semantic Layer

## Descriptions

Click the **pencil** next to a table or column in `customer_360`. Descriptions can't contain parentheses or colons.

**Model (`customer_360`):**

```text
Northbound Outfitters customer journey from campaign to visit to order, across Postgres, Databricks and S3.
```

**Tables**

| Table | Description |
|---|---|
| `campaign` | `One row per marketing campaign, with its name and ad channel.` |
| `campaign_spend` | `Daily ad spend per campaign, as reported by the ad platform.` |
| `web_session` | `One row per website visit, with the customer, the campaign it came from, device and country.` |
| `web_event` | `Every action on the website, such as page views, product views, add to cart and purchases.` |
| `order_line` | `One row per product in an order. An order with three products has three lines.` |
| `product` | `The product catalog with list price and unit cost.` |

**Columns**

| Column | Description |
|---|---|
| `order_line.revenue` | `Line revenue in USD, quantity times price after discount, before returns.` |
| `order_line.is_returned` | `True if the customer sent this line back.` |
| `order_line.discount_pct` | `Discount applied to the list price, in percent.` |
| `web_session.campaign_id` | `Campaign the visit came from. Empty for visits not attributed to a campaign.` |
| `web_session.traffic_medium` | `How the visitor arrived, cpc, paid_social or affiliate.` |
| `web_session.customer_id` | `The customer, same as customer_id in order_line.` |
| `web_event.event_type` | `page_view, product_view, add_to_cart, remove_from_cart, checkout_start or purchase.` |
| `campaign_spend.spend_usd` | `Ad spend for the campaign on that day, in USD.` |
| `product.unit_cost` | `What Northbound pays per unit. Internal, used for margin.` |

AI agents read these descriptions. In chapter 4, you'll see them quote them back.

## Data quality

**Automatic rules:** every primary and foreign key from the DDL becomes a rule, 11 in total. Open them with **Data Quality** on the canvas.

**Custom rule** on `order_line` (**⋮ → Data Quality → +**):

| Field | Value |
|---|---|
| Rule name | `discount_within_policy` |
| Rule expression | `discount_pct <= 20` |

## Expected

| Rule | Invalid rows | Why |
|---|---:|---|
| `product.product_id` (primary key) | 0 | |
| `order_line.session_id` (foreign key) | 0 | every order belongs to a known visit |
| `web_event.product_id` (foreign key) | 991,916 | page views like the home page aren't about a single product, so there's no product to point to |
| `discount_within_policy` | 497 | order lines with more than 20% discount |

A failed check isn't automatically bad data. Look at the invalid rows before you fix anything.
