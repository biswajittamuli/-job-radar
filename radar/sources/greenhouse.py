from ..models import RawJob
from ..text import strip_html

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def fetch(company, http):
    data = http.get_json(API.format(slug=company["slug"]), content="true")
    return parse(data, company)


def parse(data, company):
    out = []
    for j in data.get("jobs", []):
        locs = []
        if (j.get("location") or {}).get("name"):
            locs.append(j["location"]["name"])
        for o in j.get("offices") or []:
            if o.get("location"):
                locs.append(o["location"])
            elif o.get("name"):
                locs.append(o["name"])
        out.append(RawJob(
            source_id=str(j["id"]),
            title=(j.get("title") or "").strip(),
            url=j.get("absolute_url", ""),
            locations=list(dict.fromkeys(locs)),
            posted_at=(j.get("first_published") or j.get("updated_at") or "")[:10] or None,
            description=strip_html(j.get("content")),
            team=", ".join(d.get("name", "") for d in j.get("departments") or []),
        ))
    return out
