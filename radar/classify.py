"""Decide whether a RawJob is a fit: tech role, India/remote, fresher-friendly, which skills.

Everything here is deterministic regex logic so results are explainable:
`python -m radar explain "<title>" --desc "<text>"` prints why a job passed or failed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .models import RawJob

# ── role type ────────────────────────────────────────────────────────────────
TECH = re.compile(
    r"engineer|engineering|developer|\bsde\b|\bsdet\b|software|programmer|technical staff|"
    r"data scien|data analyst|machine learning|\bml\b|\bai\b|\bllm\b|devops|\bsre\b|"
    r"site reliability|cloud|security analyst|security engineer|\bqa\b|"
    r"quality assurance|\btest(ing)?\b|applied scientist|research scientist", re.I)

NON_TECH = re.compile(
    r"\bsales\b|account executive|account manager|marketing|recruit|talent|\bhr\b|hrbp|"
    r"people partner|legal|counsel|finance|accountant|accounting|collections?|procurement|"
    r"purchase|content|copywriter|illustrator|customer success|business development|"
    r"\bbdr\b|\bsdr\b|partner manager|payroll|audit|compliance|office admin|receptionist|"
    r"product designer|graphic designer|ux designer|ad sales|category lead|growth marketer",
    re.I)

# ── seniority ────────────────────────────────────────────────────────────────
SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|leader|manager|director|head|vp|"
    r"vice president|architect|distinguished|fellow|chief|expert)\b|"
    r"\b(engineer|developer|sde|scientist|analyst)\s*[-,]?\s*(ii|iii|iv|v|2|3|4|5)\b|"
    r"\bsde[- ]?(ii|iii|2|3)\b|\bl[5-9]\b|\bmts[- ]?(2|3|4)\b", re.I)

ENTRY = re.compile(
    r"new[- ]?grad|graduate|fresher|freshers|entry[- ]level|early[- ]career|campus|"
    r"university|\bjunior\b|\bjr\.?\b|trainee|apprentice|\bassociate\b|"
    r"\b(engineer|developer|sde|scientist|analyst)\s*[-,]?\s*(i|1)\b|\bsde[- ]?(i|1)\b|"
    r"\b202[5-7]\b|\bmts[- ]?1\b|0\s*[-–to]+\s*[12]\s*(years|yrs)", re.I)

INTERN = re.compile(r"\bintern(ship)?s?\b|co-?op\b", re.I)

# "3+ years of experience", "2-4 years of relevant experience", "minimum 5 years"
YEARS = [
    re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*(?:years?|yrs?)\b"
               r"[^.;\n]{0,80}?experience", re.I),
    re.compile(r"experience\s*(?:of|:)?\s*(?:at\s+least\s+|minimum\s+(?:of\s+)?)?"
               r"(\d{1,2})\s*(?:\+|-|–|to)?\s*\d{0,2}\s*(?:years?|yrs?)", re.I),
    re.compile(r"(?:minimum|at least)\s*(?:of\s*)?(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I),
]

# ── location ─────────────────────────────────────────────────────────────────
REMOTE = re.compile(r"\bremote\b|anywhere|worldwide|work from home|\bwfh\b", re.I)
REMOTE_OK_WORDS = {"remote", "anywhere", "worldwide", "global", "apac", "asia", "work", "from",
                   "home", "wfh", "fully", "first", "-", "–", "/", "(", ")", ""}


@dataclass
class Verdict:
    ok: bool
    reason: str
    level: str = ""
    skills: list[str] = field(default_factory=list)
    years: int | None = None
    location: str = ""
    remote: bool = False
    score: int = 0


def min_years(text: str) -> int | None:
    found = []
    for rx in YEARS:
        for m in rx.finditer(text):
            n = int(m.group(1))
            if n <= 15:
                found.append(n)
    return min(found) if found else None


def _is_global_remote(loc: str) -> bool:
    tokens = re.split(r"[\s,;|]+", loc.lower())
    return all(t.strip("()-–/") in REMOTE_OK_WORDS for t in tokens)


def match_location(job: RawJob, cfg: dict) -> tuple[str, bool]:
    """Return (display_location, is_remote) or ("", False) if no match."""
    inc = [k.lower() for k in cfg["location"]["include"]]
    hits, remote_hit = [], False
    for loc in job.locations:
        l = loc.lower()
        if any(k in l for k in inc):
            hits.append(loc)
        elif cfg["location"].get("allow_global_remote") and REMOTE.search(l) and _is_global_remote(l):
            hits.append(loc)
            remote_hit = True
    if not hits and job.remote and not job.locations and cfg["location"].get("allow_global_remote"):
        return "Remote", True
    if not hits:
        return "", False
    is_remote = remote_hit or bool(job.remote) or any(REMOTE.search(h) for h in hits)
    extra = len(job.locations) - 1
    label = hits[0] + (f" +{extra}" if extra > 0 else "")
    return label, is_remote


def tag_skills(title: str, desc: str, cfg: dict) -> list[str]:
    t = f" {title.lower()} "
    d = f" {desc.lower()[:6000]} "
    tags = []
    for bucket, kws in cfg["skills"].items():
        kws = [k.lower() for k in kws]
        if any(k in t for k in kws):
            tags.append(bucket)
        elif sum(1 for k in kws if k in d) >= 2:
            tags.append(bucket)
    # "sde" is a catch-all; drop it when something more specific matched
    if len(tags) > 1 and "sde" in tags:
        tags.remove("sde")
    return tags or ["sde"]


def classify(job: RawJob, cfg: dict, today: date | None = None) -> Verdict:
    title = job.title
    if not TECH.search(title) or NON_TECH.search(title):
        return Verdict(False, "not a tech role")

    # "Member of Technical Staff" is an IC title at AI labs, not "staff" seniority
    title_for_level = re.sub(r"member of technical staff", "mts", title, flags=re.I)
    if SENIOR.search(title_for_level):
        return Verdict(False, f"senior title ({SENIOR.search(title_for_level).group(0)})")

    loc, remote = match_location(job, cfg)
    if not loc:
        return Verdict(False, f"location not in scope ({'; '.join(job.locations) or 'none'})")

    lvl_cfg = cfg["level"]
    is_intern = bool(INTERN.search(title))
    if is_intern and not lvl_cfg.get("include_internships"):
        return Verdict(False, "internship (disabled in config)")

    years = min_years(job.description) if job.description else None
    if years is not None and years > lvl_cfg["max_years"]:
        return Verdict(False, f"asks {years}+ years experience")

    if is_intern:
        level = "intern"
    elif ENTRY.search(title_for_level) or (years is not None and years <= 1):
        level = "entry"
    elif lvl_cfg.get("mode", "open") == "open":
        level = "open"
    else:
        return Verdict(False, "no fresher signal (mode=entry)")

    skills = tag_skills(title, job.description, cfg)
    score = _score(level, skills, title, years, remote, job.posted_at, cfg, today or date.today())
    return Verdict(True, "match", level, skills, years, loc, remote, score)


def _score(level, skills, title, years, remote, posted_at, cfg, today) -> int:
    s = {"entry": 50, "open": 20, "intern": 10}[level]
    pri = cfg.get("priority", [])
    tl = title.lower()
    for i, b in enumerate(pri):
        if b in skills:
            in_title = any(k.lower() in f" {tl} " for k in cfg["skills"].get(b, []))
            s += (20 if in_title else 8) - i * 2
    if years == 0:
        s += 10
    if remote:
        s += 3
    if posted_at:
        try:
            age = (today - date.fromisoformat(posted_at[:10])).days
            s += 12 if age <= 3 else 6 if age <= 7 else 0 if age <= 30 else -10
        except ValueError:
            pass
    return s
