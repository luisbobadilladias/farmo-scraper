# farmo-scraper

Throwaway proof of concept: can we reliably get and compare medicine prices across Paraguay's pharmacy chains?

- `RECON.md`: how each chain's site works (Phase 1)
- `FINDINGS.md`: results and go/no-go (Phase 5)

## Setup

```bash
uv sync                      # Python 3.12 + deps
uv sync --extra llm          # optional: Anthropic SDK for the LLM parsing fallback
```

## Run each step

```bash
# Phase 2: scrape the 20-query basket (sequential, 1–2s between requests, ~30–40 min uncached).
# Raw responses are cached in data/raw/{chain}/{YYYY-MM-DD}/, so re-runs the same day hit no sites.
uv run farmo scrape
uv run farmo scrape --term losartan --chain farmacenter   # subset
FARMO_DATE=2026-11-25 FARMO_OFFLINE=1 uv run farmo scrape # replay an earlier day's cache, no network

# Phase 3: parse names, compute price per unit, build equivalence groups (→ data/meds.duckdb)
uv run farmo normalize
uv run farmo normalize --llm     # optional: send unparsed names to Claude (needs ANTHROPIC_API_KEY or `ant auth login`)

# Numbers behind FINDINGS.md
uv run farmo report

# Phase 4: the UI
uv run streamlit run app.py

# Parser sanity check
uv run pytest -q
```

## Layout

```
src/farmo/
  chains/{farmacenter,catedral,farmaoliva,puntofarma}.py   # each: search(query) -> list[RawProduct]
  http.py        # polite cached client (robots.txt, delay, bot-wall detection)
  basket.py      # the 20 test queries
  scrape.py      # basket runner + brand-name expansion for Oliva's name-only search
  parse.py       # regex + rapidfuzz name parser
  normalize.py   # raw_products -> products_normalized, equivalence_groups
  llm.py         # optional Claude fallback
  report.py      # coverage / quality / spread stats
app.py           # Streamlit page
```

DuckDB tables in `data/meds.duckdb`: `raw_products`, `scrape_log`, `products_normalized`, `equivalence_groups`.
