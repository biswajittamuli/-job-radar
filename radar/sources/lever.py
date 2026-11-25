from datetime import datetime, timezone

from ..http import BoardNotFound
from ..models import RawJob
from ..text import strip_html

API = "https://api.lever.co/v0/postings/{slug}"


def fetch(company, http):
    data = http.get_json(API.format(slug=company["slug"]), mode="json")
    if isinstance(data, dict):  # {"ok": false, "error": "Document not found"}
        raise BoardNotFound(data.get("error", "lever board not found"))
    return parse(data, company)


def parse(data, company):
    out = []
    for j in data:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or ([cat["location"]] if cat.get("location") else [])
        desc_parts = [j.get("descriptionPlain") or ""]
        for lst in j.get("lists") or []:
            desc_parts.append(lst.get("text", ""))
            desc_parts.append(strip_html(lst.get("content")))
        desc_parts.append(j.get("additionalPlain") or "")
        created = j.get("createdAt")
        posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat()
                  if created else None)
        out.append(RawJob(
            source_id=j["id"],
            title=(j.get("text") or "").strip(),
            url=j.get("hostedUrl", ""),
            locations=locs,
            posted_at=posted,
            description=" ".join(p for p in desc_parts if p),
            remote=(j.get("workplaceType") == "remote") or None,
            team=cat.get("team", ""),
        ))
    return out
