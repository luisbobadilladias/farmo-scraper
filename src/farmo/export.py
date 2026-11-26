"""Export products_normalized -> site/index.html (self-contained: data embedded, no server needed).

    uv run farmo export        # then open site/index.html, or host the folder anywhere static
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from .basket import BASKET
from .db import connect
from .parse import INGREDIENTS

log = logging.getLogger("farmo.export")

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).parent / "web" / "template.html"
OUT = ROOT / "site" / "index.html"

CHAINS = {
    "farmacenter": {"label": "Farmacenter", "host": "www.farmacenter.com.py"},
    "catedral": {"label": "Farmacia Catedral", "host": "www.farmaciacatedral.com.py"},
    "farmaoliva": {"label": "Farma Oliva", "host": "www.farmaoliva.com.py"},
}
BLOCKED = [{"label": "Punto Farma", "why": "su sitio bloquea el acceso automatizado"}]

PRETTY = {  # canonical (folded) -> display name with accents
    "losartan": "Losartán", "acido folico": "Ácido fólico", "vitamina d3": "Vitamina D3",
    "dipirona": "Dipirona (metamizol)", "hidroclorotiazida": "Hidroclorotiazida",
    "clavulanico": "Ácido clavulánico", "cafeina": "Cafeína", "codeina": "Codeína",
    "acido ascorbico": "Ácido ascórbico", "vitamina c": "Vitamina C", "vitamina b12": "Vitamina B12",
}
FORMS = {
    "comprimido": ("comprimido", "comprimidos"), "capsula": ("cápsula", "cápsulas"),
    "comprimido efervescente": ("comp. efervescente", "comp. efervescentes"),
    "comprimido masticable": ("comp. masticable", "comp. masticables"), "sobre": ("sobre", "sobres"),
    "supositorio": ("supositorio", "supositorios"), "jarabe": ("jarabe", "jarabe"),
    "suspension": ("suspensión", "suspensión"), "gotas": ("gotas", "gotas"), "inhalador": ("inhalador", "inhalador"),
    "inyectable": ("inyectable", "inyectables"), "topico": ("uso tópico", "uso tópico"),
    "solucion": ("solución", "solución"), "solucion para nebulizar": ("solución p/ nebulizar", "solución p/ nebulizar"),
}


def _v(x):
    """pandas NaN/NA/None -> None"""
    return None if x is None or (not isinstance(x, (list, dict)) and pd.isna(x)) else x


def pretty_ing(c: str) -> str:
    return PRETTY.get(c, c[:1].upper() + c[1:])


def _safe_url(url: str, chain: str) -> str | None:
    parts = urlsplit(url or "")
    return url if parts.scheme == "https" and parts.netloc == CHAINS[chain]["host"] else None


def run() -> None:
    con = connect(read_only=True)
    day = con.execute("SELECT max(scrape_date) FROM products_normalized").fetchone()[0]
    df = con.execute("""
        SELECT * FROM products_normalized
        WHERE group_id IS NOT NULL AND price IS NOT NULL AND price > 0 AND chain IN ?
    """, [list(CHAINS)]).df()
    con.close()

    groups = []
    for gid, g in df.groupby("group_id"):
        first = g.iloc[0]
        ings = first.ingredients.split("+")
        offers = []
        for r in g.itertuples():
            url = _safe_url(r.url, r.chain)
            if not url:
                continue
            offers.append({
                "c": r.chain, "n": r.name, "b": _v(r.brand_name), "lab": _v(r.lab), "g": bool(r.is_generic),
                "p": int(r.price), "lp": int(r.list_price) if _v(r.list_price) and r.list_price > r.price else None,
                "q": float(r.pack_size) if _v(r.pack_size) else None,
                "qu": _v(r.pack_unit),
                "u": round(float(r.unit_price), 1) if _v(r.unit_price) else None,
                "s": None if _v(r.in_stock) is None else bool(r.in_stock),
                "url": url,
            })
        if not offers:
            continue
        aliases = sorted({a for i in ings for a in INGREDIENTS.get(i, [i])})
        groups.append({
            "id": gid,
            "ing": [pretty_ing(i) for i in ings],
            "aliases": aliases,
            "st": first.strength_text,
            "sv": float(first.strength) if _v(first.strength) is not None else None,
            "su": _v(first.strength_unit),
            "f": FORMS.get(first.form, (first.form, first.form)),
            "rel": first.release,
            "bq": _v(first.basket_query),
            "o": offers,
        })

    data = {
        "date": str(day),
        "generated": datetime.now().isoformat(timespec="minutes"),
        "chains": {k: v["label"] for k, v in CHAINS.items()},
        "blocked": BLOCKED,
        "popular": [b["query"] for b in BASKET],
        "groups": groups,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    log.info("wrote %s (%d groups, %d offers, %.0f KB)", OUT, len(groups),
             sum(len(g["o"]) for g in groups), OUT.stat().st_size / 1024)
