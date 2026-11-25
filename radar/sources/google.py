"""Google careers. There's no JSON API, but the results page embeds its data in an
AF_initDataCallback({key: 'ds:1', ... data: [...]}) block, which we read.

We ask only for Google's own "early career" level (target_level=EARLY), so every job is
tagged entry level. Google's entry SWE title is "Software Engineer II" (1 year asked).
"""
import json
import re
from datetime import datetime, timezone

from ..models import RawJob
from ..text import strip_html

URL = "https://www.google.com/about/careers/applications/jobs/results"
MAX_PAGES = 10     # 20 jobs per page
_DS1 = re.compile(r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(.*?), sideChannel: \{\}\}\);</script>", re.S)


def fetch(company, http):
    jobs = []
    for page in range(1, MAX_PAGES + 1):
        q = f"?location={company.get('location', 'India')}&target_level={company.get('level', 'EARLY')}&page={page}"
        batch = parse(http.get_text(URL + q), company)
        jobs.extend(batch)
        if len(batch) < 20:
            break
    return jobs


def _text(cell):
    return strip_html(cell[1]) if isinstance(cell, list) and len(cell) > 1 and cell[1] else ""


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def parse(html_or_data, company):
    if isinstance(html_or_data, str):
        m = _DS1.search(html_or_data)
        if not m:
            raise ValueError("Google careers page layout changed: no ds:1 data block")
        data = json.loads(m.group(1))
    else:
        data = html_or_data
    out = []
    for j in (data[0] or []) if data else []:
        jid, title = str(j[0]), (j[1] or "").strip()
        locs = [l[0] for l in (j[9] or []) if l and l[0]]
        ts = (j[12] or [None])[0] if len(j) > 12 else None
        desc = " ".join(t for t in (_text(j[4]), _text(j[19]) if len(j) > 19 else "", _text(j[3]), _text(j[10])) if t)
        out.append(RawJob(
            source_id=jid, title=title,
            url=f"{URL}/{jid}-{_slug(title)}",
            locations=locs,
            posted_at=datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else None,
            description=desc,
            level_hint="entry_level" if company.get("level", "EARLY") == "EARLY" else "",
        ))
    return out
