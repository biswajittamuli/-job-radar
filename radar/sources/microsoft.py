"""Eightfold careers API ("pcsx"). Defaults are Microsoft's (apply.careers.microsoft.com);
other Eightfold customers use ats: eightfold with their own `host` and `domain`, e.g.
  { name: Qualcomm, ats: eightfold, host: careers.qualcomm.com, domain: qualcomm.com }"""
from datetime import date, datetime, timedelta, timezone

from ..models import RawJob
from ..text import strip_html

MAX_PAGES = 60     # 10 jobs per page
STOP_AFTER_DAYS = 100  # results are newest first: stop paging once postings are older than this


def _base(c):
    return f"https://{c.get('host', 'apply.careers.microsoft.com')}"


def fetch(company, http):
    jobs, start = [], 0
    for _ in range(MAX_PAGES):
        data = http.get_json(_base(company) + "/api/pcsx/search", domain=company.get("domain", "microsoft.com"),
                             query=company.get("query", ""), location=company.get("location", "India"),
                             start=start, sort_by="timestamp")["data"]
        page = parse(data, company)
        jobs.extend(page)
        start += len(data.get("positions") or [])
        if not page or start >= data.get("count", 0):
            break
        cutoff = (date.today() - timedelta(days=STOP_AFTER_DAYS)).isoformat()
        if all(j.posted_at and j.posted_at < cutoff for j in page):
            break
    return jobs


def parse(data, company):
    out = []
    for p in data.get("positions") or []:
        ts = p.get("postedTs") or p.get("creationTs")
        out.append(RawJob(
            source_id=str(p["id"]),
            title=(p.get("name") or "").strip(),
            url=_base(company) + (p.get("positionUrl") or f"/careers/job/{p['id']}"),
            locations=p.get("locations") or [],
            posted_at=datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else None,
            remote=(p.get("workLocationOption") == "remote") or None,
            team=p.get("department") or "",
        ))
    return out


def describe(company, job, http):
    data = http.get_json(_base(company) + "/api/pcsx/position_details", position_id=job.source_id,
                         domain=company.get("domain", "microsoft.com"), hl="en")["data"]
    job.description = strip_html(data.get("jobDescription"))
    return job
