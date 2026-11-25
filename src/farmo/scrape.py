"""Run the basket against every chain and store results in raw_products.

Order per search term: chains whose search matches ingredients (Farmacenter, Catedral) run first;
their results seed a list of brand names (e.g. CONVERTAL, TEMLOSAL for losartán) which are then
searched on Farma Oliva, whose search only matches product names.
"""

import logging
import re
from datetime import date

from .basket import search_terms
from .chains import CHAINS
from .db import connect
from .http import cache_date, client
from .models import Blocked, RawProduct
from .util import fold

log = logging.getLogger("farmo.scrape")

INGREDIENT_SEARCH_CHAINS = ["farmacenter", "catedral"]
NAME_SEARCH_CHAINS = ["farmaoliva"]
MAX_BRAND_EXPANSIONS = 12

# first words that are labs / generic words, not product brands
_NOT_BRANDS = {
    "lepetit", "eticos", "lasca", "indufar", "bioethic", "catedral", "quimfa", "roemmers", "megalabs",
    "comprimidos", "comp", "caja", "tabletas", "capsulas", "jarabe", "suspension", "crema", "gel",
    "vitamina", "acido", "complejo", "sobres", "gotas", "solucion", "inyectable", "pack", "kit",
}


def _brand_candidates(term: str, products: list[RawProduct]) -> list[str]:
    """Brand words from products whose text mentions the ingredient but whose name doesn't."""
    ing = fold(term).split()[0]
    counts: dict[str, int] = {}
    for p in products:
        name, text = fold(p.name), fold(" ".join(filter(None, [p.name, p.description, p.ingredient])))
        if ing not in text or name.startswith(ing):
            continue
        first = re.split(r"[\s\-\.\d/]+", name.strip())[0]
        if len(first) >= 4 and first not in _NOT_BRANDS and first != ing:
            counts[first] = counts.get(first, 0) + 1
    return [b for b, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:MAX_BRAND_EXPANSIONS]


def _search(con, chain: str, term: str, *, expansion: bool, dead: set[str]) -> list[RawProduct]:
    if chain in dead:
        return []
    try:
        res = CHAINS[chain].search(term)
        status, detail = "ok", None
    except Blocked as e:
        res, status, detail = [], "blocked", str(e)
        dead.add(chain)  # don't keep knocking on a bot wall
        log.warning("%s blocked: %s", chain, e)
    except Exception as e:  # keep the run going; record the failure
        res, status, detail = [], "error", f"{type(e).__name__}: {e}"
        log.exception("%s failed on %r", chain, term)
    con.execute("INSERT INTO scrape_log VALUES (?, ?, ?, ?, ?, ?, ?)",
                [cache_date(), chain, term, status, len(res), detail, expansion])
    log.info("%-12s %-22r %s %d", chain, term, status, len(res))
    return res


def run(terms: list[str] | None = None, chains: list[str] | None = None) -> None:
    terms = terms or search_terms()
    chains = chains or list(CHAINS)
    con = connect()
    day = cache_date()
    con.execute("DELETE FROM scrape_log WHERE scrape_date = ?", [day])
    collected: dict[tuple[str, str], RawProduct] = {}
    found_by: dict[tuple[str, str], set[str]] = {}
    dead: set[str] = set()

    def keep(items: list[RawProduct], term: str):
        for p in items:
            k = (p.chain, p.url)
            collected.setdefault(k, p)
            found_by.setdefault(k, set()).add(term)

    for term in terms:
        seed: list[RawProduct] = []
        for ch in [c for c in INGREDIENT_SEARCH_CHAINS if c in chains]:
            r = _search(con, ch, term, expansion=False, dead=dead)
            keep(r, term)
            seed += r
        brands = _brand_candidates(term, seed)
        for ch in [c for c in NAME_SEARCH_CHAINS if c in chains]:
            keep(_search(con, ch, term, expansion=False, dead=dead), term)
            for b in brands:
                keep(_search(con, ch, b, expansion=True, dead=dead), term)
        for ch in [c for c in chains if c not in INGREDIENT_SEARCH_CHAINS + NAME_SEARCH_CHAINS]:
            keep(_search(con, ch, term, expansion=False, dead=dead), term)

    con.execute("DELETE FROM raw_products WHERE scrape_date = ?", [day])
    rows = []
    for k, p in collected.items():
        d = p.to_dict()
        rows.append([d["chain"], d["url"], d["name"], d["price"], d["list_price"], d["brand"], d["description"],
                     d["ingredient"], d["ean"], d["sku"], d["in_stock"], d["rx"], d["category"], d["image"],
                     ",".join(sorted(found_by[k])), date.fromisoformat(day), d["scraped_at"]])
    if rows:
        con.executemany("INSERT INTO raw_products VALUES (" + ",".join("?" * 17) + ")", rows)
    summary = con.execute("""SELECT chain, count(*) FROM raw_products WHERE scrape_date = ?
                             GROUP BY 1 ORDER BY 1""", [day]).fetchall()
    log.info("stored %d products for %s: %s | http %s", len(rows), day, summary, client().stats)
    con.close()
