from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "meds.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_products (
    chain VARCHAR, url VARCHAR, name VARCHAR, price BIGINT, list_price BIGINT,
    brand VARCHAR, description VARCHAR, ingredient VARCHAR, ean VARCHAR, sku VARCHAR,
    in_stock BOOLEAN, rx VARCHAR, category VARCHAR, image VARCHAR,
    search_terms VARCHAR,          -- comma-separated terms that surfaced this product
    scrape_date DATE, scraped_at VARCHAR,
    PRIMARY KEY (chain, url, scrape_date)
);
CREATE TABLE IF NOT EXISTS scrape_log (
    scrape_date DATE, chain VARCHAR, search_term VARCHAR, status VARCHAR,
    n_results INTEGER, detail VARCHAR, is_expansion BOOLEAN
);
"""


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
    return con
