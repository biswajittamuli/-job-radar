"""SAP SuccessFactors career sites (the "/services/recruiting/v1/jobs" search used by
careers.wipro.com, careers.hcltech.com and others).

These sites hold thousands of postings, so we search a few keywords (newest first,
a few pages each) instead of reading everything:
  { name: Wipro, ats: successfactors, host: careers.wipro.com, location: India,
    queries: [fresher, graduate, software engineer, developer] }
"""
from datetime import datetime

from ..models import RawJob
from ..text import strip_html

PAGES_PER_QUERY = 3     # 10 results per page


def _search(company, http, keywords, page):
    body = {"locale": "en_US", "pageNumber": page, "sortBy": "date", "keywords": keywords,
            "location": company.get("location", ""), "facetFilters": {}, "brand": "", "skills": [],
            "categoryId": 0, "alertId": "", "rcmCandidateId": ""}
    return http.post_json(f"https://{company['host']}/services/recruiting/v1/jobs", body)


def fetch(company, http):
    seen, out = set(), []
    for q in company.get("queries") or ["software engineer"]:
        for page in range(company.get("pages_per_query", PAGES_PER_QUERY)):
            batch = parse(_search(company, http, q, page), company)
            for j in batch:
                if j.source_id not in seen:
                    seen.add(j.source_id)
                    out.append(j)
            if len(batch) < 10:
                break
    return out


def _date(s):
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            continue
    return None


def parse(data, company):
    out = []
    for item in data.get("jobSearchResult") or []:
        r = item.get("response") or {}
        locs = [strip_html(l).rstrip(", ") for l in (r.get("jobLocationShort") or []) if strip_html(l).strip(", ")]
        country = (r.get("jobLocationCountry") or [""])[0]
        if country and not any(country.lower() in l.lower() for l in locs):
            locs = [f"{l}, {country}" for l in locs] or [country]
        out.append(RawJob(
            source_id=str(r["id"]),
            title=strip_html(r.get("unifiedStandardTitle") or ""),
            url=f"https://{company['host']}/job/{r.get('urlTitle', 'job')}/{r['id']}-{r.get('supportedLocales', ['en_US'])[0]}/",
            locations=locs,
            posted_at=_date(r.get("unifiedStandardStart")),
        ))
    return out


def describe(company, job, http):
    """The search result has no description; read the job page's text."""
    job.description = strip_html(http.get_text(job.url))[:8000]
    return job
