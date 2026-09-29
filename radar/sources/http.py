"""Shared, polite HTTP client for InternRadar: identifies itself, retries briefly, and paces requests."""
from __future__ import annotations

import html
import re
import time

import requests

USER_AGENT = "InternRadar/1.0 (personal internship search tool; low-volume, paced requests)"
_session: requests.Session | None = None
_last = 0.0


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9"})
    return _session


def request(method: str, url: str, *, pace: float = 0.8, retries: int = 2, **kw) -> requests.Response:
    """Send a request at most every `pace` seconds, retrying on network errors and 429/5xx."""
    global _last
    kw.setdefault("timeout", 25)
    for attempt in range(retries + 1):
        wait = pace - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        try:
            r = session().request(method, url, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt >= retries:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def html_to_text(s: str) -> str:
    """Turn (possibly entity-escaped) HTML into readable plain text."""
    s = html.unescape(html.unescape(s or ""))
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()
