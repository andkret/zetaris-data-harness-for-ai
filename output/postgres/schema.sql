-- Northbound Outfitters: Postgres source tables.

CREATE TABLE products (
    product_id    integer       PRIMARY KEY,
    sku           text          NOT NULL UNIQUE,
    product_name  text          NOT NULL,
    category      text          NOT NULL,
    subcategory   text          NOT NULL,
    brand         text          NOT NULL,
    unit_price    numeric(10,2) NOT NULL,
    unit_cost     numeric(10,2) NOT NULL,
    launch_date   date          NOT NULL,
    is_active     boolean       NOT NULL
);

CREATE TABLE orders (
    order_line_id  integer       PRIMARY KEY,
    order_id       integer       NOT NULL,
    order_ts       timestamp(3)  NOT NULL,
    customer_id    integer       NOT NULL,
    session_id     integer       NOT NULL,
    product_id     integer       NOT NULL REFERENCES products (product_id),
    quantity       integer       NOT NULL,
    unit_price     numeric(10,2) NOT NULL,
    discount_pct   numeric(5,2)  NOT NULL,
    line_revenue   numeric(10,2) NOT NULL,
    is_returned    boolean       NOT NULL,
    return_ts      timestamp(3),
    return_reason  text,
    country        char(2)       NOT NULL,
    payment_method text          NOT NULL
);

CREATE INDEX orders_order_id_idx   ON orders (order_id);
CREATE INDEX orders_session_id_idx ON orders (session_id);

-- Load from the dataset root with psql:
-- \copy products FROM 'postgres/products.csv' WITH (FORMAT csv, HEADER true)
-- \copy orders   FROM 'postgres/orders.csv'   WITH (FORMAT csv, HEADER true)
