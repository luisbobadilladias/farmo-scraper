from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class RawProduct:
    chain: str
    name: str
    price: int | None  # what you pay online today (sale/web price), PYG
    url: str
    list_price: int | None = None  # "before" / list price, PYG
    brand: str | None = None  # lab / marca as the chain reports it
    description: str | None = None  # long name / description text (often contains the ingredient)
    ingredient: str | None = None  # structured active ingredient when the chain exposes one
    ean: str | None = None
    sku: str | None = None  # chain-internal code
    in_stock: bool | None = None
    rx: str | None = None  # e.g. "Venta libre", "Bajo receta"
    category: str | None = None
    image: str | None = None
    search_term: str | None = None  # the literal string sent to the site's search
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)


class Blocked(Exception):
    """Site blocks automated access (bot wall / CAPTCHA / robots). We don't work around it."""
