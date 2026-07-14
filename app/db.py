import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_number INTEGER PRIMARY KEY,
    name TEXT,
    category TEXT,
    is_bio TEXT,
    purchase_price REAL,
    suggested_retail_price REAL
);

CREATE TABLE IF NOT EXISTS orderable_items (
    store_id TEXT,
    item_number INTEGER,
    ordering_day TEXT,
    delivery_day TEXT,
    purchase_price REAL,
    suggested_retail_price REAL,
    profit_margin REAL,
    tags TEXT,
    category TEXT
);

CREATE TABLE IF NOT EXISTS inventory (
    store_id TEXT,
    item_number INTEGER,
    day TEXT,
    quantity REAL
);

CREATE TABLE IF NOT EXISTS order_recommendations (
    store_id TEXT,
    item_number INTEGER,
    ordering_day TEXT,
    delivery_day TEXT,
    recommended_quantity INTEGER
);

-- every read is "recommendations for one store on one day"
CREATE INDEX IF NOT EXISTS idx_recommendations_store_day
    ON order_recommendations (store_id, ordering_day);
"""


def get_connection() -> sqlite3.Connection:
    # DB_PATH is configurable so the database can live on a mounted volume
    # (or a temp file in tests); the default keeps local runs working as-is
    db_path = os.environ.get("DB_PATH", "freshflow.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # rows come back dict-like for the JSON response
    conn.executescript(SCHEMA)
    return conn
