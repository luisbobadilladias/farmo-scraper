import re


def parse_pyg(text: str | None) -> int | None:
    """'₲. 37.800' / 'PYG 37.800' / 'Gs. 41.000' -> 37800. Guaraníes have no decimals."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def fold(text: str | None) -> str:
    """Lowercase + strip accents: 'LOSARTÁN Potásico' -> 'losartan potasico'."""
    import unicodedata

    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
