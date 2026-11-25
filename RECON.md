# Phase 1 — Recon

Date: 2026-11-25. Test query: `losartan`. All requests were plain `curl` with a desktop Chrome User-Agent and ≥1s between calls.

## Summary

| Chain | Domain | Platform | Access method | Fields available | Difficulty | Notes / blockers |
|---|---|---|---|---|---|---|
| **Punto Farma** | puntofarma.com.py | Unknown (behind Radware Bot Manager) | ❌ None via HTTP | — | 5 (blocked) | Every page 302s to `validate.perfdrive.com` (Radware bot challenge/CAPTCHA). robots.txt itself is reachable and permissive (only cart/account disallowed). Per the rules, **not working around it**. This is the largest chain, so it's a real coverage gap. |
| **Farmacenter** | farmacenter.com.py | Fenicio (Uruguayan SaaS; `Server: fn`, `f.fcdn.app` CDN) | Server-rendered HTML: `GET /catalogo?q=…` (12 items/page), next pages via `GET /catalogo?q=…&pag=N&js=1` (HTML fragment) | name, **list price**, **sale price**, brand/lab (`MEGALABS`), long description that usually contains the active ingredient (`CONVERTAL LOSARTÁN POTÁSICO 50 MG - CAJA DE 30 COMPRIMIDOS RECUBIERTOS`), category (`Medicamentos > Cardiológicos`), stock (`tieneStock`, `data-disp`), Rx flag (`Venta libre`), URL, image, internal SKU; EAN sometimes appears in the URL slug | 2 | Best source. Each card embeds a JSON blob (`<input class="json" value="{…}">`) plus commented-out `marca`/`desc` divs, so **no product-page fetch needed**. Search matches the active ingredient: `losartan` → 19 results, including brands (Convertal, Lozax, Hipercor, Accord…). Accents are handled. Also shows per-bank discount prices (GNB, Continental), which I'll ignore. robots.txt: allow all. |
| **Farmacia Catedral** | farmaciacatedral.com.py | Custom Laravel + Vue (Cloudflare in front, no challenge) | JSON: `GET /get-productos?page=N&query_string=…` (Laravel paginator, 20/page, `last_page` given) | name, SEO name (`Temlosal 50 Mg Caja x 30 Comprimidos Recubiertos`), **sale price** (`getPrecio`), **previous price** (`getPrecioAnterior`), discount %, image, URL, internal code. Product page adds JSON-LD with brand/lab (`Pharmetica`), `availability` (InStock), and a free-text description mentioning the ingredient ("antihipertensivo (losartán)") | 2 | Clean JSON, not under the disallowed `/api/` path. robots.txt asks for `Crawl-delay: 1`. Search matches the ingredient (`losartan` → 9 incl. Temlosal, Accord, Prisonil). **No ingredient/brand/stock in the list JSON**, so getting them means one extra product-page fetch per item (slower). Accents are handled. |
| **Farma Oliva** | farmaoliva.com.py | Dattamax (Paraguayan e-commerce SaaS; `dattamax.com` CDN, WooCommerce-like markup but not WordPress) | Server-rendered HTML: `GET /catalogo?q=…` (WooCommerce-style `Mostrando 1–N de M` + pagination) | name, **web price**, **list price**, **EAN barcode** (`data-product_ean`), internal item code, URL, image. Product page adds structured **`Droga: Losartán`**, `Acción` (therapeutic class), `Presentación`, Rx flag, stock (`No disponible`) | 3 | **Search matches product names only**: `losartan` → 2 results, while `convertal` → 4 more losartán products. To get real coverage I'll need query expansion (ingredient → known brand names, bootstrapped from Farmacenter/Catedral results). The product page has the best structured ingredient field of any chain. robots.txt: allow all. Catalog looks thinner (`paracetamol` → 1 result). |
| *Farmatotal* (extra) | farmatotal.com.py | Unknown (Cloudflare) | ❌ None | — | 5 (blocked) | Cloudflare managed challenge (`cf-mitigated: challenge`, 403). Skipped. |
| *Farmacias Nissei* (extra) | farmaciasnissei.com | — | ❌ | — | — | Connection refused; I didn't dig further. |

## Sample `losartan` data

| Chain | Product | List ₲ | Sale ₲ |
|---|---|---|---|
| Farmacenter | LOSARTAN POTASICO 50 MG ETICOS CJ X 30 C | 75.600 | 37.800 |
| Catedral | LOSARTAN ETICOS 50MG CAJA X 30 COMPRIMIDOS RECUBIERTOS | 75.600 | 37.800 |
| Farma Oliva | LOSARTAN POTASICO 50MG CAJA X 30 COMP | 75.600 | 37.800 |
| Farmacenter | CONVERTAL 50 MG. CJ X 30 COMP. REC. | 75.900 | 60.720 |
| Catedral | TEMLOSAL 50 MG CAJA X 30 COMP REC | 82.000 | 41.000 |
| Farmacenter | TEMLOSAL 50 MG. CJ X 30 COMP. REC. | 82.000 | 61.500 |

Early signals:
- **List prices are almost identical across chains** (likely tied to the lab's suggested/max price). **The real variation is in the web discount**: the same Temlosal box is ₲41.000 at Catedral vs ₲61.500 at Farmacenter.
- Discounts are large (often 20–50%) and probably change with weekly promos, so a single snapshot is noisy.

## Implications for Phases 2–3

1. **3 of 4 target chains are scrapable with plain `httpx`. No Playwright needed.** Punto Farma is blocked.
2. **Search semantics differ by chain.** Farmacenter and Catedral search the ingredient; Oliva searches names only. Plan: run each basket query on all chains, collect brand names from the Farmacenter/Catedral results (e.g. `CONVERTAL`, `TEMLOSAL`), then re-query Oliva with those brands.
3. **Brand names often omit the ingredient** ("HIPERCOR D CJ X 30 COMPRIMIDOS"). Ingredient sources, best to worst: Oliva `Droga` (product page) > Farmacenter `desc` (listing) > Catedral description text (product page) > a brand→ingredient dictionary built from the other chains.
4. **The EAN barcode is a free exact-match key** where present (Oliva always; Farmacenter sometimes, via URL slug). I'll use it to validate the fuzzy matching, not as the main matcher, since some EANs look reused across presentations.
5. Price to compare: the **sale/web price** (what you'd actually pay online), keeping the list price alongside.
6. Request budget per full run: ~20 queries × (1–2 pages) × 3 chains + Oliva brand expansions + Catedral/Oliva product pages ≈ 300–600 requests at 1–2s each, so **~10–15 min uncached**. Fine.
