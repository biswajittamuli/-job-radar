"""Freshteam careers widgets (<company>.freshteam.com/hire/widgets/jobs.json).

  { name: Everstage, ats: freshteam, slug: everstage }
"""
from ..models import RawJob
from ..text import strip_html


def fetch(company, http):
    return parse(http.get_json(f"https://{company['slug']}.freshteam.com/hire/widgets/jobs.json"), company)


def parse(data, company):
    branches = {str(b.get("id")): b for b in (data or {}).get("branches") or []}
    out = []
    for j in (data or {}).get("jobs") or []:
        if j.get("deleted") in (True, "true", "True"):
            continue
        b = branches.get(str(j.get("branch_id"))) or {}
        loc = b.get("location") or ", ".join(x.strip() for x in (b.get("city"), b.get("state")) if x)
        if b.get("country_code") == "IN" and "india" not in loc.lower():
            loc = f"{loc}, India" if loc else "India"
        remote = str(j.get("remote")).lower() == "true"
        out.append(RawJob(
            source_id=str(j["id"]),
            title=(j.get("title") or "").strip(),
            url=j.get("url") or f"https://{company['slug']}.freshteam.com/jobs/{j.get('unique_id', '')}",
            locations=[loc] if loc else (["Remote"] if remote else []),
            posted_at=(j.get("created_at") or "")[:10] or None,
            description=strip_html(j.get("description")),
            remote=remote or None,
        ))
    return out
