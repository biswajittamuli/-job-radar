from datetime import datetime

from ..models import RawJob
from ..text import strip_html

API = "https://www.amazon.jobs/en/search.json"
PAGE = 100
MAX_PAGES = 3


def fetch(company, http):
    seen, out = set(), []
    for q in company.get("queries") or ["software development engineer"]:
        for page in range(MAX_PAGES):
            data = http.get_json(API, base_query=q, loc_query=company.get("location", "India"),
                                 country="IND", result_limit=PAGE, offset=page * PAGE,
                                 sort="recent")
            batch = parse(data, company)
            for j in batch:
                if j.source_id not in seen:
                    seen.add(j.source_id)
                    out.append(j)
            if len(batch) < PAGE:
                break
    return out


def _date(s):
    try:
        return datetime.strptime(s.strip(), "%B %d, %Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def parse(data, company):
    out = []
    for j in data.get("jobs", []):
        desc = " ".join([
            strip_html(j.get("description_short")),
            strip_html(j.get("basic_qualifications")),
            strip_html(j.get("preferred_qualifications")),
        ])
        out.append(RawJob(
            source_id=str(j.get("id_icims") or j.get("id")),
            title=(j.get("title") or "").strip(),
            url="https://www.amazon.jobs" + (j.get("job_path") or ""),
            locations=[x for x in (j.get("location"), j.get("normalized_location")) if x],
            posted_at=_date(j.get("posted_date")),
            description=desc,
            team=j.get("job_category", ""),
        ))
    return out
