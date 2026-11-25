from __future__ import annotations

import time

import requests

UA = "Mozilla/5.0 (job-radar; personal job tracker; +https://github.com)"


class BoardNotFound(Exception):
    """The board id/slug is wrong or the company moved ATS."""


class RateLimited(RuntimeError):
    """The server kept answering HTTP 429. Not a broken board: it usually works next run."""


class Http:
    def __init__(self, timeout: int = 25, retries: int = 4):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json"})
        self.timeout = timeout
        self.retries = retries

    def _req(self, method: str, url: str, **kw):
        last = None
        for attempt in range(self.retries):
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
                if r.status_code == 404:
                    raise BoardNotFound(f"404 at {url}")
                if r.status_code in (429, 500, 502, 503, 504):
                    last = (RateLimited if r.status_code == 429 else RuntimeError)(f"HTTP {r.status_code} at {url}")
                    if attempt + 1 < self.retries:
                        time.sleep(self._backoff(r, attempt))
                    continue
                r.raise_for_status()
                return r
            except BoardNotFound:
                raise
            except requests.RequestException as e:
                last = e
                time.sleep(2 ** attempt)
        raise last or RuntimeError(f"failed: {url}")

    @staticmethod
    def _backoff(r, attempt: int) -> float:
        """Honour Retry-After when the server sends one (capped); otherwise back off
        harder on 429 (rate limit) than on 5xx."""
        ra = r.headers.get("Retry-After", "")
        if ra.strip().isdigit():
            return min(int(ra), 60)
        return (5 if r.status_code == 429 else 2) * 2 ** attempt

    def get_json(self, url: str, headers: dict | None = None, **params):
        return self._req("GET", url, params=params or None, headers=headers).json()

    def post_json(self, url: str, body: dict, headers: dict | None = None):
        return self._req("POST", url, json=body, headers=headers).json()

    def get_text(self, url: str) -> str:
        r = self._req("GET", url, headers={"Accept": "text/html,*/*"})
        return r.text
