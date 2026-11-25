from ..http import BoardNotFound
from ..models import RawJob
from ..text import strip_html

API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
PAGE = 100
MAX_PAGES = 10


def fetch(company, http):
    slug = company["slug"]
    jobs, offset = [], 0
    for _ in range(MAX_PAGES):
        # country=in keeps the payload small; remote roles are re-checked by the filter
        data = http.get_json(API.format(slug=slug), limit=PAGE, offset=offset,
                             country=company.get("country", "in"))
        if offset == 0 and data.get("totalFound", 0) == 0 and not company.get("allow_empty"):
            raise BoardNotFound(f"SmartRecruiters company '{slug}' returned no postings")
        jobs.extend(parse(data, company))
        offset += PAGE
        if offset >= data.get("totalFound", 0):
            break
    return jobs


def parse(data, company):
    out = []
    for j in data.get("content", []):
        loc = j.get("location") or {}
        parts = [loc.get("city"), loc.get("region"), loc.get("country")]
        label = loc.get("fullLocation") or ", ".join(p for p in parts if p)
        if (loc.get("country") or "").lower() == "in" and "india" not in label.lower():
            label += ", India"
        out.append(RawJob(
            source_id=str(j["id"]),
            title=(j.get("name") or "").strip(),
            url=f"https://jobs.smartrecruiters.com/{company['slug']}/{j['id']}",
            locations=[label] if label else [],
            posted_at=(j.get("releasedDate") or "")[:10] or None,
            remote=loc.get("remote"),
            team=(j.get("department") or {}).get("label", ""),
            level_hint=(j.get("experienceLevel") or {}).get("id", ""),
        ))
    return out


def describe(company, job, http):
    """The list API has no description; fetch it for jobs that passed the pre-check."""
    data = http.get_json(API.format(slug=company["slug"]) + f"/{job.source_id}")
    sections = ((data or {}).get("jobAd") or {}).get("sections") or {}
    job.description = " ".join(strip_html((sections.get(k) or {}).get("text"))
                               for k in ("jobDescription", "qualifications", "additionalInformation"))
    return job
