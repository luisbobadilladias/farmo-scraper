"""Print the numbers behind FINDINGS.md (coverage, parse quality, spreads, EAN cross-check)."""

import pandas as pd

from .basket import BASKET
from .chains import CHAINS
from .db import connect


def _fmt_pyg(v) -> str:
    return "—" if v is None or pd.isna(v) else f"₲{v:,.0f}".replace(",", ".")


def run() -> None:
    con = connect(read_only=True)
    day = con.execute("SELECT max(scrape_date) FROM products_normalized").fetchone()[0]
    norm = con.execute("SELECT * FROM products_normalized").df()
    log = con.execute("SELECT * FROM scrape_log WHERE scrape_date = ?", [day]).df()
    pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_colwidth", 70)

    print(f"# Report for {day}\n")
    print("## Scrape log")
    print(log.groupby(["chain", "status"]).agg(requests=("search_term", "count"),
                                                results=("n_results", "sum")).to_string(), "\n")
    print("raw products per chain:", norm.groupby("chain").size().to_dict(), "\n")

    # ---- coverage
    print("## Coverage (basket item found = ≥1 product with matching ingredient+strength(+form))")
    queries = [b["query"] for b in BASKET]
    cov = pd.DataFrame(index=queries, columns=list(CHAINS), data="")
    for q in queries:
        for ch in CHAINS:
            sub = norm[(norm.basket_query == q) & (norm.chain == ch)]
            cov.at[q, ch] = f"{len(sub)}" if len(sub) else "·"
    print(cov.to_string())
    pct = {ch: round(100 * (cov[ch] != "·").sum() / len(queries)) for ch in CHAINS}
    print("coverage %:", pct, "\n")

    # ---- parse quality (medicines only: rows whose search surfaced them for basket terms)
    print("## Parse quality (all scraped rows)")
    print(norm.parse_status.value_counts().to_string())
    print((100 * norm.parse_status.value_counts(normalize=True)).round(1).to_string())
    print("\nby chain:\n", pd.crosstab(norm.chain, norm.parse_status, normalize="index").mul(100).round(1).to_string())
    print("\ningredient source:\n", norm.ingredient_source.value_counts(dropna=False).to_string())
    print("\nfailure reasons:\n", norm.failure_reason.value_counts().head(12).to_string())
    for status in ("failed", "partial"):
        print(f"\nexamples ({status}):")
        ex = norm[norm.parse_status == status].sample(min(12, (norm.parse_status == status).sum()), random_state=1)
        for r in ex.itertuples():
            print(f"  [{r.chain}] {r.name!r} -> {r.ingredients} {r.strength_text} {r.form} pack={r.pack_size} ({r.failure_reason})")

    # ---- EAN cross-check: same barcode at ≥2 chains -> did we put them in the same group?
    print("\n## EAN cross-check")
    e = norm[norm.ean.notna() & (norm.ean.str.len() == 13)]
    multi = e.groupby("ean").filter(lambda g: g.chain.nunique() > 1)
    if len(multi):
        agree = multi.groupby("ean").group_key.nunique().eq(1) & multi.groupby("ean").group_key.count().gt(1)
        print(f"{multi.ean.nunique()} barcodes seen at ≥2 chains; same equivalence group for {agree.sum()} "
              f"({100 * agree.mean():.0f}%)")
        bad = multi[multi.ean.isin(agree[~agree].index)].sort_values("ean")
        for r in bad.head(16).itertuples():
            print(f"  {r.ean} [{r.chain}] {r.name!r} -> {r.group_key}")

    # ---- spreads
    print("\n## Biggest spreads within an equivalence group (price per unit, basket items)")
    g = norm[norm.basket_query.notna() & norm.unit_price.notna()]
    rows = []
    for gid, grp in g.groupby("group_id"):
        if len(grp) < 2:
            continue
        lo, hi = grp.loc[grp.unit_price.idxmin()], grp.loc[grp.unit_price.idxmax()]
        rows.append({"basket": lo.basket_query, "group": lo.group_key, "n": len(grp), "chains": grp.chain.nunique(),
                     "cheapest": f"{lo['name']} @{lo.chain} {_fmt_pyg(lo.price)}/{lo.pack_size:g}",
                     "priciest": f"{hi['name']} @{hi.chain} {_fmt_pyg(hi.price)}/{hi.pack_size:g}",
                     "lo_unit": lo.unit_price, "hi_unit": hi.unit_price,
                     "spread_pct": 100 * (hi.unit_price - lo.unit_price) / lo.unit_price})
    sp = pd.DataFrame(rows).sort_values("spread_pct", ascending=False)
    print(sp.head(12).to_string(index=False))

    print("\n## Same product (same barcode) at different chains — pure chain price difference")
    if len(multi):
        rows = []
        for ean, grp in multi.groupby("ean"):
            grp = grp[grp.price.notna()]
            if grp.chain.nunique() < 2:
                continue
            lo, hi = grp.loc[grp.price.idxmin()], grp.loc[grp.price.idxmax()]
            if lo.chain == hi.chain:
                continue
            rows.append({"ean": ean, "name": hi["name"], "basket": grp.basket_query.dropna().iloc[0] if grp.basket_query.notna().any() else None,
                         "cheapest": f"{lo.chain} {_fmt_pyg(lo.price)}", "priciest": f"{hi.chain} {_fmt_pyg(hi.price)}",
                         "diff": hi.price - lo.price, "spread_pct": round(100 * (hi.price - lo.price) / lo.price, 1)})
        same = pd.DataFrame(rows).sort_values("spread_pct", ascending=False)
        print(same.head(15).to_string(index=False))
        print(f"\n{len(same)} barcodes compared; median spread {same.spread_pct.median():.1f}%; "
              f"identical price in {(same.spread_pct == 0).sum()}")

    print("\n## Brand vs generic (cheapest per unit, basket items)")
    rows = []
    for q, grp in g.groupby("basket_query"):
        gen, br = grp[grp.is_generic], grp[~grp.is_generic]
        rows.append({"basket": q, "generic_min": _fmt_pyg(gen.unit_price.min()) if len(gen) else "—",
                     "brand_min": _fmt_pyg(br.unit_price.min()) if len(br) else "—",
                     "brand_max": _fmt_pyg(br.unit_price.max()) if len(br) else "—",
                     "n_generic": len(gen), "n_brand": len(br)})
    print(pd.DataFrame(rows).to_string(index=False))
    con.close()
