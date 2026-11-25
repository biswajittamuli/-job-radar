"""Capgemini careers search API (the one capgemini.com's job search calls).
  { name: Capgemini, ats: capgemini, country_code: in-en }"""
from ..models import RawJob
from ..text import strip_html

API = "https://cg-jobstream-api.azurewebsites.net/api/job-search"
PAGE = 50
MAX_PAGES = 30
# Capgemini labels every posting; map its labels onto the classifier's level hints
LEVELS = {"experienced professionals": "mid_senior_level", "executives": "executive",
          "freshers": "entry_level", "graduates": "entry_level", "students": "internship",
          "entry level": "entry_level"}


def fetch(company, http):
    jobs = []
    for page in range(1, MAX_PAGES + 1):
        data = http.get_json(API, country_code=company.get("country_code", "in-en"), page=page, size=PAGE)
        batch = parse(data, company)
        jobs.extend(batch)
        if len(batch) < PAGE:
            break
    return jobs


def parse(data, company):
    out = []
    for j in data.get("data") or []:
        lvl = (j.get("experience_level") or "").strip().lower()
        loc = (j.get("location") or "").strip()
        out.append(RawJob(
            source_id=str(j.get("ref") or j["id"]),
            title=(j.get("title") or "").strip(),
            url=j.get("apply_job_url") or "https://www.capgemini.com/careers/",
            # the in-en feed is India only, but the location field is just the city
            locations=[f"{loc}, India" if loc and "india" not in loc.lower() else (loc or "India")],
            posted_at=(j.get("updated_at") or j.get("indexed_at") or "")[:10] or None,
            description=strip_html(j.get("description")) or (j.get("description_stripped") or ""),
            level_hint=LEVELS.get(lvl, ""),
            team=j.get("professional_communities") or "",
        ))
    return out
