"""The 20-query test basket.

`search`  : terms actually sent to the sites (ingredient only, no dose — dose filtering is ours to do;
            sites' search handles "50mg" inconsistently).
`ingredient`, `strength`, `unit`, `form`: the target spec used for coverage / matching (Phase 3).
"""

BASKET = [
    {"query": "losartán 50mg", "search": ["losartan"], "ingredient": "losartan", "strength": 50, "unit": "mg"},
    {"query": "enalapril 10mg", "search": ["enalapril"], "ingredient": "enalapril", "strength": 10, "unit": "mg"},
    {"query": "metformina 850mg", "search": ["metformina"], "ingredient": "metformina", "strength": 850, "unit": "mg"},
    {"query": "atorvastatina 20mg", "search": ["atorvastatina"], "ingredient": "atorvastatina", "strength": 20, "unit": "mg"},
    {"query": "omeprazol 20mg", "search": ["omeprazol"], "ingredient": "omeprazol", "strength": 20, "unit": "mg"},
    {"query": "ibuprofeno 400mg", "search": ["ibuprofeno"], "ingredient": "ibuprofeno", "strength": 400, "unit": "mg"},
    {"query": "ibuprofeno 600mg", "search": ["ibuprofeno"], "ingredient": "ibuprofeno", "strength": 600, "unit": "mg"},
    {"query": "paracetamol 500mg", "search": ["paracetamol"], "ingredient": "paracetamol", "strength": 500, "unit": "mg"},
    {"query": "dipirona 500mg", "search": ["dipirona", "metamizol"], "ingredient": "dipirona", "strength": 500, "unit": "mg"},
    {"query": "diclofenac 50mg", "search": ["diclofenac"], "ingredient": "diclofenac", "strength": 50, "unit": "mg"},
    {"query": "amoxicilina 500mg", "search": ["amoxicilina"], "ingredient": "amoxicilina", "strength": 500, "unit": "mg"},
    {"query": "azitromicina 500mg", "search": ["azitromicina"], "ingredient": "azitromicina", "strength": 500, "unit": "mg"},
    {"query": "loratadina 10mg", "search": ["loratadina"], "ingredient": "loratadina", "strength": 10, "unit": "mg"},
    {"query": "cetirizina 10mg", "search": ["cetirizina"], "ingredient": "cetirizina", "strength": 10, "unit": "mg"},
    {"query": "levotiroxina 50mcg", "search": ["levotiroxina"], "ingredient": "levotiroxina", "strength": 50, "unit": "mcg"},
    {"query": "prednisona 20mg", "search": ["prednisona"], "ingredient": "prednisona", "strength": 20, "unit": "mg"},
    {"query": "salbutamol inhalador", "search": ["salbutamol"], "ingredient": "salbutamol", "strength": None, "unit": None, "form": "inhalador"},
    {"query": "sildenafil 50mg", "search": ["sildenafil"], "ingredient": "sildenafil", "strength": 50, "unit": "mg"},
    {"query": "ácido fólico 5mg", "search": ["acido folico"], "ingredient": "acido folico", "strength": 5, "unit": "mg"},
    {"query": "vitamina D3", "search": ["vitamina d3", "colecalciferol"], "ingredient": "vitamina d3", "strength": None, "unit": None},
]


def search_terms() -> list[str]:
    seen: list[str] = []
    for b in BASKET:
        for t in b["search"]:
            if t not in seen:
                seen.append(t)
    return seen
