from ..models import RawJob
from ..text import strip_html

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def fetch(company, http):
    data = http.get_json(API.format(slug=company["slug"]))
    return parse(data, company)


def parse(data, company):
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j["location"]] if j.get("location") else []
        for s in j.get("secondaryLocations") or []:
            if s.get("location"):
                locs.append(s["location"])
        out.append(RawJob(
            source_id=j["id"],
            title=(j.get("title") or "").strip(),
            url=j.get("jobUrl") or j.get("applyUrl", ""),
            locations=locs,
            posted_at=(j.get("publishedAt") or "")[:10] or None,
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
            remote=j.get("isRemote"),
            team=j.get("department") or j.get("team") or "",
        ))
    return out
