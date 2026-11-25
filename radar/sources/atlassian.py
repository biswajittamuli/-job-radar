"""Atlassian careers: one public JSON list of every opening (www.atlassian.com/endpoint/careers/listings)."""
from datetime import datetime

from ..models import RawJob
from ..text import strip_html

API = "https://www.atlassian.com/endpoint/careers/listings"


def fetch(company, http):
    return parse(http.get_json(API), company)


def _date(s):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %I:%M %p").date().isoformat()
    except (ValueError, AttributeError):
        return None


def parse(data, company):
    out = []
    for j in data or []:
        post = j.get("portalJobPost") or {}
        # "Bengaluru - India -   Bengaluru,  560071 India" → tidy whitespace
        locs = [" ".join(l.split()) for l in j.get("locations") or []]
        out.append(RawJob(
            source_id=str(j["id"]),
            title=(j.get("title") or "").strip(),
            url=post.get("portalUrl") or j.get("applyUrl") or "https://www.atlassian.com/company/careers/all-jobs",
            locations=locs,
            posted_at=_date(post.get("updatedDate")),
            description=" ".join(strip_html(j.get(k)) for k in ("qualifications", "responsibilities", "overview") if j.get(k)),
            remote=any("remote" in l.lower() for l in locs) or None,
            team=j.get("category") or "",
        ))
    return out
