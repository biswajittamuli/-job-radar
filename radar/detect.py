"""Find which careers system a company's careers page uses, and build its companies.yaml entry.

`python -m radar detect <url>` prints candidate entries.
`python -m radar add <url> --name "Company"` also test-fetches them and appends the first
one that returns jobs to companies.yaml.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)")),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)")),
    ("lever",      re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)")),
    ("ashby",      re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)")),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("workday",    re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
    ("keka",       re.compile(r"([a-z0-9-]+)\.keka\.com")),
    ("kula",       re.compile(r"careers\.kula\.ai/([A-Za-z0-9_-]+)")),
    ("eightfold",  re.compile(r"([a-z0-9-]+)\.eightfold\.ai")),
    ("oracle_hcm", re.compile(r"([a-z0-9]+\.fa\.[a-z0-9]+\.oraclecloud\.com)")),
    ("freshteam",  re.compile(r"([a-z0-9-]+)\.freshteam\.com")),
]
# careers systems we recognise but can't read: bot checks, logins, no public feed, or not built yet
UNSUPPORTED = [("Darwinbox", r"darwinbox\.in"), ("TurboHire", r"turbohire\.co"), ("Zoho Recruit", r"zohorecruit"),
               ("iCIMS", r"\.icims\.com"), ("Phenom", r"phenompeople"), ("Taleo", r"taleo\.net"), ("Avature", r"avature\.net"),
               ("Recruitee", r"\.recruitee\.com"), ("Breezy HR", r"\.breezy\.hr"), ("Workable", r"apply\.workable\.com")]
SKIP = {"embed", "api", "v1", "jobs", "js", "css", "static", "www", "app", "assets", "cdn", "careers", "help", "support"}
_ORACLE_SITE = re.compile(r"(?:/sites/|siteNumber[\"'=:\s]+)(CX_?[A-Za-z0-9_]*)")


def detect_in(text: str, page_url: str = "") -> list[dict]:
    found, seen = [], set()
    for ats, rx in PATTERNS:
        for m in rx.finditer(text):
            if ats == "workday":
                tenant, wd, site = m.groups()
                key = (ats, tenant, site)
                block = {"ats": ats, "host": f"{tenant}.{wd}.myworkdayjobs.com",
                         "tenant": tenant, "site": site, "search": "India"}
            elif ats in ("keka", "freshteam"):
                sub = m.group(1)
                if sub in SKIP:
                    continue
                key = (ats, sub)
                block = {"ats": ats, "host": m.group(0)} if ats == "keka" else {"ats": ats, "slug": sub}
            elif ats == "eightfold":
                sub = m.group(1)
                if sub in SKIP:
                    continue
                key = (ats, sub)
                block = {"ats": ats, "host": f"{sub}.eightfold.ai", "domain": f"{sub}.com"}
            elif ats == "oracle_hcm":
                site = _ORACLE_SITE.search(text)
                key = (ats, m.group(1))
                block = {"ats": ats, "host": m.group(1), "site": site.group(1) if site else "CX_1"}
            else:
                slug = m.group(1)
                if slug.lower() in SKIP:
                    continue
                key = (ats, slug.lower())
                block = {"ats": ats, "slug": slug}
            if key not in seen:
                seen.add(key)
                found.append(block)
    # SAP SuccessFactors career sites serve their own search API on the same host
    if page_url and re.search(r"successfactors|sapsf\.|rmk-jobs-search|jobs\.sap\.com", text, re.I):
        found.append({"ats": "successfactors", "host": urlparse(page_url).netloc, "location": "India",
                      "queries": ["fresher", "graduate", "software engineer", "developer"]})
    return found


def detect(url: str, http) -> list[dict]:
    hits = detect_in(url)          # the URL itself may already be a careers-system link
    if hits:
        return hits
    return detect_in(http.get_text(url), url)


def oracle_india_location(block: dict, http) -> int | None:
    """Oracle sites filter by a numeric location id; look up India's."""
    data = http.get_json(f"https://{block['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                         onlyData="true", finder=f"findReqs;siteNumber={block['site']},facetsList=LOCATIONS,limit=1")
    for loc in (data.get("items") or [{}])[0].get("locationsFacet") or []:
        if loc.get("Name") == "India":
            return loc["Id"]
    return None


def add_company(url: str, name: str, companies_file, http, today: str) -> tuple[dict | None, list[str]]:
    """Detect the careers system behind `url`, test-fetch each candidate, and append the first
    one that returns jobs to companies.yaml. Returns (entry or None, log lines)."""
    import yaml
    from .sources import ADAPTERS

    log = []
    existing = (yaml.safe_load(open(companies_file)) or {}).get("companies") or []
    if any(c["name"].lower() == name.lower() for c in existing):
        return None, [f"{name} is already in {companies_file}"]
    try:
        candidates = detect(url, http)
    except Exception as e:  # noqa: BLE001
        return None, [f"could not load {url}: {e}"]
    if not candidates:
        # no job feed found: try reading the page itself with the headless browser
        entry = {"name": name, "ats": "webpage", "url": url, "location": "India"}
        try:
            jobs = ADAPTERS["webpage"].fetch(entry, http)
        except Exception as e:  # noqa: BLE001
            jobs, why = [], str(e)
        else:
            why = "the page lists no job links the reader can recognise"
        finally:
            getattr(ADAPTERS["webpage"], "close", lambda: None)()
        if jobs:
            from datetime import date as _date
            entry["verified"] = _date.fromisoformat(today)
            line = "  - " + yaml.safe_dump(entry, default_flow_style=True, sort_keys=False, width=1000).strip()
            with open(companies_file, "a") as f:
                f.write(("" if open(companies_file).read().endswith("\n") else "\n") + line + "\n")
            return entry, [f"  no job feed, but the careers page itself lists {len(jobs)} jobs "
                           f"(e.g. {jobs[0].title!r}); it will be read with a headless browser. Added:\n{line}"]
        try:
            page = http.get_text(url)
        except Exception:  # noqa: BLE001
            page = ""
        known = [n for n, rx in UNSUPPORTED if re.search(rx, page, re.I)]
        if known:
            return None, [f"that page uses {known[0]}, which Job Radar can't read ({why})"]
        return None, [f"couldn't find jobs on that page: {why}"]
    for block in candidates:
        entry = {"name": name, **block}
        try:
            if block["ats"] == "oracle_hcm":
                entry["location_id"] = oracle_india_location(block, http)
                if not entry["location_id"]:
                    log.append(f"  oracle_hcm {block['host']}: no India location on this site")
                    continue
            same = [c for c in existing if c.get("ats") == entry["ats"] and
                    (c.get("slug") or c.get("host")) == (entry.get("slug") or entry.get("host"))]
            if same:
                return None, [f"that board is already tracked as {same[0]['name']}"]
            jobs = ADAPTERS[entry["ats"]].fetch(entry, http)
        except Exception as e:  # noqa: BLE001
            log.append(f"  {block['ats']}: failed ({str(e)[:80]})")
            continue
        if not jobs:
            log.append(f"  {block['ats']}: board found but it lists no jobs")
            continue
        from datetime import date as _date
        entry["verified"] = _date.fromisoformat(today)
        line = "  - " + yaml.safe_dump(entry, default_flow_style=True, sort_keys=False, width=1000).strip()
        with open(companies_file, "a") as f:
            f.write(("" if open(companies_file).read().endswith("\n") else "\n") + line + "\n")
        log.append(f"  {entry['ats']}: {len(jobs)} jobs. Added:\n{line}")
        return entry, log
    return None, log
