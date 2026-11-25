"""Keka Hire careers pages (<company>.keka.com/careers), used by many Indian startups.

  host: jupiter.keka.com          # the careers page's host; the company's portal id is
                                  # read from that page, so nothing else is needed
"""
import re

from ..models import RawJob
from ..text import strip_html

_PORTAL = re.compile(r"/ats/documents/([0-9a-f-]{36})/careerportal/")


def fetch(company, http):
    host = company["host"]
    guid = company.get("portal_id")
    if not guid:
        m = _PORTAL.search(http.get_text(f"https://{host}/careers/"))
        guid = m.group(1) if m else None
    if guid:     # a company-designed careers portal
        return parse(http.get_json(f"https://{host}/careers/api/embedjobs/default/active/{guid}"), company)
    # Keka's standard careers page
    return parse(http.get_json(f"https://{host}/careers/api/jobs/default/active"), company)


def parse(data, company):
    out = []
    for j in data or []:
        locs = []
        for l in j.get("jobLocations") or []:
            parts = [l.get("city"), l.get("state"), l.get("countryName") or l.get("country")]
            label = ", ".join(p for p in parts if p) or l.get("name") or ""
            if label:
                locs.append(label)
        exp = (j.get("experience") or "").strip()
        desc = strip_html(j.get("description"))
        out.append(RawJob(
            source_id=str(j["id"]),
            title=strip_html(j.get("title")),
            url=f"https://{company['host']}/careers/jobdetails/{j['id']}",
            # Keka is used by Indian companies and often leaves locations empty
            locations=locs or [company.get("location", "India")],
            posted_at=(j.get("publishedOn") or "")[:10] or None,
            # the structured experience field ("0-1 Years") feeds the years check
            description=(f"Experience: {exp}. " if exp else "") + desc,
            team=j.get("departmentName") or "",
        ))
    return out
