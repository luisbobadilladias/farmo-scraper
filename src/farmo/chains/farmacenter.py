"""Farmacenter — Fenicio platform, server-rendered HTML.

Page 1: GET /catalogo?q=…  (12 cards). Further pages: GET /catalogo?q=…&pag=N&js=1 (HTML fragment).
Each card carries a JSON blob (<input class="json" value="…">) and commented-out marca/desc divs,
so product pages are never needed.
"""

import html
import json
import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..http import client
from ..models import RawProduct
from ..util import parse_pyg

CHAIN = "farmacenter"
BASE = "https://www.farmacenter.com.py"
PER_PAGE = 12
MAX_PAGES = 8

_EAN_IN_URL = re.compile(r"_(\d{13})_\d+$")  # only real 13-digit barcodes, not internal codes


def _monto(node, selector: str) -> int | None:
    n = node.css_first(selector)
    return parse_pyg(n.text()) if n else None


def _parse(page_html: str, term: str) -> tuple[list[RawProduct], int | None]:
    tree = HTMLParser(page_html)
    central = tree.css_first("#central")
    total = int(central.attributes["data-total"]) if central and central.attributes.get("data-total") else None

    out = []
    for card in tree.css("div.it[data-codProd]"):
        raw = card.html or ""
        data = {}
        j = card.css_first("input.json")
        if j and j.attributes.get("value"):
            try:
                data = json.loads(html.unescape(j.attributes["value"]))
            except json.JSONDecodeError:
                pass
        prod, var = data.get("producto", {}), data.get("variante", {})

        title = card.css_first("a.tit h2")
        name = (title.text(strip=True) if title else None) or data.get("nombre")
        if not name:
            continue
        url = var.get("url") or (card.css_first("a.tit").attributes.get("href") if card.css_first("a.tit") else "")
        desc = re.search(r'<!--\s*<div class="desc">(.*?)</div>\s*-->', raw, re.S)
        marca = re.search(r'<!--\s*<div class="marca">(.*?)</div>\s*-->', raw, re.S)
        rx = card.css_first("span.receta")
        img = (var.get("img") or {}).get("u")
        ean = _EAN_IN_URL.search(url or "")

        sale = _monto(card, "strong.precio.venta .monto")
        lst = _monto(card, "del.precio.lista .monto")
        out.append(RawProduct(
            chain=CHAIN,
            name=html.unescape(name),
            price=sale or data.get("precioMonto"),
            list_price=lst or data.get("precioMonto"),
            url=url,
            brand=prod.get("marca") or (html.unescape(marca.group(1).strip()) if marca else None),
            description=(html.unescape(desc.group(1).strip()) or None) if desc else None,
            ean=ean.group(1) if ean else None,
            sku=prod.get("codigo") or card.attributes.get("data-codprod"),
            # listing JSON's tieneStock is always false (product pages disagree); data-disp is the shown flag
            in_stock=card.attributes.get("data-disp") == "1" if card.attributes.get("data-disp") else None,
            rx=rx.text(strip=True) if rx else None,
            category=prod.get("categoria"),
            image=f"https:{img}" if img and img.startswith("//") else img,
            search_term=term,
        ))
    return out, total


def search(query: str) -> list[RawProduct]:
    c = client()
    items, total = _parse(c.get(CHAIN, f"{BASE}/catalogo", {"q": query}), query)
    page = 2
    while total and len(items) < total and page <= MAX_PAGES:
        more, _ = _parse(c.get(CHAIN, f"{BASE}/catalogo", {"q": query, "pag": page, "js": 1}), query)
        if not more:
            break
        items += more
        page += 1
    # de-dupe (a fragment can repeat cards)
    seen, uniq = set(), []
    for p in items:
        if p.url not in seen:
            seen.add(p.url)
            uniq.append(p)
    return uniq
