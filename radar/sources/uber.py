"""Uber careers (jobs.uber.com). The search API ignores location filters, so we read every
posting (about 9 pages of 100) and let the classifier keep India/remote ones."""
from ..models import RawJob
from ..text import strip_html

API = "https://jobs.uber.com/api/jobs/search/"
MAX_PAGES = 20


def fetch(company, http):
    jobs = []
    for page in range(1, MAX_PAGES + 1):
        data = http.get_json(API, pagesize=100, page=page)
        jobs.extend(parse(data, company))
        if page >= (data.get("totalPages") or 0):
            break
    return jobs


def parse(data, company):
    out = []
    for j in data.get("jobs") or []:
        locs = []
        for l in j.get("Locations") or []:
            label = ", ".join(x for x in (l.get("City"), l.get("Region"), l.get("Country")) if x)
            if label:
                locs.append(label)
        path = next((u.get("Url") for u in j.get("Urls") or [] if u.get("IsDefault")), f"/en/jobs/{j['Id']}/")
        out.append(RawJob(
            source_id=str(j["Id"]),
            title=(j.get("Title") or "").strip(),
            url="https://jobs.uber.com" + path,
            locations=locs,
            posted_at=(j.get("DisplayDate") or "")[:10] or None,
            description=strip_html(j.get("Description")),
            remote=str(j.get("Remote")).lower() == "true" or None,
            team=", ".join(j.get("Teams") or []),
            level_hint=(j.get("ExperienceLevel") or "").lower().replace(" ", "_") if j.get("ExperienceLevel") else "",
        ))
    return out
