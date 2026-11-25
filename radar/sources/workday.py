"""Workday's public CXS endpoint (the same one their career site calls)."""
import re

from ..models import RawJob

PAGE = 20          # Workday caps page size at 20
MAX_PAGES = 15
_MULTI = re.compile(r"^\d+ Locations?$", re.I)


def _base(c):
    return f"https://{c['host']}/wday/cxs/{c['tenant']}/{c['site']}/jobs"


def fetch(company, http):
    jobs, offset = [], 0
    for _ in range(MAX_PAGES):
        data = http.post_json(_base(company), {
            "appliedFacets": {}, "limit": PAGE, "offset": offset,
            "searchText": company.get("search", ""),
        })
        page = parse(data, company)
        jobs.extend(page)
        offset += PAGE
        if not page or offset >= data.get("total", 0):
            break
    return jobs


def parse(data, company):
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
            posted_at=None,   # Workday only gives "Posted 3 Days Ago"; first_seen covers it
        ))
    return out
