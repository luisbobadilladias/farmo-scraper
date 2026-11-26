"""raw_products -> products_normalized + equivalence_groups.

Ingredient resolution order per product:
  1. regex/dictionary on name, chain's structured field (Oliva 'Droga'), description
  2. rapidfuzz against the ingredient dictionary (misspellings)
  3. brand dictionary learned from pass 1 ('hipercor d' -> losartan+hidroclorotiazida)
  4. same EAN barcode already resolved at another chain
  5. (optional, --llm) Claude
"""

import argparse
import hashlib
import logging
import sys

import pandas as pd

from .basket import BASKET
from .db import connect
from .parse import Parsed, build_brand_dict, parse_product
from .util import fold

log = logging.getLogger("farmo.normalize")

DIRECT_SOURCES = {"name", "structured", "description", "name+description", "structured+description"}


def _group_key(p: Parsed) -> str | None:
    if not p.ingredients or not p.strengths or not p.form or p.status == "failed":
        return None
    if len(p.ingredients) > 1 and len(p.strengths) < len(p.ingredients):
        return None  # 'CONVERTAL D 50 MG': combo with partial dose info can't be compared safely
    return " | ".join(["+".join(p.ingredients), p.strength_text, p.form, p.release or "normal"])


def _basket_for(p: Parsed) -> str | None:
    if p.ingredients is None or len(p.ingredients) != 1 or p.status == "failed":
        return None
    ing = p.ingredients[0]
    for b in BASKET:
        if fold(b["ingredient"]) != ing:
            continue
        if b.get("form") and p.form != b["form"]:
            continue
        if b["strength"] is not None:
            if not p.strengths or p.strengths[0][0] != b["strength"] or p.strengths[0][1] != b["unit"]:
                continue
        elif p.form is None:
            continue
        return b["query"]
    return None


def _llm_fill(df: pd.DataFrame, parsed: list[Parsed]) -> int:
    from .llm import parse_batch

    todo = [i for i, p in enumerate(parsed) if p.status != "clean"]
    if not todo:
        return 0
    res = parse_batch([{"id": i, "name": df.at[i, "name"], "description": (df.at[i, "description"] or "")[:300]}
                       for i in todo])
    fixed = 0
    for i, r in res.items():
        p = parsed[i]
        ings = sorted(fold(x) for x in r["ingredients"])
        if not ings:
            continue
        p.ingredients = ings
        p.ingredient_source = "llm"
        if r["strengths"] and r["unit"]:
            p.strengths = [(float(v), fold(r["unit"])) for v in r["strengths"]]
        p.form = p.form or (fold(r["form"]) if r["form"] else None)
        if not p.pack_size and r["pack_size"]:
            p.pack_size, p.pack_unit = float(r["pack_size"]), r["pack_unit"] or "unidad"
        before = p.status
        p.status = "clean" if (p.strengths and p.form and p.pack_size) else "partial"
        p.failure_reason = None if p.status == "clean" else "llm: incomplete"
        fixed += before != p.status
    return fixed


def run(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="farmo normalize")
    ap.add_argument("--llm", action="store_true", help="send unparsed names to Claude (needs credentials)")
    args = ap.parse_args(argv if argv is not None else sys.argv[2:])

    con = connect()
    day = con.execute("SELECT max(scrape_date) FROM raw_products").fetchone()[0]
    df = con.execute("SELECT * FROM raw_products WHERE scrape_date = ? ORDER BY chain, url", [day]).df()
    log.info("normalizing %d raw products from %s", len(df), day)

    def parse_all(brand_dict=None):
        return [parse_product(r.name, r.description, r.ingredient, brand_dict) for r in df.itertuples()]

    # pass 1: direct evidence only -> learn brand dictionary
    first = parse_all()
    brand_dict = build_brand_dict([(p.brand_key, p.ingredients) for p in first
                                   if p.ingredient_source in DIRECT_SOURCES])
    # pass 2: with brand dictionary
    parsed = parse_all(brand_dict)

    # EAN propagation: same barcode resolved elsewhere
    ean_ings = {}
    for r, p in zip(df.itertuples(), parsed):
        if r.ean and p.ingredients and p.ingredient_source in DIRECT_SOURCES:
            ean_ings.setdefault(r.ean, p.ingredients)
    for r, p in zip(df.itertuples(), parsed):
        if not p.ingredients and r.ean in ean_ings:
            p2 = parse_product(r.name, r.description, " ".join(ean_ings[r.ean]), brand_dict)
            p2.ingredient_source = "ean"
            parsed[r.Index] = p2

    stats_pre_llm = pd.Series([p.status for p in parsed]).value_counts().to_dict()
    llm_fixed = 0
    if args.llm:
        llm_fixed = _llm_fill(df, parsed)
        log.info("LLM fallback upgraded %d products", llm_fixed)

    rows = []
    for r, p in zip(df.itertuples(), parsed):
        gk = _group_key(p)
        unit_price = (r.price / p.pack_size) if (r.price and p.pack_size) else None
        rows.append({
            "chain": r.chain, "url": r.url, "name": r.name, "price": r.price, "list_price": r.list_price,
            "ingredients": "+".join(p.ingredients) or None, "ingredient_source": p.ingredient_source,
            "strength": p.strengths[0][0] if p.strengths else None,
            "strength_unit": p.strengths[0][1] if p.strengths else None,
            "strength_text": p.strength_text, "strength_inferred": p.strength_inferred,
            "form": p.form, "form_inferred": p.form_inferred, "release": p.release,
            "pack_size": p.pack_size, "pack_unit": p.pack_unit, "unit_price": unit_price,
            "brand_name": None if p.is_generic else (p.brand_key.upper() if p.brand_key else None),
            "lab": r.brand, "is_generic": p.is_generic,
            "parse_status": p.status, "failure_reason": p.failure_reason,
            "group_key": gk,
            "group_id": hashlib.sha1(gk.encode()).hexdigest()[:10] if gk else None,
            "basket_query": _basket_for(p),
            "ean": r.ean, "in_stock": r.in_stock, "image": r.image, "scrape_date": day,
        })
    norm = pd.DataFrame(rows)

    con.execute("DROP TABLE IF EXISTS products_normalized")
    con.execute("CREATE TABLE products_normalized AS SELECT * FROM norm")
    con.execute("DROP TABLE IF EXISTS equivalence_groups")
    con.execute("""
        CREATE TABLE equivalence_groups AS
        WITH g AS (
            SELECT * FROM products_normalized WHERE group_id IS NOT NULL
        ), ranked AS (
            SELECT *,
                row_number() OVER (PARTITION BY group_id, is_generic ORDER BY unit_price NULLS LAST, price) AS rk
            FROM g
        )
        SELECT
            g.group_id, any_value(g.group_key) AS group_key, any_value(g.ingredients) AS ingredients,
            any_value(g.strength_text) AS strength, any_value(g.form) AS form, any_value(g.release) AS release,
            any_value(g.basket_query) AS basket_query,
            count(*) AS n_products, count(DISTINCT g.chain) AS n_chains,
            string_agg(DISTINCT g.chain, ',' ORDER BY g.chain) AS chains,
            min(g.unit_price) AS min_unit_price, max(g.unit_price) AS max_unit_price,
            CASE WHEN min(g.unit_price) > 0
                 THEN round(100.0 * (max(g.unit_price) - min(g.unit_price)) / min(g.unit_price), 1) END AS spread_pct,
            (SELECT url FROM ranked r WHERE r.group_id = g.group_id AND r.is_generic AND r.rk = 1) AS cheapest_generic_url,
            (SELECT url FROM ranked r WHERE r.group_id = g.group_id AND NOT r.is_generic AND r.rk = 1) AS cheapest_brand_url
        FROM g GROUP BY g.group_id
    """)

    summary = norm["parse_status"].value_counts().to_dict()
    log.info("parse status: %s (before LLM: %s, LLM upgraded %d)", summary, stats_pre_llm, llm_fixed)
    log.info("ingredient sources: %s", norm["ingredient_source"].value_counts(dropna=False).to_dict())
    n_groups, n_multi = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE n_chains > 1) FROM equivalence_groups").fetchone()
    log.info("%d equivalence groups, %d span >1 chain", n_groups, n_multi)
    con.close()
