-- Sales database of Helix Pharma Distribution (fictional).
--
-- This file is used twice:
--   1. app/db/seed.py runs it to create the SQLite database.
--   2. app/agents/sql_agent.py shows it, comments included, to the LLM as the
--      schema description. The comments are the model's documentation, so
--      keep them accurate when you change a column.

-- Medicines the company sells.
CREATE TABLE products (
    product_id          INTEGER PRIMARY KEY,
    name                TEXT    NOT NULL,  -- generic name + strength, e.g. 'Atorvastatin 20 mg tablets'
    category            TEXT    NOT NULL,  -- 'antibiotic' | 'analgesic' | 'cardiovascular' | 'diabetes' | 'vaccine' | 'biologic'
    unit_price          INTEGER NOT NULL,  -- current list price of one pack, in Iranian rials (IRR)
    requires_cold_chain INTEGER NOT NULL   -- 1 = must be stored at 2-8 °C, 0 = room temperature
);

-- Pharmacies, hospitals and clinics that buy from the company.
CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    name          TEXT    NOT NULL,
    customer_type TEXT    NOT NULL,  -- 'pharmacy' | 'hospital' | 'clinic'
    city          TEXT    NOT NULL,  -- English spelling: 'Tehran', 'Isfahan', 'Shiraz', 'Mashhad', 'Tabriz'
    credit_limit  INTEGER NOT NULL   -- maximum open (unpaid) balance allowed, in IRR
);

-- One row per order (an order can contain several products).
CREATE TABLE orders (
    order_id       INTEGER PRIMARY KEY,
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date     TEXT    NOT NULL,  -- ISO date 'YYYY-MM-DD'; data covers 2026-01-01 .. 2026-09-30
    status         TEXT    NOT NULL,  -- 'delivered' | 'returned' | 'cancelled'
    payment_status TEXT    NOT NULL   -- 'paid' | 'unpaid' for delivered orders; 'not_applicable' for returned/cancelled
);

-- Order lines. Sales / revenue = SUM(quantity * unit_price) over delivered orders only.
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,  -- number of packs
    unit_price    INTEGER NOT NULL   -- price actually charged per pack in IRR (hospitals get 5% off list price)
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
