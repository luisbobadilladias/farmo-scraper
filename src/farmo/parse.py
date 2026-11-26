"""Parse messy Spanish pharmacy product names into structured fields.

    "CONVERTAL D 50 MG CJ X 30 COMP. REC." ->
        ingredients=['hidroclorotiazida','losartan'] (via description), strength 50+12.5 mg,
        form=comprimido, pack=30 unidad, brand_key='convertal d', is_generic=False

Strategy: regex on accent-folded text + an ingredient dictionary, rapidfuzz for misspellings,
and a brand->ingredient dictionary learned from the rest of the dataset for names that only carry a
brand ("HIPERCOR 50 MG CJ X 30"). Each result records *where* the ingredient came from and a status:
    clean   - ingredients + strength + form + pack size all determined
    partial - ingredients found but something needed for price-per-unit is missing
    failed  - no ingredient could be determined
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .util import fold

# canonical -> aliases (folded). Longer / more specific names must be listed so that word-boundary
# matching picks e.g. 'levocetirizina' instead of 'cetirizina', 'esomeprazol' instead of 'omeprazol'.
INGREDIENTS: dict[str, list[str]] = {
    # basket
    "losartan": ["losartan", "losartan potasico", "losartana"],
    "enalapril": ["enalapril", "enalapril maleato", "maleato de enalapril"],
    "metformina": ["metformina", "metformina clorhidrato", "clorhidrato de metformina"],
    "atorvastatina": ["atorvastatina", "atorvastatina calcica"],
    "omeprazol": ["omeprazol"],
    "ibuprofeno": ["ibuprofeno", "ibuprofen"],
    "paracetamol": ["paracetamol", "acetaminofen", "acetaminofeno"],
    "dipirona": ["dipirona", "metamizol", "metamizol sodico", "metamizole", "dipirona sodica"],
    "diclofenac": ["diclofenac", "diclofenaco", "diclofenac sodico", "diclofenac potasico", "diclofenac resinato"],
    "amoxicilina": ["amoxicilina", "amoxicillina", "amoxicilina trihidrato"],
    "azitromicina": ["azitromicina"],
    "loratadina": ["loratadina"],
    "cetirizina": ["cetirizina", "cetirizina diclorhidrato"],
    "levotiroxina": ["levotiroxina", "levotiroxina sodica", "t4"],
    "prednisona": ["prednisona"],
    "salbutamol": ["salbutamol", "albuterol"],
    "sildenafil": ["sildenafil", "sildenafilo", "sildenafil citrato"],
    "acido folico": ["acido folico", "folico"],
    "vitamina d3": ["vitamina d3", "vit d3", "vit. d3", "colecalciferol", "vitamina d 3", "d3"],
    # look-alikes that must NOT collapse into basket items
    "levocetirizina": ["levocetirizina"],
    "desloratadina": ["desloratadina"],
    "esomeprazol": ["esomeprazol"],
    "prednisolona": ["prednisolona", "metilprednisolona"],
    "rosuvastatina": ["rosuvastatina"],
    "dexketoprofeno": ["dexketoprofeno"],
    "dexibuprofeno": ["dexibuprofeno"],
    # common partners in combination products
    "hidroclorotiazida": ["hidroclorotiazida", "hctz", "hct"],
    "amlodipina": ["amlodipina", "amlodipino"],
    "clavulanico": ["acido clavulanico", "clavulanico", "clavulanato", "clavulanato de potasio"],
    "cafeina": ["cafeina"],
    "codeina": ["codeina"],
    "pseudoefedrina": ["pseudoefedrina"],
    "fenilefrina": ["fenilefrina"],
    "clorfenamina": ["clorfenamina", "clorfeniramina"],
    "orfenadrina": ["orfenadrina"],
    "carisoprodol": ["carisoprodol"],
    "pargeverina": ["pargeverina"],
    "hioscina": ["hioscina", "butilescopolamina"],
    "tramadol": ["tramadol"],
    "metocarbamol": ["metocarbamol"],
    "betametasona": ["betametasona"],
    "dexametasona": ["dexametasona"],
    "ipratropio": ["ipratropio", "bromuro de ipratropio"],
    "beclometasona": ["beclometasona"],
    "budesonida": ["budesonida"],
    "glibenclamida": ["glibenclamida"],
    "sitagliptina": ["sitagliptina"],
    "vildagliptina": ["vildagliptina"],
    "ezetimiba": ["ezetimiba"],
    "calcio": ["calcio", "carbonato de calcio", "citrato de calcio"],
    "hierro": ["hierro", "sulfato ferroso", "fumarato ferroso"],
    "vitamina b12": ["vitamina b12", "cianocobalamina", "b12"],
    "vitamina b1": ["vitamina b1", "tiamina"],
    "vitamina b6": ["vitamina b6", "piridoxina"],
    "magnesio": ["magnesio"],
    "zinc": ["zinc"],
    "vitamina c": ["vitamina c", "acido ascorbico"],
    "vitamina k2": ["vitamina k2", "menaquinona"],
    "omega 3": ["omega 3"],
    "dextrometorfano": ["dextrometorfano"],
    "guaifenesina": ["guaifenesina"],
    "ambroxol": ["ambroxol"],
    "simeticona": ["simeticona"],
    "domperidona": ["domperidona"],
    "famotidina": ["famotidina"],
    "lidocaina": ["lidocaina"],
    "fluticasona": ["fluticasona"],
}

_ALIAS_TO_CANON = {a: c for c, al in INGREDIENTS.items() for a in al}
# longest alias first so 'acido clavulanico' wins over 'clavulanico'
_ALIASES = sorted(_ALIAS_TO_CANON, key=len, reverse=True)
_ALIAS_RE = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(a) for a in _ALIASES) + r")(?![a-z0-9])")
# aliases too short/ambiguous to trust when they appear alone in free text
_WEAK_ALIASES = {"t4", "d3", "hct", "b12", "folico"}
_FUZZY_POOL = [a for a in _ALIASES if len(a) >= 7 and " " not in a]

FORMS = [  # (regex on folded text, canonical form). First match wins, order matters.
    (r"\binhal|\baerosol\b|\binh\b|\bpuff|\bdosis\b", "inhalador"),
    (r"\bnebul|\bsol\.? p/? ?nebul", "solucion para nebulizar"),
    (r"\bjarabe\b|\bjbe\b|\bjar\b", "jarabe"),
    (r"\bsusp|\bpolvo p/ ?susp", "suspension"),
    (r"\bgotas\b|\bgts\b|\bgota\b", "gotas"),
    (r"\biny|\bampolla|\bamp\b|\bvial\b|\bjeringa", "inyectable"),
    (r"\bsupos|\bsup\b", "supositorio"),
    (r"\bcrema\b|\bgel\b|\bpomada\b|\bunguento\b|\blocion\b|\bemulgel\b|\bspray\b", "topico"),
    (r"\bsobres?\b|\bsachet", "sobre"),
    (r"\befervesc|\beferv\b", "comprimido efervescente"),
    (r"\bmasticab|\bmast\b", "comprimido masticable"),
    (r"\bcaps?\b|\bcapsulas?\b|\bcapsula blanda|\bcap\.|\bcaps\.|\bperlas?\b|\bsoftgel", "capsula"),
    (r"\bcomp|\bcomprimidos?\b|\btab\b|\btabletas?\b|\bgrageas?\b|\bcompr\b|\bco-rv\b|\bt-rec\b|\bcom\b|\bcpr\b|\bc\.? ?rec\b", "comprimido"),
    (r"\bsolucion\b|\bsol\b|\bliquido\b|\bfrasco\b|\bfco\b", "solucion"),
]
_FORMS = [(re.compile(p), f) for p, f in FORMS]
SOLID_FORMS = {"comprimido", "capsula", "comprimido efervescente", "comprimido masticable", "sobre", "supositorio"}

_RELEASE = re.compile(r"\b(lp|xr|sr|er|retard|liberacion prolongada|ret|ac\.? prolongada|odt|xl)\b")
_COMBO_MARK = re.compile(r"^[a-z][a-z\-]*[\s\-]+(d|h|hct|plus|duo|am|co|compuesto|forte|combi|met)\b")
# combo markers anywhere in the name: 'ACCORD 50-H', 'LOZAX D 50', 'X PLUS'
_COMBO_ANY = re.compile(r"(?:^|[\s\-])(h|d|hct|plus|duo|combi)(?=[\s\-.]|$)")
_SLASH_DOSE = re.compile(r"\b\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?(?!\s*(?:ml|g\b|dosis))")

_NUM = r"(\d+(?:[.,]\d+)?)"
_STRENGTH = re.compile(
    _NUM + r"(?:\s*/\s*" + _NUM + r")?(?:\s*/\s*" + _NUM + r")?\s*"
    r"(mg|mcg|µg|ug|microgramos?|g|gr|grs|ui|u\.i\.|%)"
    r"(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(ml|g|dosis|puff|gota|gotas))?(?![a-z])"
)
_PACK_COUNT = re.compile(
    r"(?:\bx\s*|\bpor\s+|\bde\s+|\bcaja\s+(?:de\s+)?|\bcj\.?\s*(?:x\s*)?|\b)(\d{1,3})\s*"
    r"(comp\w*|caps\w*|tab\w*|grag\w*|sobres?|c\b|com\b|unid\w*|un\b|cpr|supos\w*|perlas?|softgels?|dosis|puff\w*|inhal\w*)"
)
_PACK_X = re.compile(r"\bx\s*(\d{1,3})(?!\s*(?:ml|mg|g|gr|mcg|tiras?|blister|%|\d))\b")
_VOLUME_X = re.compile(r"\bx\s*(\d{1,4}(?:[.,]\d+)?)\s*(ml|cc|l)\b")
_VOLUME = re.compile(r"(?<![/\d.])\s*(\d{1,4}(?:[.,]\d+)?)\s*(ml|cc|l)\b(?!\s*/)")
_TIRAS = re.compile(r"\bx\s*\d+\s*tiras?\b|\bexhib")
_DOSES = re.compile(r"(\d{2,4})\s*(dosis|puff\w*|inhalaciones|aplicaciones)")
_LEADING_NUM = re.compile(r"^([a-z][a-z\-\. ]*?)\s+(\d+(?:[.,]\d+)?)(?!\s*(?:mg|mcg|g|ui|ml|%|comp|caps|tab|x|\d))\b")

# phrases in long descriptions that introduce the product's own active ingredient(s)
_DESC_CUE = re.compile(r"compuest[oa]s? (?:por|de)|a base de|contiene|asocia|combina|combinacion de|"
                       r"principio activo|droga|\(")

DEFAULT_UNIT = {"levotiroxina": "mcg", "vitamina d3": "ui", "salbutamol": "mcg"}
_GENERIC_LABS = {"eticos", "lasca", "bioethic", "catedral", "quimfa", "indufar", "pharmetica", "lepetit",
                 "felsan", "sanofi", "megalabs", "roemmers", "lab", "laboratorio"}


@dataclass
class Parsed:
    ingredients: list[str] = field(default_factory=list)
    ingredient_source: str | None = None  # name | structured | description | brand_dict | fuzzy
    strengths: list[tuple[float, str]] = field(default_factory=list)  # [(value, unit)] in order found
    strength_inferred: bool = False
    form: str | None = None
    form_inferred: bool = False
    release: str | None = None
    pack_size: float | None = None
    pack_unit: str | None = None  # unidad | ml | dosis
    brand_key: str | None = None
    is_generic: bool = False
    status: str = "failed"
    failure_reason: str | None = None

    @property
    def strength_text(self) -> str | None:
        if not self.strengths:
            return None
        units = {u for _, u in self.strengths}
        vals = "+".join(_fmt(v) for v, _ in self.strengths)
        return f"{vals} {self.strengths[0][1]}" if len(units) == 1 else "+".join(f"{_fmt(v)} {u}" for v, u in self.strengths)


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def find_ingredients(text: str, *, allow_weak: bool = True) -> list[str]:
    found: list[str] = []
    for m in _ALIAS_RE.finditer(text):
        alias = m.group(1)
        if alias in _WEAK_ALIASES and not allow_weak:
            continue
        c = _ALIAS_TO_CANON[alias]
        if c not in found:
            found.append(c)
    # 'folico' alone and 'acido folico' -> same; 'd3' alone only counts if 'vitamina'/'vit' nearby
    if "vitamina d3" in found and not re.search(r"vit\w*\.?\s*d\s*3|colecalciferol", text):
        found.remove("vitamina d3")
    return found


def fuzzy_ingredients(text: str) -> list[str]:
    found = []
    for tok in set(re.findall(r"[a-z]{7,}", text)):
        if tok in _ALIAS_TO_CANON:
            continue
        hit = process.extractOne(tok, _FUZZY_POOL, scorer=fuzz.ratio, score_cutoff=90)
        if hit:
            c = _ALIAS_TO_CANON[hit[0]]
            if c not in found:
                found.append(c)
    return found


def brand_key_of(name_f: str) -> str | None:
    """Leading words before the first digit / form word: 'convertal d 50 mg cj x 30' -> 'convertal d'."""
    lead = re.split(r"\d|\b(?:x|cj|caja|comp\w*|caps\w*|tab\w*|jarabe|susp\w*|gotas|blister|fco|frasco|sobres?|"
                    r"iny\w*|crema|gel|inhal\w*|aerosol|spray|sol|solucion|ampollas?|polvo|grageas?)\b",
                    name_f, maxsplit=1)[0]
    lead = re.sub(r"[^a-z ]+", " ", lead)
    words = re.sub(r"\s+", " ", lead).strip().split(" ")
    while len(words) > 1 and words[0] in _GENERIC_LABS:  # 'lepetit prisonil d' -> 'prisonil d'
        words = words[1:]
    return " ".join(words) or None


def _strengths(text: str) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for m in _STRENGTH.finditer(text):
        vals = [v for v in m.group(1, 2, 3) if v]
        unit = m.group(4)
        per_n, per_u = m.group(5), m.group(6)
        unit = {"µg": "mcg", "ug": "mcg", "microgramo": "mcg", "microgramos": "mcg", "gr": "g", "grs": "g",
                "u.i.": "ui"}.get(unit, unit)
        for v in vals:
            val = _num(v)
            u = unit
            if u == "g" and not per_u:  # grams of active -> mg (amoxicilina 1 g)
                val, u = val * 1000, "mg"
            if per_u:
                n = _num(per_n) if per_n else 1.0
                if per_u in ("ml",) and n and n != 1:
                    val = val / n
                u = f"{u}/{per_u if per_u in ('ml', 'g', 'dosis') else 'dosis'}"
                if u == "mg/g" or u == "%":
                    pass
            if (val, u) not in out:
                out.append((val, u))
    return out


def parse_product(name: str, description: str | None = None, structured: str | None = None,
                  brand_dict: dict[str, list[str]] | None = None) -> Parsed:
    p = Parsed()
    n = fold(name)
    n = re.sub(r"(\d)\s*,\s*(\d)", r"\1.\2", n)  # 12,5 -> 12.5
    desc = fold(description)
    desc = re.sub(r"(\d)\s*,\s*(\d)", r"\1.\2", desc)
    struct = fold(structured)

    p.brand_key = brand_key_of(n)

    # ---- ingredients: name > structured field > description > fuzzy > learned brand dictionary
    ings = find_ingredients(n)
    src = "name" if ings else None
    if struct:
        s_ings = find_ingredients(struct)
        if s_ings and (not ings or len(s_ings) > len(ings)):
            ings, src = s_ings, "structured"
    if desc:
        # only the first ~250 chars: later sentences mention interactions ("no combinar con ibuprofeno")
        d_ings = find_ingredients(desc[:250], allow_weak=False)
        for m in _DESC_CUE.finditer(desc):
            for c in find_ingredients(desc[m.end():m.end() + 90], allow_weak=False):
                if c not in d_ings:
                    d_ings.append(c)
        if d_ings and (not ings or (set(ings) < set(d_ings) and len(d_ings) <= 3)):
            ings, src = d_ings, ("description" if not ings else src + "+description")
    if not ings:
        f = fuzzy_ingredients(n)
        if f:
            ings, src = f, "fuzzy"
    if not ings and brand_dict and p.brand_key:
        hit = brand_dict.get(p.brand_key)
        if hit is None and len(p.brand_key) >= 5:
            m = process.extractOne(p.brand_key, list(brand_dict), scorer=fuzz.ratio, score_cutoff=92)
            hit = brand_dict[m[0]] if m else None
        if hit:
            ings, src = list(hit), "brand_dict"
    # a chain listing only part of a combination (Oliva: CONVERTAL-D -> 'Hidroclorotiazida'):
    # if another chain's evidence for this brand is a strict superset, trust that
    if ings and brand_dict and p.brand_key:
        known = brand_dict.get(p.brand_key)
        if known and set(ings) < set(known):
            ings, src = list(known), (src or "") + "+brand_dict"
    p.ingredients, p.ingredient_source = sorted(ings), src

    # combo marker with a single detected ingredient ('CONVERTAL D', 'ACCORD-H') -> we can't trust it
    combo_suspect = len(ings) == 1 and ings[0] != "vitamina d3" and (
        (bool(_COMBO_MARK.match(n)) and p.brand_key and not any(p.brand_key.startswith(a) for a in _ALIAS_TO_CANON))
        or bool(_SLASH_DOSE.search(n))  # '50/850' with one known ingredient -> partner unknown
        or bool(_COMBO_ANY.search(n))
    )

    # ---- strength
    p.strengths = _strengths(n)
    if not p.strengths and desc:
        p.strengths = _strengths(desc[:250])
    if not p.strengths and len(ings) == 1:
        m = _LEADING_NUM.match(n)  # 'convertal 100 cj x 30' / 'eutirox 50'
        if m:
            p.strengths = [(_num(m.group(2)), DEFAULT_UNIT.get(ings[0], "mg"))]
            p.strength_inferred = True
    if len(ings) == 1 and len(p.strengths) > 1:
        # keep the mass strength, drop e.g. a second 'mg/ml' restatement
        p.strengths = p.strengths[:1]

    # ---- form & release
    for rx, f in _FORMS:
        if rx.search(n):
            p.form = f
            break
    if not p.form and desc:
        for rx, f in _FORMS:
            if rx.search(desc[:250]):
                p.form, p.form_inferred = f, True
                break
    rel = _RELEASE.search(n)
    p.release = "prolongada" if rel and rel.group(1) != "odt" else ("dispersable" if rel else None)

    # ---- pack size
    if p.form in SOLID_FORMS or p.form is None:
        m = _PACK_COUNT.search(n)
        if m:
            p.pack_size, p.pack_unit = float(m.group(1)), "unidad"
        elif not _TIRAS.search(n) and (m := _PACK_X.search(n)):
            p.pack_size, p.pack_unit = float(m.group(1)), "unidad"
        elif desc and (m := _PACK_COUNT.search(desc[:300])):
            p.pack_size, p.pack_unit = float(m.group(1)), "unidad"
        if p.form is None and p.pack_unit == "unidad":
            p.form, p.form_inferred = "comprimido", True  # 'CJ X 30' with no form word: almost always tablets
    elif p.form == "inhalador":
        m = _DOSES.search(n) or (_DOSES.search(desc[:300]) if desc else None)
        if m:
            p.pack_size, p.pack_unit = float(m.group(1)), "dosis"
    else:
        m = _VOLUME_X.search(n) or _VOLUME.search(re.sub(r"/\s*\d+(?:[.,]\d+)?\s*ml", "/ml", n)) \
            or (_VOLUME.search(desc[:300]) if desc else None)
        if m:
            v = _num(m.group(1))
            p.pack_size, p.pack_unit = (v * 1000 if m.group(2) == "l" else v), "ml"
        elif p.form == "sobre" and (m := _PACK_X.search(n)):
            p.pack_size, p.pack_unit = float(m.group(1)), "unidad"

    # ---- brand vs generic
    bk = p.brand_key or ""
    first_word = bk.split(" ")[0] if bk else ""
    p.is_generic = bool(ings) and (
        any(bk.startswith(a) for a in _ALIAS_TO_CANON if len(a) > 3)
        or first_word in {"acido", "vitamina", "vit"} and src == "name"
    )

    # ---- status
    missing = []
    if not ings:
        missing.append("ingredient")
    if combo_suspect:
        missing.append("combo partner unknown")
    if not p.strengths and not (ings and ings[0] in ("salbutamol", "vitamina d3")):
        missing.append("strength")
    if not p.form:
        missing.append("form")
    if not p.pack_size:
        missing.append("pack size (tiras/exhibidor)" if _TIRAS.search(n) else "pack size")
    if not ings:
        p.status = "failed"
    elif combo_suspect:
        p.status = "failed"
    elif missing:
        p.status = "partial"
    else:
        p.status = "clean"
    p.failure_reason = ", ".join(missing) or None
    return p


def build_brand_dict(rows: list[tuple[str, list[str]]]) -> dict[str, list[str]]:
    """brand_key -> most common ingredient set, from products whose ingredients were found directly."""
    votes: dict[str, Counter] = {}
    for brand_key, ings in rows:
        if brand_key and ings:
            votes.setdefault(brand_key, Counter())[tuple(sorted(ings))] += 1
    return {k: list(c.most_common(1)[0][0]) for k, c in votes.items()}
