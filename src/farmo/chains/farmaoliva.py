"""Farma Oliva — Dattamax platform, server-rendered HTML (WooCommerce-like markup).

List: GET /catalogo?q=…  (name-only search! see query expansion in scrape.py)
Detail: product page has structured 'Droga:' (active ingredient), 'Acción:', 'Presentación:', stock.
"""

import html
import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..http import client
from ..models import RawProduct
from ..util import parse_pyg

CHAIN = "farmaoliva"
BASE = "https://www.farmaoliva.com.py/"
MAX_PAGES = 5
FETCH_DETAILS = True


def _label(text: str, label: str) -> str | None:
    m = re.search(rf"{label}:\s*(.+?)(?=\s+(?:Acción|Droga|Presentación|Precio lista|Precio web|CÓDIGO|Venta libre|Bajo receta)\b|$)", text)
    return m.group(1).strip() if m else None


def _details(url: str) -> dict:
    tree = HTMLParser(client().get(CHAIN, url))
    # Both buttons are always rendered; the inapplicable one is hidden with display:none.
    no_stock_btn = next((b for b in tree.css("button.single_add_to_cart_button")
                         if "No disponible" in b.text()), None)
    in_stock = None
    if no_stock_btn is not None:
        in_stock = "display: none" in (no_stock_btn.attributes.get("style") or "")
    for t in tree.css("script, style, svg"):
        t.decompose()
    body = tree.body.text(separator=" ") if tree.body else ""
    text = re.sub(r"\s+", " ", html.unescape(body))
    # keep only the product summary block (before "Productos Relacionados")
    text = text.split("Productos Relacionados")[0]
    out = {
        "ingredient": _label(text, "Droga"),
        "accion": _label(text, "Acción"),
        "presentacion": _label(text, "Presentación"),
    }
    if m := re.search(r"(Venta libre|Bajo receta[^.]*?)(?=\s+Presentación|\s+Acción|\s+Droga)", text):
        out["rx"] = m.group(1).strip()
    out["in_stock"] = in_stock
    return out


def _parse_list(page_html: str, term: str) -> tuple[list[RawProduct], str | None]:
    tree = HTMLParser(page_html)
    out = []
    for card in tree.css("div.products > div.product"):
        a = card.css_first("a.ecommercepro-LoopProduct-link")
        btn = card.css_first("a.add_to_cart_button")
        title = card.css_first("h2")
        if not a or not title:
            continue
        ins, dele = card.css_first(".price ins .amount"), card.css_first(".price del .amount")
        plain = card.css_first(".price .amount")
        sale = parse_pyg((ins or plain).text()) if (ins or plain) else None
        if btn and btn.attributes.get("data-product_price"):
            sale = parse_pyg(btn.attributes["data-product_price"]) or sale
        img = card.css_first("img")
        out.append(RawProduct(
            chain=CHAIN,
            name=html.unescape(title.text(strip=True)),
            price=sale,
            list_price=parse_pyg(dele.text()) if dele else sale,
            url=urljoin(BASE, a.attributes.get("href", "")),
            brand=(btn.attributes.get("data-product_brand") or None) if btn else None,
            ean=(btn.attributes.get("data-product_ean") or None) if btn else None,
            sku=(btn.attributes.get("data-product_item") or None) if btn else None,
            category=(btn.attributes.get("data-product_category") or None) if btn else None,
            image=img.attributes.get("data-src") if img else None,
            search_term=term,
        ))
    nxt = tree.css_first(".ecommercepro-pagination a.next")
    return out, (nxt.attributes.get("href") if nxt else None)


def search(query: str) -> list[RawProduct]:
    c = client()
    items, nxt = _parse_list(c.get(CHAIN, urljoin(BASE, "catalogo"), {"q": query}), query)
    pages = 1
    while nxt and pages < MAX_PAGES:
        more, nxt = _parse_list(c.get(CHAIN, urljoin(BASE, nxt)), query)
        items += more
        pages += 1
    if FETCH_DETAILS:
        for p in items:
            d = _details(p.url)
            p.ingredient = d.get("ingredient")
            p.in_stock = d.get("in_stock")
            p.rx = d.get("rx")
            p.category = p.category or d.get("accion")
            p.description = " | ".join(x for x in (d.get("presentacion"), d.get("accion")) if x) or None
    return items
