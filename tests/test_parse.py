"""Quick sanity check on the name parser (the only tests in this PoC)."""

import pytest

from farmo.parse import parse_product

BD = {"hipercor": ["losartan"], "eutirox": ["levotiroxina"]}

CASES = [
    # name, description, structured, expected (ingredients, strength_text, form, pack, status)
    ("LOSARTAN POTASICO 50 MG ETICOS CJ X 30 C", None, None, ("losartan", "50 mg", "comprimido", 30, "clean")),
    ("CONVERTAL 100 CJ X 30 COMPRIMIDOS", "CONVERTAL 100 LOSARTÁN POTÁSICO 100 MG - CAJA DE 30 COMPRIMIDOS", None,
     ("losartan", "100 mg", "comprimido", 30, "clean")),
    ("CONVERTAL D 100 CJ X 30 COMPRIMIDOS", "LOSARTÁN POTÁSICO 100 MG HIDROCLOROTIAZIDA 25 MG", None,
     ("hidroclorotiazida+losartan", "100+25 mg", "comprimido", 30, "clean")),
    ("HIPERCOR 50 MG CJ X 30 COMP.", None, None, ("losartan", "50 mg", "comprimido", 30, "clean")),
    ("EUTIROX 50 CJ X 50 COMP", None, None, ("levotiroxina", "50 mcg", "comprimido", 50, "clean")),
    ("LOSARTAN POTASICO ETICOS 50MG BLISTER X 10 COMP.", None, "Losartán", ("losartan", "50 mg", "comprimido", 10, "clean")),
    ("AMOXICILINA 250 MG/5 ML SUSP X 60 ML", None, None, ("amoxicilina", "50 mg/ml", "suspension", 60, "clean")),
    ("AMOXICILINA 1 G X 8 COMP", None, None, ("amoxicilina", "1000 mg", "comprimido", 8, "clean")),
    ("IBUPROFENO 400MG X 10 COMP", None, None, ("ibuprofeno", "400 mg", "comprimido", 10, "clean")),
    ("DICLOFENACO SODICO 50 MG X 20 COMP", None, None, ("diclofenac", "50 mg", "comprimido", 20, "clean")),
    ("ACIDO FOLICO 5 MG X 20 COMP", None, None, ("acido folico", "5 mg", "comprimido", 20, "clean")),
    ("VITAMINA D3 1000 UI X 60 CAPS", None, None, ("vitamina d3", "1000 ui", "capsula", 60, "clean")),
    ("LEVOCETIRIZINA 5 MG X 10 COMP", None, None, ("levocetirizina", "5 mg", "comprimido", 10, "clean")),
    ("ESOMEPRAZOL 20 MG X 14 CAPS", None, None, ("esomeprazol", "20 mg", "capsula", 14, "clean")),
    # known-unparseable shapes must fail/partial, never silently mis-group
    ("TEMLOSAL 50 MG EXHIB CJ X 10 TIRA", None, None, (None, "50 mg", None, None, "failed")),
    ("ALOGLUC MET 50/850 CAJA X 30 COMP", "asocia un inhibidor de la DPP-4 (50 mg) con metformina", None,
     (None, None, None, None, "failed")),
    ("ACCORD-H CAJA X 30 COMP", None, None, (None, None, "comprimido", 30, "failed")),
]


@pytest.mark.parametrize("name,desc,struct,exp", CASES, ids=[c[0][:30] for c in CASES])
def test_parse(name, desc, struct, exp):
    p = parse_product(name, desc, struct, BD)
    ings, strength, form, pack, status = exp
    assert p.status == status, p
    if ings is not None:
        assert "+".join(p.ingredients) == ings
    if strength is not None:
        assert p.strength_text == strength
    if form is not None:
        assert p.form == form
    if pack is not None:
        assert p.pack_size == pack


def test_combo_marker_after_dose_is_not_monotherapy():
    p = parse_product("ACCORD 50-H 50MG COMP. CAJA X 30", None, "Losartán")
    assert p.status == "failed" and "combo" in p.failure_reason


def test_vitamin_d_is_not_a_combo():
    p = parse_product("VITAMINA D 1000 UI X 30 CAPS", "vitamina d3 colecalciferol", None)
    assert p.status == "clean"


def test_partial_structured_ingredient_upgraded_from_brand_dict():
    bd = {"convertal d": ["hidroclorotiazida", "losartan"]}
    p = parse_product("CONVERTAL-D 50MG T-REC CAJA X 30", None, "Hidroclorotiazida", bd)
    assert p.ingredients == ["hidroclorotiazida", "losartan"]
    p = parse_product("CONVERTAL-D 50MG T-REC CAJA X 30", None, "Hidroclorotiazida")
    assert p.status == "failed"  # without the cross-chain evidence it must not be grouped
