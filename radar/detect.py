"""Find which ATS a company's careers page uses, and print the companies.yaml block."""
from __future__ import annotations

import re

PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)")),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)")),
    ("lever",      re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)")),
    ("ashby",      re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)")),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("workday",    re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
]
SKIP = {"embed", "api", "v1", "jobs", "js", "css", "static"}


def detect_in(text: str) -> list[dict]:
    found, seen = [], set()
    for ats, rx in PATTERNS:
        for m in rx.finditer(text):
            if ats == "workday":
                tenant, wd, site = m.groups()
                key = (ats, tenant, site)
                block = {"ats": ats, "host": f"{tenant}.{wd}.myworkdayjobs.com",
                         "tenant": tenant, "site": site, "search": "India"}
            else:
                slug = m.group(1)
                if slug.lower() in SKIP:
                    continue
                key = (ats, slug.lower())
                block = {"ats": ats, "slug": slug}
            if key not in seen:
                seen.add(key)
                found.append(block)
    return found


def detect(url: str, http) -> list[dict]:
    hits = detect_in(url)          # the URL itself may already be an ATS link
    if hits:
        return hits
    return detect_in(http.get_text(url))
