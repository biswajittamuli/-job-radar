"""Kula careers pages (careers.kula.ai/<slug>), used by Indian startups such as Cashfree
and MoEngage. The page is a Next.js app that embeds its job list in the HTML.

  slug: cashfree
"""
import json
import re

from ..models import RawJob
from ..text import strip_html

BASE = "https://careers.kula.ai"
_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
_JOB_START = re.compile(r'\{\s*"id"\s*:\s*\d+\s*,\s*"account_id"\s*:\s*\d+\s*,\s*"title"\s*:')


def _payload(html: str) -> str:
    return "".join(json.loads('"' + c + '"') for c in _CHUNK.findall(html))


def fetch(company, http):
    return parse(http.get_text(f"{BASE}/{company['slug']}"), company)


def parse(html, company):
    blob = _payload(html)
    dec = json.JSONDecoder()
    out, seen = [], set()
    for m in _JOB_START.finditer(blob):
        try:
            j, _ = dec.raw_decode(blob, m.start())
        except ValueError:
            continue
        if j["id"] in seen or j.get("listed") is False or j.get("on_career_page") is False:
            continue
        seen.add(j["id"])
        ats = j.get("ats_job") or {}
        offices = ats.get("offices") or []
        locs = [o.get("location") or ", ".join(x for x in (o.get("city"), o.get("country")) if x) for o in offices]
        out.append(RawJob(
            source_id=str(j["id"]),
            title=(j.get("title") or "").strip(),
            url=f"{BASE}/{company['slug']}/{j['id']}",
            locations=[l for l in locs if l],
            posted_at=(j.get("launch_at") or "")[:10] or None,
            remote=any(o.get("remote") for o in offices) or ats.get("workplace") == "remote" or None,
            team=(ats.get("ats_department") or {}).get("name", ""),
        ))
    return out


def describe(company, job, http):
    """The list has no description text; read it from the job's own page."""
    html = http.get_text(job.url)
    blob = _payload(html)
    # the description is the longest HTML-ish text block in the payload
    texts = re.findall(r"<(?:p|ul|li|div|h\d)[^>]*>.*?</(?:p|ul|li|div|h\d)>", blob, re.S)
    job.description = strip_html(" ".join(texts))[:8000]
    return job
