"""Offline tests: every adapter's parser, the classifier, the store diff, and a full
end-to-end run against fake boards. `pytest -q` from the repo root."""
import json
import shutil
from pathlib import Path

import pytest
import yaml

from radar.classify import classify, min_years
from radar.detect import detect_in
from radar.http import BoardNotFound
from radar.models import RawJob
from radar.runner import run
from radar.sources import amazon, ashby, greenhouse, lever, smartrecruiters, workday

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())


def J(title, loc="Bengaluru, India", desc="", remote=None):
    return RawJob("1", title, "u", [loc] if loc else [], description=desc, remote=remote)


# ── classifier ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title,loc,desc,level", [
    ("Software Engineer I, Backend", "Bengaluru, India", "", "entry"),
    ("SDE-1 (Python / FastAPI)", "Pune", "", "entry"),
    ("Associate Software Engineer", "Hyderabad, India", "", "entry"),
    ("Graduate Engineer Trainee 2026", "Noida", "", "entry"),
    ("Machine Learning Engineer", "Bangalore", "0-1 years of experience in Python", "entry"),
    ("Backend Engineer", "Remote", "", "open"),
    ("Member of Technical Staff - Enterprise Platform", "Bangalore, India (on-site)", "", "open"),
    ("Software Development Engineer", "IN, KA, Bengaluru", "1+ years of non-internship professional software development experience", "entry"),
])
def test_passes(title, loc, desc, level):
    v = classify(J(title, loc, desc), CFG)
    assert v.ok, v.reason
    assert v.level == level


@pytest.mark.parametrize("title,loc,desc,why", [
    ("Senior Backend Engineer", "Bengaluru", "", "senior"),
    ("Software Dev Engineer III, AWS", "IN, KA, Bengaluru", "", "senior"),
    ("Staff Engineer", "Bengaluru", "", "senior"),
    ("Engineering Manager", "Pune", "", "senior"),
    ("Software Engineer II", "Bengaluru", "", "senior"),
    ("Backend Engineer", "San Francisco, CA", "", "location"),
    ("Backend Engineer", "Remote - US", "", "location"),
    ("Backend Engineer", "Bengaluru", "You have 4+ years of professional experience", "years"),
    ("Account Executive", "Mumbai", "", "tech"),
    ("Area Collections Manager", "Chennai", "", "tech"),
    ("Product Designer", "Bengaluru", "", "tech"),
    ("Software Engineering Intern", "Bengaluru", "", "internship"),
])
def test_rejects(title, loc, desc, why):
    v = classify(J(title, loc, desc), CFG)
    assert not v.ok
    assert why in v.reason


def test_min_years():
    assert min_years("Requires 3+ years of experience. Bonus: 5 years experience with Go") == 3
    assert min_years("experience of 2-4 years in backend") == 2
    assert min_years("minimum 1 year") == 1
    assert min_years("We have been around for 20 years. Join us!") is None


def test_skills_tagging():
    v = classify(J("Backend Engineer", desc="Work with FastAPI, Postgres and Redis on Kubernetes and Docker"), CFG)
    assert "backend" in v.skills and "devops_cloud" in v.skills
    v = classify(J("AI Engineer - LLM applications"), CFG)
    assert v.skills[0] == "ai_ml" or "ai_ml" in v.skills


def test_global_remote_but_not_country_locked():
    assert classify(J("Software Engineer", "Remote"), CFG).ok
    assert classify(J("Software Engineer", "Remote (APAC)"), CFG).ok
    assert not classify(J("Software Engineer", "Remote, Canada"), CFG).ok
    assert classify(J("Software Engineer", "Remote - India"), CFG).ok


# ── adapters ────────────────────────────────────────────────────────────────
GH = {"jobs": [{"id": 11, "title": "Software Engineer I", "absolute_url": "https://x/11",
                "location": {"name": "Bengaluru, India"}, "updated_at": "2026-11-20T10:00:00-05:00",
                "content": "&lt;p&gt;0-1 years of experience with Python&lt;/p&gt;",
                "departments": [{"name": "Engineering"}], "offices": []},
               {"id": 12, "title": "Senior Software Engineer", "absolute_url": "https://x/12",
                "location": {"name": "Bengaluru, India"}, "updated_at": "2026-11-20", "content": ""}],
      "meta": {"total": 2}}
LEVER = [{"id": "ab-1", "text": "Backend Developer (Python)", "hostedUrl": "https://jobs.lever.co/cred/ab-1",
          "categories": {"location": "Bengaluru", "team": "Engineering"}, "createdAt": 1764000000000,
          "descriptionPlain": "Build APIs with FastAPI.", "lists": [{"text": "Requirements",
          "content": "<li>1+ years of experience</li>"}], "workplaceType": "onsite"},
         {"id": "ab-2", "text": "Area Collections Manager", "hostedUrl": "u",
          "categories": {"location": "Chennai, Tamil Nadu"}}]
ASHBY = {"jobs": [{"id": "z1", "title": "AI Engineer", "location": "Bengaluru", "jobUrl": "https://jobs.ashbyhq.com/s/z1",
                   "publishedAt": "2026-11-19T00:00:00Z", "descriptionPlain": "LLM, RAG, PyTorch", "isRemote": False,
                   "secondaryLocations": [{"location": "Delhi"}], "isListed": True},
                  {"id": "z2", "title": "Hidden", "location": "Delhi", "isListed": False}]}
SR = {"totalFound": 1, "content": [{"id": "744", "name": "Associate Software Engineer", "releasedDate": "2026-11-18T00:00:00Z",
                                    "location": {"city": "Bangalore", "country": "in", "remote": False}}]}
WD = {"total": 2, "jobPostings": [{"title": "Software Engineer", "externalPath": "/job/Bangalore/SWE_JR1",
                                   "locationsText": "India, Bengaluru", "postedOn": "Posted Today"},
                                  {"title": "Systems Engineer", "externalPath": "/job/x/JR2", "locationsText": "3 Locations"}]}
AMZ = {"hits": 1, "jobs": [{"id_icims": "10581201", "title": "Software Development Engineer I", "location": "IN, KA, Bengaluru",
                            "job_path": "/en/jobs/10581201/sde", "posted_date": "October 16, 2026",
                            "basic_qualifications": "- 1+ years of non-internship professional software development experience"}]}


def test_parsers():
    g = greenhouse.parse(GH, {})
    assert g[0].title == "Software Engineer I" and "0-1 years" in g[0].description and g[0].posted_at == "2026-11-20"
    l = lever.parse(LEVER, {})
    assert l[0].locations == ["Bengaluru"] and "1+ years" in l[0].description and l[0].posted_at.startswith("2025")
    a = ashby.parse(ASHBY, {})
    assert len(a) == 1 and a[0].locations == ["Bengaluru", "Delhi"]
    s = smartrecruiters.parse(SR, {"slug": "Visa"})
    assert s[0].locations == ["Bangalore, in, India"] and s[0].url.endswith("/Visa/744")
    w = workday.parse(WD, {"host": "nvidia.wd5.myworkdayjobs.com", "site": "Ext", "search": "India"})
    assert w[1].locations == ["Multiple locations (India)"] and w[0].url.startswith("https://nvidia.wd5")
    z = amazon.parse(AMZ, {})
    assert z[0].posted_at == "2026-10-16" and z[0].url.startswith("https://www.amazon.jobs/en/jobs/")


def test_detect():
    html = '<a href="https://boards.greenhouse.io/postmanlabs/jobs/1">x</a> <iframe src="https://jobs.lever.co/acme">'
    assert {"ats": "greenhouse", "slug": "postmanlabs"} in detect_in(html)
    assert {"ats": "lever", "slug": "acme"} in detect_in(html)
    wd = detect_in("https://walmart.wd5.myworkdayjobs.com/en-US/WalmartExternal")
    assert wd[0]["tenant"] == "walmart" and wd[0]["site"] == "WalmartExternal"


# ── end to end ──────────────────────────────────────────────────────────────
class FakeHttp:
    def __init__(self, boards):
        self.boards = boards

    def get_json(self, url, **params):
        for key, payload in self.boards.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise BoardNotFound(url)

    def post_json(self, url, body):
        return self.get_json(url)


@pytest.fixture
def repo(tmp_path):
    for f in ("config.yaml",):
        shutil.copy(ROOT / f, tmp_path / f)
    (tmp_path / "companies.yaml").write_text(yaml.safe_dump({"companies": [
        {"name": "Acme", "ats": "greenhouse", "slug": "acme"},
        {"name": "Cred", "ats": "lever", "slug": "cred"},
        {"name": "Sarvam", "ats": "ashby", "slug": "sarvam"},
        {"name": "Ghost", "ats": "greenhouse", "slug": "ghost"},
    ]}))
    return tmp_path


def test_end_to_end(repo):
    boards = {"boards/acme": GH, "postings/cred": LEVER, "job-board/sarvam": ASHBY}
    r1 = run(root=repo, http=FakeHttp(boards), do_notify=False, verbose=False)
    titles = sorted(j.title for j in r1["new"])
    assert titles == ["AI Engineer", "Backend Developer (Python)", "Software Engineer I"]
    assert r1["failing"] == ["Ghost"]

    # second run: nothing new; then a job disappears → marked closed
    r2 = run(root=repo, http=FakeHttp(boards), do_notify=False, verbose=False)
    assert r2["new"] == []
    boards["boards/acme"] = {"jobs": []}
    run(root=repo, http=FakeHttp(boards), do_notify=False, verbose=False)
    jobs = json.loads((repo / "data/jobs.json").read_text())
    closed = [j for j in jobs.values() if j["status"] == "closed"]
    assert [j["title"] for j in closed] == ["Software Engineer I"]

    # a board that errors must NOT close its jobs
    boards["postings/cred"] = RuntimeError("timeout")
    run(root=repo, http=FakeHttp(boards), do_notify=False, verbose=False)
    jobs = json.loads((repo / "data/jobs.json").read_text())
    assert any(j["company"] == "Cred" and j["status"] == "open" for j in jobs.values())

    html = (repo / "docs/index.html").read_text()
    assert "__RADAR_DATA__" not in html and "Backend Developer (Python)" in html
