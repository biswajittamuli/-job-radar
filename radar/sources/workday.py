"""Workday's public CXS endpoint (the same one their career site calls)."""
import re
import threading
import time
from datetime import date, timedelta

from ..models import RawJob
from ..text import strip_html

PAGE = 20          # Workday caps page size at 20
MAX_PAGES = 15
PAGE_DELAY = 1.5   # seconds between page requests; Workday answers bursts with HTTP 429
_MULTI = re.compile(r"^\d+ Locations?$", re.I)
_DAYS_AGO = re.compile(r"(\d+)\+?\s*days?\s*ago", re.I)
# Workday tenants share infrastructure (e.g. NVIDIA and Adobe are both on wd5) and rate-limit
# by client IP, so fetch one Workday board at a time instead of in parallel.
_LOCK = threading.Lock()


def _base(c):
    return f"https://{c['host']}/wday/cxs/{c['tenant']}/{c['site']}"


def _headers(c):
    # What the career site's own JavaScript sends. Without Origin/Referer (and the cookies
    # from loading the page once) Workday's Cloudflare front end answers 429 far sooner.
    page = f"https://{c['host']}/en-US/{c['site']}"
    return {"Accept": "application/json", "Content-Type": "application/json",
            "Origin": f"https://{c['host']}", "Referer": page}


def _warm_up(c, http):
    try:
        http.get_text(f"https://{c['host']}/en-US/{c['site']}")
    except Exception:  # noqa: BLE001 — cookies are a nice-to-have; the API call decides
        pass


def fetch(company, http):
    with _LOCK:
        _warm_up(company, http)
        jobs, offset = [], 0
        for i in range(MAX_PAGES):
            if i:
                time.sleep(PAGE_DELAY)
            data = http.post_json(_base(company) + "/jobs", {
                "appliedFacets": {}, "limit": PAGE, "offset": offset,
                "searchText": company.get("search", ""),
            }, headers=_headers(company))
            page = parse(data, company)
            jobs.extend(page)
            offset += PAGE
            if not page or offset >= data.get("total", 0):
                break
        time.sleep(PAGE_DELAY)   # breathing room before the next Workday board
        return jobs


def describe(company, job, http):
    """Fill in the full description, exact posting date and every location of one job.
    Called only for jobs that already passed the title/location pre-check."""
    with _LOCK:
        time.sleep(PAGE_DELAY)
        data = http.get_json(_base(company) + job.source_id, headers=_headers(company))
    apply_detail(job, data)
    return job


def apply_detail(job, data):
    info = (data or {}).get("jobPostingInfo") or {}
    job.description = strip_html(info.get("jobDescription")) or job.description
    if info.get("startDate"):           # the real posting date, e.g. "2026-11-20"
        job.posted_at = str(info["startDate"])[:10]
    elif info.get("postedOn"):
        job.posted_at = posted_on_to_date(info["postedOn"]) or job.posted_at
    locs = [info.get("location")] + list(info.get("additionalLocations") or [])
    locs = [l for l in locs if l]
    if locs:
        job.locations = list(dict.fromkeys(locs))


def posted_on_to_date(text, today=None):
    """'Posted Today' / 'Posted Yesterday' / 'Posted 5 Days Ago' / 'Posted 30+ Days Ago'
    → ISO date. '30+' becomes 30 days, a lower bound, so the freshness filter still drops it."""
    if not text:
        return None
    today = today or date.today()
    t = text.strip().lower()
    if "today" in t or "just posted" in t:
        days = 0
    elif "yesterday" in t:
        days = 1
    else:
        m = _DAYS_AGO.search(t)
        if not m:
            return None
        days = int(m.group(1))
    return (today - timedelta(days=days)).isoformat()


def parse(data, company, today=None):
    out = []
    search = company.get("search", "")
    for j in data.get("jobPostings", []):
        path = j.get("externalPath") or ""
        loc = j.get("locationsText") or ""
        if _MULTI.match(loc):
            # Workday hides multi-location lists; we searched by location, so record that.
            loc = f"Multiple locations ({search})" if search else loc
        out.append(RawJob(
            source_id=path or j.get("title", ""),
            title=(j.get("title") or "").strip(),
            url=f"https://{company['host']}/en-US/{company['site']}{path}",
            locations=[loc] if loc else [],
            posted_at=posted_on_to_date(j.get("postedOn"), today),
        ))
    return out
