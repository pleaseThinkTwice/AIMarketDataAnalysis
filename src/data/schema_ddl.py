"""DDL statements for the 12-table e-commerce analytics schema.

Tables are organized into four categories:
    - Master data: users, skus, categories
    - Transactions: orders, order_items, payments
    - After-sales: returns, return_reasons
    - Behavior: page_views, add_to_cart, reviews, customer_service_tickets

Plus one dimension table:
    - dim_order_status (enum code lookup, injected noise)

All timestamps are stored as TIMESTAMP WITHOUT TIME ZONE (UTC).
The schema assumes PostgreSQL 16.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Drop-all (for teardown / reset)
# ---------------------------------------------------------------------------

DROP_ALL_SQL = """
DROP TABLE IF EXISTS customer_service_tickets CASCADE;
DROP TABLE IF EXISTS reviews CASCADE;
DROP TABLE IF EXISTS add_to_cart CASCADE;
DROP TABLE IF EXISTS page_views CASCADE;
DROP TABLE IF EXISTS returns CASCADE;
DROP TABLE IF EXISTS return_reasons CASCADE;
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS dim_order_status CASCADE;
DROP TABLE IF EXISTS skus CASCADE;
DROP TABLE IF EXISTS categories CASCADE;
DROP TABLE IF EXISTS users CASCADE;
"""

# ---------------------------------------------------------------------------
# Create-all (execution order respects FK dependencies)
# ---------------------------------------------------------------------------

CREATE_ALL_SQL = """
-- =========================================================================
-- 1. MASTER DATA
-- =========================================================================

-- 1a. Categories (product category hierarchy)
CREATE TABLE categories (
    category_id        SERIAL PRIMARY KEY,
    category_name      VARCHAR(200)  NOT NULL,
    category_name_en   VARCHAR(200),               -- English name (from Olist)
    parent_category_id INT REFERENCES categories(category_id),
    is_deleted         SMALLINT NOT NULL DEFAULT 0  -- soft-delete flag
);

-- 1b. SKUs / Products
CREATE TABLE skus (
    sku_id             VARCHAR(64) PRIMARY KEY,    -- Olist product_id
    category_id        INT NOT NULL REFERENCES categories(category_id),
    product_name       VARCHAR(500),
    product_name_cn    VARCHAR(500),               -- Chinese name (Faker augmented)
    weight_g           NUMERIC(10,2),
    length_cm          NUMERIC(10,2),
    height_cm          NUMERIC(10,2),
    width_cm           NUMERIC(10,2),
    price              NUMERIC(10,2),
    is_deleted         SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX idx_skus_category ON skus(category_id);

-- 1c. Users / Customers
CREATE TABLE users (
    user_id            VARCHAR(64) PRIMARY KEY,    -- Olist customer_id
    user_unique_id     VARCHAR(64) NOT NULL UNIQUE,-- Olist customer_unique_id
    zip_code_prefix    VARCHAR(10),
    city               VARCHAR(200),
    state              VARCHAR(10),
    -- PII fields (marked sensitive, not exposed to LLM)
    phone              VARCHAR(30),
    email              VARCHAR(200),
    address            VARCHAR(500),
    is_deleted         SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX idx_users_state ON users(state);
CREATE INDEX idx_users_city ON users(city);

-- =========================================================================
-- 1d. DIMENSION: Order Status (enum-code noise -- LLM must JOIN to decode)
-- =========================================================================
CREATE TABLE dim_order_status (
    status_code        INT PRIMARY KEY,            -- 1, 2, 3, 4
    status_name        VARCHAR(50) NOT NULL,       -- delivered, shipped, cancelled, processing
    status_name_cn     VARCHAR(50) NOT NULL        -- Chinese label
);
INSERT INTO dim_order_status (status_code, status_name, status_name_cn) VALUES
    (1, 'delivered',  '已交付'),
    (2, 'shipped',    '已发货'),
    (3, 'cancelled',  '已取消'),
    (4, 'processing', '处理中');

-- =========================================================================
-- 2. TRANSACTIONS
-- =========================================================================

-- 2a. Orders
CREATE TABLE orders (
    order_id           VARCHAR(64) PRIMARY KEY,    -- Olist order_id
    user_id            VARCHAR(64) NOT NULL REFERENCES users(user_id),
    order_status       INT NOT NULL DEFAULT 1 REFERENCES dim_order_status(status_code),
    created_at         TIMESTAMP NOT NULL,          -- UTC!
    delivered_at       TIMESTAMP,
    estimated_delivery_date TIMESTAMP,
    amount             NUMERIC(12,2) NOT NULL,      -- Gross amount (incl. tax) = "销售额"
    -- NOTE: amount differs from payments.amount (net after discounts)
    is_deleted         SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_orders_created ON orders(created_at);
CREATE INDEX idx_orders_status ON orders(order_status);

-- 2b. Order Items
CREATE TABLE order_items (
    order_item_id      SERIAL PRIMARY KEY,
    order_id           VARCHAR(64) NOT NULL REFERENCES orders(order_id),
    sku_id             VARCHAR(64) NOT NULL REFERENCES skus(sku_id),
    quantity           INT NOT NULL DEFAULT 1,
    unit_price         NUMERIC(10,2) NOT NULL,
    freight_value      NUMERIC(10,2) DEFAULT 0,
    is_deleted         SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_sku ON order_items(sku_id);

-- 2c. Payments
CREATE TABLE payments (
    payment_id         SERIAL PRIMARY KEY,
    order_id           VARCHAR(64) NOT NULL REFERENCES orders(order_id),
    payment_sequential INT NOT NULL DEFAULT 1,      -- installment number
    payment_type       VARCHAR(50),                  -- credit_card, boleto, voucher, debit_card
    payment_installments INT DEFAULT 1,
    amount             NUMERIC(10,2) NOT NULL,       -- Net paid amount = "实收"
    -- NOTE: orders.amount is gross, payments.amount is net after discounts/coupons
    is_deleted         SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX idx_payments_order ON payments(order_id);

-- =========================================================================
-- 3. AFTER-SALES
-- =========================================================================

-- 3a. Return Reasons (dictionary)
CREATE TABLE return_reasons (
    reason_id          SERIAL PRIMARY KEY,
    reason_code        VARCHAR(50) NOT NULL UNIQUE,
    reason_name        VARCHAR(200) NOT NULL,
    reason_name_cn     VARCHAR(200) NOT NULL         -- Chinese label
);

-- 3b. Returns
CREATE TABLE returns (
    return_id          VARCHAR(64) PRIMARY KEY,
    order_id           VARCHAR(64) NOT NULL REFERENCES orders(order_id),
    sku_id             VARCHAR(64) NOT NULL REFERENCES skus(sku_id),
    reason_id          INT NOT NULL REFERENCES return_reasons(reason_id),
    return_quantity    INT NOT NULL DEFAULT 1,
    return_amount      NUMERIC(10,2),
    created_at         TIMESTAMP NOT NULL,           -- UTC!
    is_deleted         SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX idx_returns_order ON returns(order_id);
CREATE INDEX idx_returns_sku ON returns(sku_id);
CREATE INDEX idx_returns_reason ON returns(reason_id);
CREATE INDEX idx_returns_created ON returns(created_at);

-- =========================================================================
-- 4. USER BEHAVIOR
-- =========================================================================

-- 4a. Page Views
CREATE TABLE page_views (
    view_id            BIGSERIAL PRIMARY KEY,
    user_id            VARCHAR(64) REFERENCES users(user_id),
    sku_id             VARCHAR(64) REFERENCES skus(sku_id),
    page_type          VARCHAR(100),                 -- homepage, product, search, category
    referral_source    VARCHAR(200),
    session_id         VARCHAR(128),
    viewed_at          TIMESTAMP NOT NULL            -- UTC!
);
CREATE INDEX idx_page_views_user ON page_views(user_id);
CREATE INDEX idx_page_views_sku ON page_views(sku_id);
CREATE INDEX idx_page_views_time ON page_views(viewed_at);

-- 4b. Add to Cart
CREATE TABLE add_to_cart (
    cart_id            BIGSERIAL PRIMARY KEY,
    user_id            VARCHAR(64) REFERENCES users(user_id),
    sku_id             VARCHAR(64) REFERENCES skus(sku_id),
    quantity           INT DEFAULT 1,
    added_at           TIMESTAMP NOT NULL,           -- UTC!
    converted_to_order BOOLEAN DEFAULT FALSE         -- Did this cart event convert?
);
CREATE INDEX idx_cart_user ON add_to_cart(user_id);
CREATE INDEX idx_cart_sku ON add_to_cart(sku_id);
CREATE INDEX idx_cart_time ON add_to_cart(added_at);

-- 4c. Reviews
CREATE TABLE reviews (
    review_id          VARCHAR(64) PRIMARY KEY,
    order_id           VARCHAR(64) NOT NULL REFERENCES orders(order_id),
    sku_id             VARCHAR(64) NOT NULL REFERENCES skus(sku_id),
    user_id            VARCHAR(64) NOT NULL REFERENCES users(user_id),
    review_score       INT NOT NULL CHECK (review_score BETWEEN 1 AND 5),
    review_title       VARCHAR(500),
    review_text        TEXT,                         -- Chinese + original PT
    created_at         TIMESTAMP NOT NULL            -- UTC!
);
CREATE INDEX idx_reviews_order ON reviews(order_id);
CREATE INDEX idx_reviews_sku ON reviews(sku_id);
CREATE INDEX idx_reviews_score ON reviews(review_score);

-- 4d. Customer Service Tickets
CREATE TABLE customer_service_tickets (
    ticket_id          VARCHAR(64) PRIMARY KEY,
    user_id            VARCHAR(64) NOT NULL REFERENCES users(user_id),
    order_id           VARCHAR(64) REFERENCES orders(order_id),
    ticket_type        VARCHAR(50) NOT NULL,         -- complaint, inquiry, return_request, refund
    ticket_status      VARCHAR(30) DEFAULT 'open',   -- open, in_progress, resolved, closed
    subject            VARCHAR(500),
    body               TEXT,                         -- Chinese (Faker augmented)
    created_at         TIMESTAMP NOT NULL,           -- UTC!
    resolved_at        TIMESTAMP,
    is_deleted         SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX idx_tickets_user ON customer_service_tickets(user_id);
CREATE INDEX idx_tickets_order ON customer_service_tickets(order_id);
CREATE INDEX idx_tickets_type ON customer_service_tickets(ticket_type);
"""

# ---------------------------------------------------------------------------
# Convenience: list of tables in dependency order (for teardown & creation)
# ---------------------------------------------------------------------------

TABLE_NAMES = [
    "categories",
    "skus",
    "users",
    "dim_order_status",
    "orders",
    "order_items",
    "payments",
    "return_reasons",
    "returns",
    "page_views",
    "add_to_cart",
    "reviews",
    "customer_service_tickets",
]

# Tables that have an is_deleted column
TABLES_WITH_SOFT_DELETE = [
    "categories",
    "skus",
    "users",
    "orders",
    "order_items",
    "payments",
    "returns",
    "customer_service_tickets",
]
