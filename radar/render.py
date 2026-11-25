"""Build docs/index.html: one self-contained page with the data embedded,
so it works on GitHub Pages and also when opened straight from disk."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .models import newest_first

TEMPLATE = Path(__file__).with_name("dashboard.html")


def careers_link(c: dict) -> str:
    """A human careers page for a companies.yaml entry."""
    a, slug, host = c.get("ats"), c.get("slug", ""), c.get("host", "")
    return {
        "greenhouse": f"https://job-boards.greenhouse.io/{slug}",
        "lever": f"https://jobs.lever.co/{slug}",
        "ashby": f"https://jobs.ashbyhq.com/{slug}",
        "smartrecruiters": f"https://jobs.smartrecruiters.com/{slug}",
        "keka": f"https://{host}/careers/",
        "kula": f"https://careers.kula.ai/{slug}",
        "freshteam": f"https://{slug}.freshteam.com/jobs",
        "workday": f"https://{host}/en-US/{c.get('site', '')}",
        "oracle_hcm": f"https://{host}/hcmUI/CandidateExperience/en/sites/{c.get('site', '')}",
        "eightfold": f"https://{host}/careers",
        "successfactors": f"https://{host}/",
    }.get(a, "")


def startup_directory(root: Path, store) -> list[dict]:
    """Every Indian startup in startups.yaml: tracked ones with their fresher-hiring record,
    and manual ones with a careers link to check by hand."""
    f = Path(root) / "startups.yaml"
    if not f.exists():
        return []
    cfg = yaml.safe_load(f.read_text()) or {}
    comps = {c["name"]: c for c in (yaml.safe_load((Path(root) / "companies.yaml").read_text()) or {}).get("companies", [])}
    open_jobs = {}
    for j in store.jobs.values():
        if j["status"] == "open":
            open_jobs[j["company"]] = open_jobs.get(j["company"], 0) + 1
    out = []
    for name in cfg.get("tracked") or []:
        c = comps.get(name, {})
        rec = store.companies.get(name, {})
        seen = sorted((rec.get("seen") or {}).values(), key=lambda e: e.get("last_seen", ""), reverse=True)
        out.append({"name": name, "tracked": True, "system": c.get("ats", ""), "careers": careers_link(c),
                    "matches": open_jobs.get(name, 0), "open_entry": rec.get("open_entry", 0),
                    "open_intern": rec.get("open_intern", 0),
                    "fresher_seen": sum(1 for e in seen if e.get("kind") == "entry"),
                    "intern_seen": sum(1 for e in seen if e.get("kind") == "intern"),
                    "last_fresher_seen": rec.get("last_fresher_seen"),
                    "examples": [{"title": e["title"], "url": e.get("url", ""), "kind": e.get("kind"),
                                  "last_seen": e.get("last_seen")} for e in seen[:4]]})
    for m in cfg.get("manual") or []:
        out.append({"name": m["name"], "tracked": False, "system": m.get("system", ""), "careers": m.get("careers", "")})
    return out


def build(root: Path, store) -> Path:
    jobs = sorted(store.jobs.values(),
                  key=lambda j: (j["status"] != "open", *newest_first(j.get("posted_at"), j["score"])))
    payload = {
        "generated_at": store.runs[-1]["at"] if store.runs else None,
        "jobs": jobs,
        "health": store.health,
        "runs": store.runs[-30:],
        "startups": startup_directory(root, store),
    }
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out = Path(root) / "docs" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.read_text().replace("__RADAR_DATA__", blob))
    (out.parent / ".nojekyll").touch()
    return out
