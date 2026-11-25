"""Punto Farma — blocked.

Every page on www.puntofarma.com.py either 302-redirects plain HTTP clients to a Radware Bot Manager
challenge (validate.perfdrive.com) or serves the Radware JS loader page with HTTP 200. Per project rules we don't work around bot walls.
"""

from ..http import client
from ..models import Blocked, RawProduct

CHAIN = "puntofarma"
BASE = "https://www.puntofarma.com.py"


def search(query: str) -> list[RawProduct]:
    # One real attempt so the block is observed (and logged), not assumed.
    client().get(CHAIN, f"{BASE}/buscar", {"q": query})
    raise Blocked("unexpected: Punto Farma responded without a bot wall — implement a parser")
