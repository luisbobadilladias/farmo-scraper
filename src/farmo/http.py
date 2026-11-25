"""Polite, cached HTTP client shared by all chain scrapers.

- Sequential only; 1–2s random delay between *network* requests (cache hits are free).
- robots.txt checked per host before every network fetch.
- Raw responses cached at data/raw/{chain}/{date}/{sha1(url)}.{ext}, with an index.jsonl
  mapping URL -> file. Set FARMO_DATE=YYYY-MM-DD to replay an earlier day's cache.
"""

import hashlib
import json
import logging
import os
import random
import time
import urllib.robotparser
from datetime import date
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx

from .models import Blocked

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BOT_WALL_HOSTS = ("validate.perfdrive.com",)


def cache_date() -> str:
    return os.environ.get("FARMO_DATE") or date.today().isoformat()


class PoliteClient:
    def __init__(self, min_delay: float = 1.0, max_delay: float = 2.0, offline: bool = False):
        self.min_delay, self.max_delay = min_delay, max_delay
        self.offline = offline  # True -> never touch the network, cache only
        self._last_request = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.stats = {"network": 0, "cache": 0}
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es-PY,es;q=0.9"},
            timeout=30,
            follow_redirects=False,
        )

    # -- internals ---------------------------------------------------------
    def _sleep(self):
        wait = self._last_request + random.uniform(self.min_delay, self.max_delay) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(host)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            self._sleep()
            r = self._client.get(f"{host}/robots.txt")
            self.stats["network"] += 1
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            self._robots[host] = rp
        return rp.can_fetch("*", url)

    @staticmethod
    def _cache_path(chain: str, url: str, ext: str) -> Path:
        key = hashlib.sha1(url.encode()).hexdigest()[:20]
        return RAW_DIR / chain / cache_date() / f"{key}.{ext}"

    # -- public ------------------------------------------------------------
    def get(self, chain: str, url: str, params: dict | None = None, *, ext: str = "html",
            headers: dict | None = None) -> str:
        if params:
            url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        path = self._cache_path(chain, url, ext)
        if path.exists():
            self.stats["cache"] += 1
            return path.read_text(encoding="utf-8")
        if self.offline:
            raise FileNotFoundError(f"not cached (offline mode): {url}")
        if not self._allowed(url):
            raise Blocked(f"robots.txt disallows {url}")

        self._sleep()
        r = self._client.get(url, headers=headers)
        self.stats["network"] += 1
        if r.is_redirect:
            loc = r.headers.get("location", "")
            if any(h in loc for h in BOT_WALL_HOSTS):
                raise Blocked(f"bot wall redirect: {urlsplit(loc).netloc}")
            # follow ordinary redirects once (relative or absolute)
            target = str(r.next_request.url) if r.next_request else loc
            log.debug("redirect %s -> %s", url, target)
            return self.get(chain, target, ext=ext, headers=headers)
        if r.status_code == 403 and ("cf-mitigated" in r.headers or "captcha" in r.text[:5000].lower()):
            raise Blocked(f"challenge page (HTTP 403) at {url}")
        r.raise_for_status()
        head = r.text[:3000]
        if "<title>Radware Page</title>" in head or "perfdrive.com" in r.text[:20000]:
            raise Blocked(f"bot wall page (Radware) served with HTTP {r.status_code} at {url}")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(r.text, encoding="utf-8")
        with open(path.parent / "index.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"url": url, "file": path.name, "status": r.status_code}) + "\n")
        return r.text

    def get_json(self, chain: str, url: str, params: dict | None = None, headers: dict | None = None):
        h = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest", **(headers or {})}
        return json.loads(self.get(chain, url, params, ext="json", headers=h))


_default: PoliteClient | None = None


def client() -> PoliteClient:
    global _default
    if _default is None:
        _default = PoliteClient(offline=os.environ.get("FARMO_OFFLINE") == "1")
    return _default
