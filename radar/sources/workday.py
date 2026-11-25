"""Workday's public CXS endpoint (the same one their career site calls)."""
import re
import threading
import time
from datetime import date, timedelta

from ..models import RawJob

PAGE = 20          # Workday caps page size at 20
MAX_PAGES = 15
PAGE_DELAY = 1.5   # seconds between page requests; Workday answers bursts with HTTP 429
_MULTI = re.compile(r"^\d+ Locations?$", re.I)
_DAYS_AGO = re.compile(r"(\d+)\+?\s*days?\s*ago", re.I)
# Workday tenants share infrastructure (e.g. NVIDIA and Adobe are both on wd5) and rate-limit
# by client IP, so fetch one Workday board at a time instead of in parallel.
_LOCK = threading.Lock()


def _base(c):
    return f"https://{c['host']}/wday/cxs/{c['tenant']}/{c['site']}/jobs"


def fetch(company, http):
    with _LOCK:
        jobs, offset = [], 0
        for i in range(MAX_PAGES):
            if i:
                time.sleep(PAGE_DELAY)
            data = http.post_json(_base(company), {
                "appliedFacets": {}, "limit": PAGE, "offset": offset,
                "searchText": company.get("search", ""),
            })
            page = parse(data, company)
            jobs.extend(page)
            offset += PAGE
            if not page or offset >= data.get("total", 0):
                break
        time.sleep(PAGE_DELAY)   # breathing room before the next Workday board
        return jobs


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
