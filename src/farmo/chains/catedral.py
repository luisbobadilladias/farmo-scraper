"""Farmacia Catedral — Laravel + Vue. JSON list endpoint + HTML product pages.

List: GET /get-productos?page=N&query_string=…  (Laravel paginator, 20/page)
Detail: product page gives brand (lab), barcode, stock, description text (mentions the ingredient).
robots.txt asks for Crawl-delay: 1 — our client already waits 1–2s.
"""

import html
import json
import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..http import client
from ..models import RawProduct

CHAIN = "catedral"
BASE = "https://www.farmaciacatedral.com.py"
MAX_PAGES = 5
FETCH_DETAILS = True


def _details(url: str) -> dict:
    page = client().get(CHAIN, url)
    tree = HTMLParser(page)
    out: dict = {}
    for s in tree.css('script[type="application/ld+json"]'):
        try:
            ld = json.loads(s.text())
        except json.JSONDecodeError:
            continue
        if isinstance(ld, dict) and ld.get("@type") == "Product":
            out["brand"] = (ld.get("brand") or {}).get("name")
            offers = ld.get("offers") or {}
            if "availability" in offers:
                out["in_stock"] = offers["availability"].endswith("InStock")
            out["ld_description"] = ld.get("description")
    if n := tree.css_first("a.title-marca"):
        out["brand"] = out.get("brand") or n.text(strip=True)
    if n := tree.css_first("p.barra-ficha"):
        if m := re.search(r"\d{8,14}", n.text()):
            out["ean"] = m.group(0)
    if n := tree.css_first("p.stock-ficha"):
        out["in_stock"] = "disponible" in n.text().lower() and "no disponible" not in n.text().lower()
    if n := tree.css_first("#home-tab-pane"):
        out["description"] = re.sub(r"\s+", " ", n.text(separator=" ")).strip()[:1500]
    return out


def search(query: str) -> list[RawProduct]:
    c = client()
    rows, page = [], 1
    while page <= MAX_PAGES:
        data = c.get_json(CHAIN, f"{BASE}/get-productos", {"page": page, "query_string": query},
                          headers={"Referer": f"{BASE}/buscador?q={query}"})
        pag = data.get("paginacion") or {}
        rows += pag.get("data") or []
        if page >= (pag.get("last_page") or 1):
            break
        page += 1

    out = []
    for r in rows:
        d = _details(r["url_ver"]) if FETCH_DETAILS else {}
        desc_parts = [r.get("nombre_seo"), d.get("ld_description"), d.get("description")]
        out.append(RawProduct(
            chain=CHAIN,
            name=html.unescape(r["nombre"]).strip(),
            price=r.get("getPrecio"),
            list_price=r.get("getPrecioAnterior") or r.get("getPrecio"),
            url=r["url_ver"],
            brand=d.get("brand"),
            description=" | ".join(p for p in desc_parts if p) or None,
            ean=d.get("ean"),
            sku=str(r.get("codigo_articulo") or r.get("id")),
            in_stock=d.get("in_stock"),
            image=r.get("primera_imagen"),
            search_term=query,
        ))
    return out
