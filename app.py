"""Streamlit page: type a medicine, see equivalents across chains sorted by price per unit.

    uv run streamlit run app.py
"""

import re

import duckdb
import pandas as pd
import streamlit as st

from farmo.db import DB_PATH
from farmo.parse import _strengths, find_ingredients, fuzzy_ingredients
from farmo.util import fold

st.set_page_config(page_title="Farmo — precios de medicamentos", layout="wide")
st.title("Farmo · comparador de precios (PoC)")


@st.cache_data(ttl=300)
def load() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute("SELECT * FROM products_normalized WHERE group_id IS NOT NULL").df()
    con.close()
    return df


df = load()
st.caption(f"Datos del {df.scrape_date.max()} · {len(df)} productos agrupables · "
           f"cadenas: {', '.join(sorted(df.chain.unique()))} · Punto Farma bloqueado (anti-bot)")

q = st.text_input("Medicamento", "losartán 50mg", help="Principio activo o marca, opcionalmente con dosis")
if not q:
    st.stop()

qf = re.sub(r"(\d)\s*,\s*(\d)", r"\1.\2", fold(q))
ings = find_ingredients(qf) or fuzzy_ingredients(qf)
if not ings:  # maybe a brand name: look it up in our own data
    word = qf.split()[0]
    hits = df[df.brand_name.fillna("").str.lower().str.startswith(word)]
    ings = sorted(set(hits.ingredients.dropna()))[:1]
    ings = ings[0].split("+") if ings else []
if not ings:
    st.warning("No reconozco ese principio activo o marca.")
    st.stop()

strength = _strengths(qf)
key = "+".join(sorted(ings))
sel = df[df.ingredients == key]
if strength:
    sel = sel[(sel.strength == strength[0][0]) & (sel.strength_unit == strength[0][1])]
if sel.empty:
    st.info(f"Sin resultados para **{key}** {strength[0][0]:g} {strength[0][1]}" if strength else f"Sin resultados para {key}")
    st.stop()

for gk, grp in sorted(sel.groupby("group_key"), key=lambda kv: -len(kv[1])):
    grp = grp.sort_values(["unit_price", "price"], na_position="last").reset_index(drop=True)
    priced = grp[grp.unit_price.notna()]
    gen_idx = priced[priced.is_generic].unit_price.idxmin() if priced.is_generic.any() else None
    br_idx = priced[~priced.is_generic].unit_price.idxmin() if (~priced.is_generic).any() else None

    st.subheader(gk)
    c1, c2, c3 = st.columns(3)
    c1.metric("Productos / cadenas", f"{len(grp)} / {grp.chain.nunique()}")
    if gen_idx is not None:
        c2.metric("Genérico más barato (₲/u)", f"{grp.at[gen_idx, 'unit_price']:,.0f}".replace(",", "."),
                  grp.at[gen_idx, "chain"], delta_color="off")
    if br_idx is not None:
        c3.metric("Marca más barata (₲/u)", f"{grp.at[br_idx, 'unit_price']:,.0f}".replace(",", "."),
                  f"{grp.at[br_idx, 'brand_name']} · {grp.at[br_idx, 'chain']}", delta_color="off")

    view = pd.DataFrame({
        "": ["🟢 genérico más barato" if i == gen_idx else "🔵 marca más barata" if i == br_idx else ""
             for i in grp.index],
        "cadena": grp.chain,
        "producto": grp.name,
        "marca": grp.brand_name.fillna("genérico"),
        "lab": grp.lab,
        "precio ₲": grp.price,
        "lista ₲": grp.list_price,
        "unidades": grp.pack_size,
        "₲ / unidad": grp.unit_price.round(0),
        "stock": grp.in_stock.map({True: "sí", False: "no"}).fillna("?"),
        "link": grp.url,
    })

    def hl(row):
        color = "background-color: rgba(34,197,94,.18)" if row.name == gen_idx else \
            "background-color: rgba(59,130,246,.18)" if row.name == br_idx else ""
        return [color] * len(row)

    st.dataframe(
        view.style.apply(hl, axis=1).format({"precio ₲": "{:,.0f}", "lista ₲": "{:,.0f}", "₲ / unidad": "{:,.0f}",
                                              "unidades": "{:g}"}, na_rep="—"),
        column_config={"link": st.column_config.LinkColumn("link", display_text="abrir")},
        hide_index=True, use_container_width=True,
    )
