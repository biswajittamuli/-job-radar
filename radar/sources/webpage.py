"""Read a careers page the way a person does: open it in a headless browser, wait for it to
render, and pick out the job links. For companies whose careers site has no job feed
(their own page, Darwinbox, Zoho Recruit, Phenom, iCIMS, Avature, Taleo, TurboHire…).

  - name: Example
    ats: webpage
    url: https://example.com/careers        # the page that lists the jobs
    location: India                         # assumed when a listing shows no city

Polite by design: it checks the site's robots.txt and skips pages that disallow bots, reads
one page at a time, never logs in, and opens a job's own page (for the description) only
when its title already looks like a fresher software role.
"""
from __future__ import annotations

import re
import threading
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from ..http import SourceDisabled
from ..models import RawJob
from ..text import strip_html

BROWSER = True             # the runner reads these one at a time, after the API boards
MAX_DESCRIBE = 15          # job pages opened per company per run (then cached)
AGENT = "JobRadar"
PAGE_TIMEOUT_MS = 30000

_lock = threading.Lock()
_pw = _browser = None

# words that make link text look like a job title
ROLE = re.compile(r"engineer|developer|\bsde\b|sdet|intern|analyst|scientist|architect|programmer|designer|"
                  r"manager|lead\b|associate|executive|specialist|consultant|officer|representative|trainee|"
                  r"graduate|fresher|\bmts\b|technical staff|devops|\bsre\b|full[- ]?stack|back[- ]?end|front[- ]?end", re.I)
# navigation / generic link texts that are never jobs
NAV = re.compile(r"^(careers?|jobs?|all jobs|apply( now| here)?|view( all)?( jobs| openings| roles| details| more)?|"
                 r"open (positions|roles|jobs)|current openings|see (all|more|open roles)|learn more|read more|"
                 r"explore( jobs| roles| opportunities)?|join us|life at .*|our (team|culture|values)|benefits|"
                 r"home|about( us)?|blog|contact( us)?|log ?in|sign (in|up)|privacy.*|terms.*|cookie.*|faq.*)$", re.I)
# a job posting's own address: /jobs/123, /careers/backend-engineer-42, ?jobId=…, or a careers-system host
JOB_HREF = re.compile(
    r"/(jobs?|careers?|positions?|openings?|vacanc\w*|requisitions?|opportunit\w*|roles?|job-details?|jobdetails)/[^/?#]{3,}|"
    r"[?&](job|jobid|job_id|gh_jid|jid|req|reqid|requisitionid|position|posting)=|/j/[a-z0-9]|/apply\b|jobdescription|"
    r"darwinbox|keka\.com|zohorecruit|turbohire|freshteam|lever\.co|ashbyhq|greenhouse\.io|smartrecruiters|workable|"
    r"icims|taleo|avature|phenompeople|eightfold|myworkdayjobs|successfactors|oraclecloud|recruitee|kula\.ai", re.I)
# category / landing pages on job boards: "Backend Developer Jobs", "Remote Android Developer Jobs"
CATEGORY = re.compile(r"\bjobs?$|\bjobs in\b|\bvacancies$|\bopenings$|^(all|remote|latest|top)\b.*\bjobs?\b", re.I)
SOCIAL = re.compile(r"linkedin\.com|twitter\.com|x\.com/|facebook\.com|instagram\.com|youtube\.com|glassdoor|"
                    r"^mailto:|^tel:|^javascript:", re.I)
OPEN_JOBS = ['a:has-text("Open positions")', 'a:has-text("View jobs")', 'a:has-text("View openings")',
             'a:has-text("Open roles")', 'a:has-text("See open")', 'a:has-text("Explore jobs")',
             'a:has-text("Current openings")', 'a:has-text("Job openings")', 'a:has-text("View all jobs")',
             'button:has-text("Open positions")', 'button:has-text("View jobs")', 'a:has-text("Search jobs")']

# runs inside every frame: candidate links with the text around them
_EXTRACT_JS = r"""
() => Array.from(document.querySelectorAll('a[href]')).map(a => {
  let box = a, ctx = '';
  for (let i = 0; i < 3 && box; i++) { box = box.parentElement; if (box && box.innerText && box.innerText.length < 400) ctx = box.innerText; }
  return { text: (a.innerText || a.textContent || '').trim(), href: a.href, ctx: ctx };
})
"""


def _browser_page():
    global _pw, _browser
    if _browser is None:
        from playwright.sync_api import sync_playwright
        _pw = sync_playwright().start()
        try:
            _browser = _pw.chromium.launch()
        except Exception:  # noqa: BLE001 — a pre-installed Chromium in some containers
            _browser = _pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = _browser.new_context(user_agent=f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                         f"Chrome/131.0 Safari/537.36 {AGENT}/1.0")
    return ctx, ctx.new_page()


def close():
    """Shut the shared browser down (the runner calls this after the last page)."""
    global _pw, _browser
    with _lock:
        if _browser is not None:
            try:
                _browser.close()
                _pw.stop()
            finally:
                _pw = _browser = None


def allowed(url: str, http) -> bool:
    """Respect robots.txt. An unreadable robots.txt counts as allowed (the web's convention)."""
    p = urlparse(url)
    rp = RobotFileParser()
    try:
        rp.parse(http.get_text(f"{p.scheme}://{p.netloc}/robots.txt").splitlines())
    except Exception:  # noqa: BLE001
        return True
    return rp.can_fetch(AGENT, url)


def _render_links(url: str) -> list[dict]:
    with _lock:
        ctx, page = _browser_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:  # noqa: BLE001 — some pages never go quiet
                pass
            links = _collect(page)
            if sum(1 for l in links if ROLE.search(l["text"])) < 2:
                # the list is often one click away ("Open positions")
                for sel in OPEN_JOBS:
                    el = page.query_selector(sel)
                    if el:
                        try:
                            el.click(timeout=5000)
                            page.wait_for_load_state("domcontentloaded", timeout=15000)
                            page.wait_for_timeout(4000)
                        except Exception:  # noqa: BLE001
                            pass
                        links += _collect(page)
                        break
            return links
        finally:
            ctx.close()


def _collect(page) -> list[dict]:
    for _ in range(3):              # lazy-loaded lists
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(700)
    out = []
    for frame in page.frames:
        try:
            out += frame.evaluate(_EXTRACT_JS)
        except Exception:  # noqa: BLE001 — cross-origin or detached frames
            continue
    return out


def parse(links: list[dict], company: dict, cities: list[str] | None = None) -> list[RawJob]:
    """Turn rendered links into jobs. Pure, so it is unit-tested without a browser."""
    cities = [c.lower() for c in (cities or [])]
    base = company.get("url", "")
    out, seen = [], set()
    for l in links:
        text = " ".join((l.get("text") or "").split())
        title = re.split(r"\s{2,}|\n| \| ", (l.get("text") or "").strip())[0].strip() if l.get("text") else ""
        title = " ".join(title.split())[:120]
        href = urljoin(base, l.get("href") or "")
        if not title or len(title) < 4 or len(title.split()) > 15 or NAV.match(title) or SOCIAL.search(href):
            continue
        if not ROLE.search(title) or CATEGORY.search(title):
            continue
        if not JOB_HREF.search(urlparse(href).path + "?" + urlparse(href).query + " " + urlparse(href).netloc):
            continue                      # menu, product and blog links aren't job postings
        key = (title.lower(), href.split("#")[0])
        if key in seen:
            continue
        seen.add(key)
        ctx = (l.get("ctx") or text).lower()
        loc = next((c.title() for c in cities if re.search(rf"\b{re.escape(c)}\b", ctx)), None)
        remote = bool(re.search(r"\bremote\b", ctx))
        out.append(RawJob(
            source_id=href if href and href != base else title,
            title=title,
            url=href or base,
            locations=[f"{loc}, India"] if loc else (["Remote"] if remote else ([company["location"]] if company.get("location") else [])),
            remote=remote or None,
            description="",
        ))
    return out


def fetch(company, http):
    url = company["url"]
    if not allowed(url, http):
        raise SourceDisabled("its robots.txt asks bots not to read this page")
    cities = company.get("_cities") or ["bengaluru", "bangalore", "hyderabad", "chennai", "pune", "mumbai", "gurugram",
                                        "gurgaon", "noida", "delhi", "kolkata", "ahmedabad", "jaipur", "kochi", "indore"]
    return parse(_render_links(url), company, cities)


def describe(company, job, http):
    """Read the job's own page: plain HTTP first, the browser if that page needs JavaScript."""
    if job.url == company.get("url") or not allowed(job.url, http):
        return job
    text = ""
    try:
        text = strip_html(http.get_text(job.url))
    except Exception:  # noqa: BLE001
        pass
    if len(text) < 600:
        with _lock:
            ctx, page = _browser_page()
            try:
                page.goto(job.url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                page.wait_for_timeout(3000)
                text = " ".join((page.inner_text("body") or "").split())
            except Exception:  # noqa: BLE001
                pass
            finally:
                ctx.close()
    job.description = text[:8000]
    return job
