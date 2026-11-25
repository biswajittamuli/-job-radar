"""Jooble job-search API (jooble.org/api/about): jobs from many sites and companies.

Needs a free API key in the JOOBLE_KEY environment variable (a GitHub Actions secret).
Without it this source is skipped, not reported as broken.

  - name: Jooble
    ats: jooble
    location: India
    queries: [software engineer fresher, ...]

The key is part of the request URL, so errors are re-raised without the URL: they end
up in data/health.json, which is committed to the (public) repo.
"""
import os

from ..http import SourceDisabled
from ..models import RawJob
from ..text import strip_html

AGGREGATOR = True      # jobs come from many companies; the runner de-duplicates them
API = "https://{host}/api/{key}"   # host: jooble.org, or a country site such as in.jooble.org
PAGES_PER_QUERY = 2    # 20 results per page


def _key():
    key = (os.getenv("JOOBLE_KEY") or "").strip()
    if not key:
        raise SourceDisabled("JOOBLE_KEY secret not set")
    return key


def _post(http, key, body, host="jooble.org"):
    try:
        return http.post_json(API.format(host=host, key=key), body)
    except Exception as e:  # noqa: BLE001 — scrub the key out of whatever went wrong
        raise RuntimeError(f"Jooble API error: {type(e).__name__}: {str(e).replace(key, '***')}"[:200]) from None


def fetch(company, http):
    key = _key()
    seen, out = set(), []
    for q in company.get("queries") or ["software engineer fresher"]:
        for page in range(1, company.get("pages_per_query", PAGES_PER_QUERY) + 1):
            data = _post(http, key, {"keywords": q, "location": company.get("location", "India"), "page": str(page)},
                         company.get("host", "jooble.org"))
            batch = parse(data, company)
            for j in batch:
                if j.source_id not in seen:
                    seen.add(j.source_id)
                    out.append(j)
            if len(batch) < 20:
                break
    return out


def parse(data, company):
    out = []
    for j in (data or {}).get("jobs") or []:
        loc = (j.get("location") or "").strip()
        out.append(RawJob(
            source_id=str(j.get("id") or j.get("link")),
            title=strip_html(j.get("title")),
            url=j.get("link") or "",
            # Jooble's India results give just the city; add the country for the filter
            locations=[loc if not loc or "india" in loc.lower() else f"{loc}, India"] if loc else [company.get("location", "India")],
            posted_at=(j.get("updated") or "")[:10] or None,
            description=strip_html(j.get("snippet")),
            company=(j.get("company") or "").strip(),
        ))
    return out
