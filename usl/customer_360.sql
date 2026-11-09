CREATE TABLE product (
  product_id     int PRIMARY KEY,
  sku            string,
  product_name   string,
  category       string,
  subcategory    string,
  brand          string,
  list_price     decimal(10,2),
  unit_cost      decimal(10,2),
  launch_date    date,
  is_active      boolean
);

CREATE TABLE campaign (
  campaign_id    string PRIMARY KEY,
  campaign_name  string,
  channel        string
);

CREATE TABLE web_session (
  session_id      bigint PRIMARY KEY,
  customer_id     bigint,
  campaign_id     string FOREIGN KEY REFERENCES campaign(campaign_id),
  traffic_source  string,
  traffic_medium  string,
  device          string,
  country         string,
  started_at      timestamp
);

CREATE TABLE web_event (
  event_id     bigint PRIMARY KEY,
  session_id   bigint FOREIGN KEY REFERENCES web_session(session_id),
  event_at     timestamp,
  event_type   string,
  product_id   int FOREIGN KEY REFERENCES product(product_id),
  page_path    string,
  referrer     string
);

CREATE TABLE order_line (
  order_line_id   int PRIMARY KEY,
  order_id        int,
  ordered_at      timestamp,
  customer_id     bigint,
  session_id      bigint FOREIGN KEY REFERENCES web_session(session_id),
  product_id      int FOREIGN KEY REFERENCES product(product_id),
  quantity        int,
  unit_price      decimal(10,2),
  discount_pct    decimal(5,2),
  revenue         decimal(10,2),
  is_returned     boolean,
  returned_at     timestamp,
  return_reason   string,
  country         string,
  payment_method  string
);

CREATE TABLE campaign_spend (
  spend_date    date,
  campaign_id   string FOREIGN KEY REFERENCES campaign(campaign_id),
  impressions   int,
  clicks        int,
  spend_usd     decimal(10,2)
)
