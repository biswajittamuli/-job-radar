"""Offline tests: every adapter's parser, the classifier, the store diff, and a full
end-to-end run against fake boards. `pytest -q` from the repo root."""
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from radar import notify
from radar.classify import classify, min_years
from radar.detect import detect_in
from radar.http import BoardNotFound
from radar.models import RawJob
from radar.runner import run
from radar.sources import amazon, ashby, greenhouse, lever, smartrecruiters, workday

ROOT = Path(__file__).resolve().parent.parent
TODAY = date.today()


def ago(days):
    return (TODAY - timedelta(days=days)).isoformat()
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())          # strict fresher (the real config)
# The same config in "open" mode, for tests about location/skills/title rules rather than level
OPEN = {**CFG, "level": {**CFG["level"], "mode": "open", "max_years": 2}}


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
    v = classify(J(title, loc, desc), OPEN)
    assert v.ok, v.reason
    assert v.level == level


@pytest.mark.parametrize("title,loc,desc,why", [
    ("Senior Backend Engineer", "Bengaluru", "", "senior"),
    ("Backend Engineer Seniore", "Bengaluru", "", "senior"),
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
    v = classify(J(title, loc, desc), OPEN)
    assert not v.ok
    assert why in v.reason


def test_min_years():
    assert min_years("Requires 3+ years of experience. Bonus: 5 years experience with Go") == 3
    assert min_years("experience of 2-4 years in backend") == 2
    assert min_years("minimum 1 year") == 1
    assert min_years("We have been around for 20 years. Join us!") is None
    assert min_years("3+ yrs of programming exp in at least one language") == 3
    assert min_years("PayPal has been revolutionizing commerce for more than 25 years. Creating experiences") is None


def test_skills_tagging():
    v = classify(J("Backend Engineer", desc="Work with FastAPI, Postgres and Redis on Kubernetes and Docker"), OPEN)
    assert "backend" in v.skills and "devops_cloud" in v.skills
    v = classify(J("AI Engineer - LLM applications"), OPEN)
    assert v.skills[0] == "ai_ml" or "ai_ml" in v.skills


def test_global_remote_but_not_country_locked():
    assert classify(J("Software Engineer", "Remote"), OPEN).ok
    assert classify(J("Software Engineer", "Remote (APAC)"), OPEN).ok
    assert not classify(J("Software Engineer", "Remote, Canada"), OPEN).ok
    assert classify(J("Software Engineer", "Remote - India"), OPEN).ok


# ── adapters ────────────────────────────────────────────────────────────────
GH = {"jobs": [{"id": 11, "title": "Software Engineer I", "absolute_url": "https://x/11",
                "location": {"name": "Bengaluru, India"}, "updated_at": ago(5) + "T10:00:00-05:00",
                "content": "&lt;p&gt;0-1 years of experience with Python&lt;/p&gt;",
                "departments": [{"name": "Engineering"}], "offices": []},
               {"id": 12, "title": "Senior Software Engineer", "absolute_url": "https://x/12",
                "location": {"name": "Bengaluru, India"}, "updated_at": ago(5), "content": ""}],
      "meta": {"total": 2}}
LEVER = [{"id": "ab-1", "text": "Backend Developer (Python)", "hostedUrl": "https://jobs.lever.co/cred/ab-1",
          "categories": {"location": "Bengaluru", "team": "Engineering"}, "createdAt": int(datetime.combine(TODAY - timedelta(days=3), datetime.min.time(), timezone.utc).timestamp() * 1000),
          "descriptionPlain": "Build APIs with FastAPI.", "lists": [{"text": "Requirements",
          "content": "<li>1+ years of experience</li>"}], "workplaceType": "onsite"},
         {"id": "ab-2", "text": "Area Collections Manager", "hostedUrl": "u",
          "categories": {"location": "Chennai, Tamil Nadu"}}]
ASHBY = {"jobs": [{"id": "z1", "title": "AI Engineer", "location": "Bengaluru", "jobUrl": "https://jobs.ashbyhq.com/s/z1",
                   "publishedAt": ago(6) + "T00:00:00Z", "descriptionPlain": "LLM, RAG, PyTorch", "isRemote": False,
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
    assert g[0].title == "Software Engineer I" and "0-1 years" in g[0].description and g[0].posted_at == ago(5)
    l = lever.parse(LEVER, {})
    assert l[0].locations == ["Bengaluru"] and "1+ years" in l[0].description and l[0].posted_at == ago(3)
    a = ashby.parse(ASHBY, {})
    assert len(a) == 1 and a[0].locations == ["Bengaluru", "Delhi"]
    s = smartrecruiters.parse(SR, {"slug": "Visa"})
    assert s[0].locations == ["Bangalore, in, India"] and s[0].url.endswith("/Visa/744")
    w = workday.parse(WD, {"host": "nvidia.wd5.myworkdayjobs.com", "site": "Ext", "search": "India"})
    assert w[1].locations == ["Multiple locations (India)"] and w[0].url.startswith("https://nvidia.wd5")
    assert w[0].posted_at == TODAY.isoformat() and w[1].posted_at is None
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

    def get_json(self, url, headers=None, **params):
        self.calls = getattr(self, "calls", []) + [url]
        for key, payload in self.boards.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise BoardNotFound(url)

    def post_json(self, url, body, headers=None):
        return self.get_json(url)

    def get_text(self, url):
        return ""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(OPEN))
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


# ── senior titles ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", [
    "SMTS, Software Engineering", "LMTS - Software Engineer", "PMTS Software Engineer",
    "Software Engineering SMTS", "Senior Member of Technical Staff",
])
def test_salesforce_mts_levels_are_senior(title):
    v = classify(J(title), OPEN)
    assert not v.ok and "senior" in v.reason


def test_plain_mts_still_passes():
    assert classify(J("MTS, Software Engineering"), OPEN).ok
    assert classify(J("Member of Technical Staff"), OPEN).ok


# ── freshness ───────────────────────────────────────────────────────────────
def Jd(posted_at, title="Software Engineer I"):
    return RawJob("1", title, "u", ["Bengaluru, India"], posted_at=posted_at)


def test_freshness_config_present():
    assert CFG["freshness"]["max_posted_age_days"] == 90


CFG14 = {**CFG, "freshness": {"max_posted_age_days": 14}}


@pytest.mark.parametrize("age,ok", [(0, True), (89, True), (90, True), (91, False), (200, False)])
def test_freshness_cutoff(age, ok):
    today = date(2026, 11, 25)
    v = classify(Jd((today - timedelta(days=age)).isoformat()), CFG, today=today)
    assert v.ok is ok, v.reason
    if not ok:
        assert "posted" in v.reason and "older than 90" in v.reason


@pytest.mark.parametrize("age,ok", [(14, True), (15, False)])
def test_freshness_cutoff_is_configurable(age, ok):
    today = date(2026, 11, 25)
    assert classify(Jd((today - timedelta(days=age)).isoformat()), CFG14, today=today).ok is ok


def test_freshness_keeps_undated_and_unparseable():
    assert classify(Jd(None), CFG).ok
    assert classify(Jd("not a date"), CFG).ok


def test_freshness_disabled_when_unset():
    cfg = {**CFG, "freshness": {}}
    assert classify(Jd("2020-01-01"), cfg).ok


@pytest.mark.parametrize("text,days", [
    ("Posted Today", 0), ("Posted Yesterday", 1), ("Posted 5 Days Ago", 5),
    ("Posted 30+ Days Ago", 30), ("posted 1 day ago", 1),
])
def test_workday_posted_on(text, days):
    today = date(2026, 11, 25)
    assert workday.posted_on_to_date(text, today) == (today - timedelta(days=days)).isoformat()


@pytest.mark.parametrize("text", [None, "", "Recently", "Posted sometime"])
def test_workday_posted_on_unknown(text):
    assert workday.posted_on_to_date(text) is None


def test_workday_30_plus_is_filtered_out():
    today = date(2026, 11, 25)
    data = {"total": 2, "jobPostings": [
        {"title": "Software Engineer", "externalPath": "/a", "locationsText": "India, Bengaluru", "postedOn": "Posted 30+ Days Ago"},
        {"title": "Software Engineer", "externalPath": "/b", "locationsText": "India, Bengaluru", "postedOn": "Posted 2 Days Ago"}]}
    jobs = workday.parse(data, {"host": "h", "site": "s"}, today=today)
    open14 = {**OPEN, "freshness": {"max_posted_age_days": 14}}
    assert [classify(j, open14, today=today).ok for j in jobs] == [False, True]


def test_workday_fetch_paginates(monkeypatch):
    monkeypatch.setattr(workday, "PAGE_DELAY", 0)
    pages = [{"total": 21, "jobPostings": [{"title": f"SWE {i}", "externalPath": f"/{i}", "postedOn": "Posted Today"}
                                           for i in range(20)]},
             {"total": 21, "jobPostings": [{"title": "SWE 20", "externalPath": "/20", "postedOn": "Posted Today"}]}]
    calls = []

    class H:
        def get_text(self, url):
            raise RuntimeError("429")   # warm-up failing must not stop the fetch

        def post_json(self, url, body, headers=None):
            assert headers["Origin"] == "https://h" and url.endswith("/wday/cxs/t/s/jobs")
            calls.append(body["offset"])
            return pages[len(calls) - 1]
    jobs = workday.fetch({"host": "h", "tenant": "t", "site": "s"}, H())
    assert len(jobs) == 21 and calls == [0, 20]


# ── http backoff ────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, headers=None):
        self.status_code, self.headers = status, headers or {}


def test_backoff_honours_retry_after():
    from radar.http import Http
    assert Http._backoff(_Resp(429, {"Retry-After": "7"}), 0) == 7
    assert Http._backoff(_Resp(429, {"Retry-After": "999"}), 0) == 60
    assert Http._backoff(_Resp(429), 1) > Http._backoff(_Resp(503), 1)


# ── sorting newest first ────────────────────────────────────────────────────
def _job(title, posted, score):
    from radar.models import Job
    return Job(id=title, company="C", title=title, url="u", location="Bengaluru", level="open",
               skills=["sde"], score=score, posted_at=posted, first_seen="2026-11-25T00:00:00+00:00",
               last_seen="2026-11-25T00:00:00+00:00")


def test_newest_first_ordering():
    from radar.models import newest_first
    jobs = [_job("old", "2026-11-10", 99), _job("undated", None, 100), _job("new", "2026-11-24", 1),
            _job("mid", "2026-11-20", 50), _job("new-better", "2026-11-24", 5)]
    order = [j.title for j in sorted(jobs, key=lambda j: newest_first(j.posted_at, j.score))]
    assert order == ["new-better", "new", "mid", "old", "undated"]


def test_alert_lists_newest_first_with_age():
    today = date.today()
    jobs = [_job("Older Role", (today - timedelta(days=9)).isoformat(), 90),
            _job("Fresh Role", today.isoformat(), 10)]
    text = notify.build_html(jobs, [], "", 40)
    assert text.index("Fresh Role") < text.index("Older Role")
    assert "posted today" in text and "posted 9 days ago" in text


def test_posted_label():
    t = date(2026, 11, 25)
    assert notify.posted_label("2026-11-25", t) == "posted today"
    assert notify.posted_label("2026-11-24", t) == "posted yesterday"
    assert notify.posted_label("2026-11-20", t) == "posted 5 days ago"
    assert notify.posted_label(None, t) == ""


# ── telegram ────────────────────────────────────────────────────────────────
class _TgResp:
    def __init__(self, status, payload):
        self.status_code, self._p, self.text, self.reason = status, payload, json.dumps(payload), "x"

    def json(self):
        return self._p


@pytest.fixture
def tg(monkeypatch):
    sent = []
    state = {"resp": _TgResp(200, {"ok": True, "result": {"chat": {"id": 42, "first_name": "Me"}}})}

    def post(url, timeout, json):
        sent.append((url, json))
        return state["resp"]
    monkeypatch.setattr(notify.requests, "post", post)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    return sent, state


def test_telegram_strips_newline_from_secrets(tg, monkeypatch, capsys):
    sent, _ = tg
    # the actual production bug: the secret was saved with a trailing newline → ".../bot123:abc%0A/sendMessage" → 404
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 42\n")
    assert notify.telegram([_job("Role", None, 1)], [], "", 40)
    url, body = sent[0]
    assert url == "https://api.telegram.org/bot123:abc/sendMessage" and body["chat_id"] == "42"
    assert "whitespace" in capsys.readouterr().out


def test_send_test_message_ok(tg):
    sent, _ = tg
    assert "42" in notify.send_test_message()
    assert "test message" in sent[0][1]["text"]


def test_telegram_error_is_telegrams_text(tg):
    _, state = tg
    state["resp"] = _TgResp(400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})
    with pytest.raises(notify.TelegramError) as e:
        notify.send_test_message()
    assert "Bad Request: chat not found" in str(e.value) and "123:abc" not in str(e.value)


def test_send_all_prints_annotation_on_failure(tg, capsys):
    _, state = tg
    state["resp"] = _TgResp(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
    sent = notify.send_all([_job("Role", None, 1)], [], "", {"notify": {}}, "stats")
    out = capsys.readouterr().out
    assert sent == []
    assert "::warning title=Alert failed::telegram: Telegram API 401: Unauthorized" in out


def test_send_all_logs_missing_secrets(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    notify.send_all([], [], "", {"notify": {}}, "stats")
    out = capsys.readouterr().out
    assert "telegram disabled: secret(s) not set: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID" in out
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    notify.send_all([], [], "", {"notify": {}}, "stats")
    assert "::warning title=Alert failed::telegram: TELEGRAM_CHAT_ID is not set" in capsys.readouterr().out


def test_warn_escapes_newlines(capsys):
    notify.warn("Alert failed", "a\nb%c")
    assert capsys.readouterr().out.strip() == "::warning title=Alert failed::a%0Ab%25c"


def test_cli_test_notify_exit_codes(tg, monkeypatch, capsys):
    from radar.__main__ import main
    _, state = tg
    assert main(["test-notify"]) == 0
    state["resp"] = _TgResp(404, {"ok": False, "error_code": 404, "description": "Not Found"})
    assert main(["test-notify"]) == 1
    assert "Telegram API 404: Not Found" in capsys.readouterr().out
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    assert main(["test-notify"]) == 1


def test_end_to_end_drops_stale_jobs(repo):
    stale = {"jobs": [{"id": 99, "title": "Software Engineer I", "absolute_url": "https://x/99",
                       "location": {"name": "Bengaluru, India"}, "first_published": ago(120), "content": ""}]}
    r = run(root=repo, http=FakeHttp({"boards/acme": stale}), do_notify=False, verbose=False)
    assert r["new"] == []


def test_dashboard_defaults_to_newest_posted(repo):
    run(root=repo, http=FakeHttp({"boards/acme": GH}), do_notify=False, verbose=False)
    html = (repo / "docs/index.html").read_text()
    assert "sort:'posted'" in html and "posted ${d} days ago" in html


# ── strict fresher mode (the real config) ───────────────────────────────────
def test_config_is_strict_fresher():
    assert CFG["level"]["mode"] == "entry" and CFG["level"]["max_years"] == 1


@pytest.mark.parametrize("title,desc", [
    ("Software Engineer", "We're hiring freshers from the 2026 batch."),
    ("Backend Developer", "0-1 years of experience with Python"),
    ("Software Engineer", "Open to recent graduates with strong DSA."),
    ("SDE-1", ""),
    ("Graduate Engineer Trainee", ""),
    ("Associate Software Engineer", ""),
    ("Associate SDE", ""),
    ("Software Engineer", "Experience: 1+ years of professional experience"),
])
def test_strict_accepts_fresher_signals(title, desc):
    v = classify(J(title, desc=desc), CFG)
    assert v.ok and v.level == "entry", v.reason


@pytest.mark.parametrize("title,desc,why", [
    ("Software Engineer", "", "no fresher signal"),                       # nothing says fresher
    ("Software Engineer", "Build scalable APIs with Go.", "no fresher signal"),
    ("Backend Engineer", "2+ years of experience building APIs", "asks 2+"),
    ("Software Engineering MTS", "Join as an early-career engineer. 3+ yrs of programming exp in Java", "asks 3+"),
    ("Software Engineering LMTS (Database Engineering)",
     "8+ years of experience in database engineering, including 3+ years operating databases on AWS", "senior"),
    ("Software Engineer", "8+ years of experience in database engineering, including 3+ years on AWS", "asks 8+"),
    ("Research Scientist - Nemotron India", "", "excluded title"),
    ("Data Scientist", "freshers welcome", "excluded title"),
    ("AI Automation Engineer Associate", "Python, LLMs", "no fresher signal"),
    ("Testing - Associate", "corporate action processing", "no fresher signal"),
    ("Applied Scientist I", "new grad", "excluded title"),
])
def test_strict_rejects(title, desc, why):
    v = classify(J(title, desc=desc), CFG)
    # a title with no software role word is now rejected earlier, as "not a tech role"
    assert not v.ok and (why in v.reason or "not a tech role" in v.reason), v.reason


def test_desc_entry_signal_is_narrow():
    # "university"/"graduate degree" appear in senior postings too; they must not count
    v = classify(J("Software Engineer", desc="Bachelor's degree from a university; graduate degree preferred."), CFG)
    assert not v.ok


def test_ats_level_hint():
    sr = RawJob("1", "Software Engineer", "u", ["Bengaluru, India"], level_hint="entry_level")
    assert classify(sr, CFG).level == "entry"
    sr.level_hint = "mid_senior_level"
    assert "senior level per job board" in classify(sr, CFG).reason


# ── location matching ───────────────────────────────────────────────────────
@pytest.mark.parametrize("loc", ["Austin, TX, United States", "Indianapolis, IN, United States", "Berlin, Germany",
                                 "Dublin, Ireland", "Wisconsin, USA", "Remote - US"])
def test_location_rejects_lookalikes(loc):
    assert not classify(J("Software Engineer I", loc), CFG).ok


@pytest.mark.parametrize("loc", ["IN, KA, Bengaluru", "IN-Hyderabad", "India - Bengaluru", "Gurugram, Haryana, India",
                                 "Thiruvananthapuram", "Remote - India"])
def test_location_accepts_india(loc):
    assert classify(J("Software Engineer I", loc), CFG).ok


# ── description enrichment ──────────────────────────────────────────────────
WD_DETAIL = {"jobPostingInfo": {"jobDescription": "<p>We hire <b>freshers</b>. 0-1 years of experience.</p>",
                                "startDate": "2026-11-21", "location": "India, Bengaluru",
                                "additionalLocations": ["India, Hyderabad"]}}


def test_workday_apply_detail():
    j = RawJob("/job/x", "Software Engineer", "u", ["2 Locations"])
    workday.apply_detail(j, WD_DETAIL)
    assert "freshers" in j.description and j.posted_at == "2026-11-21"
    assert j.locations == ["India, Bengaluru", "India, Hyderabad"]


def test_smartrecruiters_describe_and_level():
    s = smartrecruiters.parse({"content": [{"id": "9", "name": "Software Engineer", "releasedDate": ago(1),
                                            "experienceLevel": {"id": "entry_level"},
                                            "location": {"city": "Pune", "country": "in"}}]}, {"slug": "X"})
    assert s[0].level_hint == "entry_level"

    class H:
        def get_json(self, url, **kw):
            assert url.endswith("/companies/X/postings/9")
            return {"jobAd": {"sections": {"jobDescription": {"text": "<p>Build things</p>"},
                                           "qualifications": {"text": "<li>0-1 years</li>"}}}}
    smartrecruiters.describe({"slug": "X"}, s[0], H())
    assert "Build things" in s[0].description and "0-1 years" in s[0].description


def test_runner_fetches_descriptions_only_for_precheck_survivors_and_caches(tmp_path, monkeypatch):
    from radar import runner
    from radar.store import Store
    monkeypatch.setattr(workday, "PAGE_DELAY", 0)
    raw = [RawJob("/job/a", "Software Engineer", "u", ["India, Bengaluru"], posted_at=ago(1)),
           RawJob("/job/b", "Senior Software Engineer", "u", ["India, Bengaluru"], posted_at=ago(1)),   # senior: no fetch
           RawJob("/job/c", "Software Engineer", "u", ["Austin, TX"], posted_at=ago(1)),                # location: no fetch
           RawJob("/job/d", "Software Engineer", "u", ["India, Pune"], posted_at=ago(1))]
    fetched = []

    class H:
        def get_json(self, url, headers=None, **kw):
            fetched.append(url.rsplit("/", 1)[-1])
            if url.endswith("/a"):
                return WD_DETAIL
            return {"jobPostingInfo": {"jobDescription": "5+ years of experience required"}}
    c = {"name": "Co", "ats": "workday", "host": "h", "tenant": "t", "site": "s"}
    store = Store(tmp_path)
    out = runner.enrich_and_classify(c, raw, CFG, store, H(), "2026-11-25T00:00:00+00:00")
    assert fetched == ["a", "d"]
    assert [r.source_id for r, v, jid in out] == ["/job/a"]
    assert set(store.details) == {"workday:co:/job/a", "workday:co:/job/d"}

    # second run: served from the cache, nothing fetched again
    fetched.clear()
    raw2 = [RawJob("/job/a", "Software Engineer", "u", ["India, Bengaluru"], posted_at=ago(1))]
    out2 = runner.enrich_and_classify(c, raw2, CFG, store, H(), "2026-11-25T06:00:00+00:00")
    assert fetched == [] and len(out2) == 1


def test_runner_keeps_going_when_a_description_fails(tmp_path):
    from radar import runner
    from radar.store import Store

    class H:
        def get_json(self, url, headers=None, **kw):
            raise RuntimeError("HTTP 429")
    c = {"name": "Co", "ats": "smartrecruiters", "slug": "Co"}
    raw = [RawJob("1", "SDE-1", "u", ["Bengaluru, India"], posted_at=ago(1))]
    out = runner.enrich_and_classify(c, raw, CFG, Store(tmp_path), H(), "2026-11-25T00:00:00+00:00")
    assert len(out) == 1   # the title alone says fresher, so it still counts


# ── failing-board alerts ────────────────────────────────────────────────────
def test_broken_board_alerts_only_after_repeated_failures_and_never_for_rate_limits(repo):
    from radar.http import RateLimited
    (repo / "companies.yaml").write_text(yaml.safe_dump({"companies": [
        {"name": "Acme", "ats": "greenhouse", "slug": "acme"},
        {"name": "Busy", "ats": "greenhouse", "slug": "busy"}]}))
    boards = {"boards/acme": RuntimeError("boom"), "boards/busy": RateLimited("HTTP 429")}
    alerts = []
    import radar.runner as rr
    orig = rr.notify.send_all
    rr.notify.send_all = lambda new, broken, *a, **k: alerts.append(list(broken)) or []
    try:
        for _ in range(4):
            run(root=repo, http=FakeHttp(boards), do_notify=True, verbose=False)
    finally:
        rr.notify.send_all = orig
    assert alerts == [[], [], ["Acme"], []]
    health = json.loads((repo / "data/health.json").read_text())
    assert health["Busy"]["status"] == "rate_limited" and health["Acme"]["status"] == "error"


# ── workflow ────────────────────────────────────────────────────────────────
def test_workflow_runs_four_times_a_day_and_survives_overlapping_runs():
    wf = yaml.safe_load((ROOT / ".github/workflows/radar.yml").read_text())
    cron = wf[True]["schedule"][0]["cron"] if True in wf else wf["on"]["schedule"][0]["cron"]
    assert len(cron.split()[1].split(",")) == 4
    save = next(s for s in wf["jobs"]["scan"]["steps"] if s.get("name") == "Save results")["run"]
    # results are copied aside and re-applied on the latest commit: no rebase conflicts
    assert "reset -q --hard" in save and "cp -r \"$out\"/data" in save and "rebase" not in save


# ── role relevance: software development only ───────────────────────────────
@pytest.mark.parametrize("title", [
    "Technical Support Engineer I", "Associate, ML Data Operations, GO-AI Operations",
    "Data Centre Linux & HW Engineer", "Network Operation Engineering I", "Sales Engineer",
    "Customer Engineer", "Implementation Engineer", "Software Engineering MTS - Production Support",
    "Associate Engineer - Mechanical (Cost Out)", "Manufacturing Engineer", "PMIC Design Verification Engineer",
    "NOC DV Assoc Engineer", "Hardware Engineer", "Associate Engineer - Safety & Reliability", "Technical Solution Engineer",
])
def test_non_dev_roles_excluded(title):
    v = classify(J(title, desc="freshers welcome"), CFG)
    assert not v.ok and ("excluded title" in v.reason or "not a tech role" in v.reason), v.reason


@pytest.mark.parametrize("title", ["Software Engineer", "SDE-1", "DevOps Engineer", "Site Reliability Engineer",
                                   "Data Engineer", "Frontend Developer", "CPU Software Engineer", "Advanced Software Engineer"])
def test_dev_roles_not_excluded(title):
    assert classify(J(title, desc="freshers welcome"), CFG).ok


def test_entry_hint_skips_grade_but_not_senior_words():
    g = RawJob("1", "Software Engineer II, Google Cloud", "u", ["Hyderabad, Telangana, India"],
               description="1 year of experience with software development", level_hint="entry_level")
    assert classify(g, CFG).ok
    g.title = "Senior Software Engineer"
    assert not classify(g, CFG).ok
    plain = RawJob("1", "Software Engineer II", "u", ["Hyderabad, India"], description="1 year of experience")
    assert "senior title" in classify(plain, CFG).reason


# ── big-tech adapters ───────────────────────────────────────────────────────
from radar.sources import google, microsoft, oracle_hcm

MS = {"count": 2, "positions": [
    {"id": 111, "name": "Software Engineer", "locations": ["India, Telangana, Hyderabad"], "postedTs": 1795591298,
     "positionUrl": "/careers/job/111", "workLocationOption": "onsite", "department": "Software Engineering"},
    {"id": 222, "name": "Principal Software Engineering Manager", "locations": ["India, Karnataka, Bangalore"],
     "postedTs": 1795591298, "positionUrl": "/careers/job/222"}]}


def test_microsoft_parse_and_describe():
    jobs = microsoft.parse(MS, {})
    assert jobs[0].url == "https://apply.careers.microsoft.com/careers/job/111"
    assert jobs[0].locations == ["India, Telangana, Hyderabad"] and jobs[0].posted_at == "2026-11-25"

    class H:
        def get_json(self, url, **kw):
            assert url.endswith("/api/pcsx/position_details") and kw["position_id"] == "111"
            return {"data": {"jobDescription": "<p>New graduates welcome</p>"}}
    microsoft.describe({}, jobs[0], H())
    assert jobs[0].description == "New graduates welcome"


def _google_job(jid, title, loc, ts, quals):
    j = [None] * 21
    j[0], j[1], j[9], j[12] = jid, title, [[loc, [], "", "", "", "IN"]], [ts, 0]
    j[3], j[4], j[10], j[19] = [None, "<li>Write code</li>"], [None, quals], [None, "<p>About</p>"], [None, ""]
    return j


def test_google_parse_embedded_data():
    data = [[_google_job("83624643516080838", "Software Engineer II, Google Cloud", "Hyderabad, Telangana, India",
                         1795435695, "<li>1 year of experience with software development</li>")], None, 1, 20]
    html = ("<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:" + json.dumps(data) +
            ", sideChannel: {}});</script>")
    j = google.parse(html, {})[0]
    assert j.url.endswith("/83624643516080838-software-engineer-ii-google-cloud")
    assert j.locations == ["Hyderabad, Telangana, India"] and j.posted_at == "2026-11-23"
    assert "1 year of experience" in j.description and j.level_hint == "entry_level"
    v = classify(j, CFG, today=date(2026, 11, 25))
    assert v.ok and v.level == "entry", v.reason


def test_google_layout_change_is_an_error():
    with pytest.raises(ValueError):
        google.parse("<html>nothing here</html>", {})


def test_oracle_hcm_parse():
    item = {"TotalJobsCount": 1, "requisitionList": [{
        "Id": "210794929", "Title": "Software Engineer I", "PostedDate": "2026-11-25",
        "PrimaryLocation": "Bengaluru, Karnataka, India", "secondaryLocations": [{"Name": "Hyderabad, Telangana, India"}],
        "ExternalQualificationsStr": "<li>0-1 years of experience</li>"}]}
    c = {"host": "jpmc.fa.oraclecloud.com", "site": "CX_1001"}
    j = oracle_hcm.parse(item, c)[0]
    assert j.url == "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210794929"
    assert j.locations == ["Bengaluru, Karnataka, India", "Hyderabad, Telangana, India"]
    assert j.description == ""     # the list's summary is partial: the runner fetches the full posting

    class H:
        def get_json(self, url, **kw):
            assert url.endswith("/recruitingCEJobRequisitionDetails") and '210794929' in kw["finder"]
            return {"items": [{"ExternalQualificationsStr": "<li>0-1 years of experience</li>"}]}
    oracle_hcm.describe(c, j, H())
    assert "0-1 years" in j.description and classify(j, CFG, today=date(2026, 11, 25)).ok


# ── duplicates ──────────────────────────────────────────────────────────────
def test_same_title_and_location_kept_once(repo):
    dup = {"jobs": [{"id": i, "title": "Software Engineer I", "absolute_url": f"https://x/{i}",
                     "location": {"name": "Bengaluru, India"}, "first_published": ago(1), "content": ""}
                    for i in (1, 2)]}
    r = run(root=repo, http=FakeHttp({"boards/acme": dup}), do_notify=False, verbose=False)
    assert len([j for j in r["new"] if j.company == "Acme"]) == 1


def test_every_company_uses_a_known_adapter():
    from radar.sources import ADAPTERS
    comps = yaml.safe_load((ROOT / "companies.yaml").read_text())["companies"]
    assert len(comps) > 100
    assert all(c["ats"] in ADAPTERS for c in comps)


# ── more careers platforms ──────────────────────────────────────────────────
from radar.sources import atlassian, capgemini, keka, kula, successfactors, uber
from radar.text import strip_html


def test_strip_html_drops_scripts_and_styles():
    assert strip_html("<p>Hi</p><script>var x = 'secret';</script><style>.a{}</style><p>there</p>") == "Hi there"


def test_keka_parse_and_portal_discovery():
    data = [{"id": 7, "title": "Software Engineer - Fresher", "description": "<p>Build APIs</p>", "experience": "0-1 Years",
             "jobLocations": [], "publishedOn": "2026-11-24T11:41:25Z", "departmentName": "Engineering"}]
    j = keka.parse(data, {"host": "acme.keka.com"})[0]
    assert j.url == "https://acme.keka.com/careers/jobdetails/7" and j.locations == ["India"]
    assert j.description.startswith("Experience: 0-1 Years.") and classify(j, CFG, today=date(2026, 11, 25)).level == "entry"

    class H:
        def get_text(self, url):
            return '<script>fetch("/ats/documents/b5279857-cf81-4dde-a215-fc48957ee2b5/careerportal/x.html")</script>'

        def get_json(self, url, **kw):
            assert url.endswith("/careers/api/embedjobs/default/active/b5279857-cf81-4dde-a215-fc48957ee2b5")
            return data
    assert len(keka.fetch({"host": "acme.keka.com"}, H())) == 1


def test_keka_experience_field_rejects_seniors():
    j = keka.parse([{"id": 1, "title": "Backend Developer", "experience": "13-15 Years", "description": ""}], {"host": "a"})[0]
    assert "asks 13+" in classify(j, CFG).reason


def test_kula_parse_embedded_next_payload():
    job = {"id": 5565, "account_id": 1291, "title": "Software Development Engineer 1", "listed": True, "on_career_page": True,
           "launch_at": "2026-11-20T06:46:30.000Z",
           "ats_job": {"workplace": "office", "ats_department": {"name": "Engineering"},
                       "offices": [{"location": "Bengaluru, Karnataka, India", "remote": False}]}}
    hidden = {**job, "id": 9, "title": "Hidden", "on_career_page": False}
    payload = json.dumps([job, hidden])
    html = '<script>self.__next_f.push([1,' + json.dumps(payload) + '])</script>'
    jobs = kula.parse(html, {"slug": "cashfree"})
    assert [j.title for j in jobs] == ["Software Development Engineer 1"]
    assert jobs[0].url == "https://careers.kula.ai/cashfree/5565" and jobs[0].posted_at == "2026-11-20"
    assert jobs[0].locations == ["Bengaluru, Karnataka, India"]


def test_uber_parse():
    data = {"jobs": [{"Id": "305180", "Title": "Software Engineer I", "DisplayDate": "2026-11-25T07:00:56Z",
                      "Description": "<p>0-1 years</p>", "Remote": "False", "Teams": ["Engineering"],
                      "Locations": [{"City": "Hyderabad", "Region": "Telangana", "Country": "India"}],
                      "Urls": [{"Url": "/en/jobs/305180/", "IsDefault": True}]}], "totalPages": 1}
    j = uber.parse(data, {})[0]
    assert j.url == "https://jobs.uber.com/en/jobs/305180/" and j.locations == ["Hyderabad, Telangana, India"]
    assert classify(j, CFG, today=date(2026, 11, 25)).ok


def test_atlassian_parse():
    data = [{"id": 27339, "title": "Graduate Software Engineer", "category": "Engineering",
             "locations": ["Bengaluru - India -   Bengaluru,  560071 India"], "qualifications": "<p>new grads</p>",
             "portalJobPost": {"portalUrl": "https://careers-apac-atlassian.icims.com/jobs/27339/x/job", "updatedDate": "2026-11-23 03:02 PM"}}]
    j = atlassian.parse(data, {})[0]
    assert j.locations == ["Bengaluru - India - Bengaluru, 560071 India"] and j.posted_at == "2026-11-23"
    assert classify(j, CFG, today=date(2026, 11, 25)).level == "entry"


def test_successfactors_parse():
    data = {"totalJobs": 1, "jobSearchResult": [{"response": {
        "id": "206685", "unifiedStandardTitle": "Software Engineer - Fresher", "urlTitle": "Software-Engineer-Fresher",
        "unifiedStandardStart": "11/25/26", "supportedLocales": ["en_US"], "jobLocationCountry": ["India"],
        "jobLocationShort": ["Pune, IND-27, IND, 411005<br/>"]}}]}
    j = successfactors.parse(data, {"host": "careers.wipro.com"})[0]
    assert j.url == "https://careers.wipro.com/job/Software-Engineer-Fresher/206685-en_US/"
    assert j.posted_at == "2026-11-25" and j.locations == ["Pune, IND-27, IND, 411005, India"]
    assert classify(j, CFG, today=date(2026, 11, 25)).ok


def test_capgemini_parse_and_level_labels():
    data = {"count": 2, "data": [
        {"id": "1", "ref": "1-en", "title": "Software Engineer", "location": "Pune", "experience_level": "Experienced Professionals",
         "updated_at": "2026-11-25T08:32:41Z", "description": "<p>Java</p>", "apply_job_url": "https://careers.capgemini.com/job/1"},
        {"id": "2", "ref": "2-en", "title": "Software Engineer", "location": "Bangalore", "experience_level": "Freshers",
         "updated_at": "2026-11-25T08:32:41Z", "description": "<p>Java</p>", "apply_job_url": "https://careers.capgemini.com/job/2"}]}
    exp, fresh = capgemini.parse(data, {})
    assert exp.locations == ["Pune, India"]
    assert "senior level per job board" in classify(exp, CFG, today=date(2026, 11, 25)).reason
    assert classify(fresh, CFG, today=date(2026, 11, 25)).level == "entry"


def test_eightfold_generic_host_and_domain():
    class H:
        def get_json(self, url, **kw):
            assert url == "https://careers.qualcomm.com/api/pcsx/search" and kw["domain"] == "qualcomm.com"
            return {"data": {"count": 1, "positions": [{"id": 5, "name": "Engineer I", "locations": ["Bangalore, India"],
                                                        "postedTs": 1795591298, "positionUrl": "/careers/job/5"}]}}
    j = microsoft.fetch({"host": "careers.qualcomm.com", "domain": "qualcomm.com"}, H())[0]
    assert j.url == "https://careers.qualcomm.com/careers/job/5"


# ── experience in the title, and wrong job-board level tags ──────────────────
from radar.classify import title_years


@pytest.mark.parametrize("title,n", [("Product Solution Engineer  (1 to 3)", 1), ("Software Engineer (3-5 years), Symphony", 3),
                                     ("Software Engineer (5-7 years,Firmware)", 5), ("SRE - On-Prem (1 to 4 Years)", 1),
                                     ("Backend Engineer 2+ yrs", 2), ("Platform Engineer 2", None), ("SDE-1", None)])
def test_title_years(title, n):
    assert title_years(title) == n


def test_title_years_decide_level():
    assert classify(J("Site Reliability Engineer - On-Prem (1 to 4 Years)", desc="5+ years preferred"), CFG).level == "entry"
    assert "title asks 3+" in classify(J("Software Engineer, Backend (3-5 years)"), CFG).reason


def test_entry_title_beats_wrong_job_board_tag():
    j = RawJob("1", "Platform Engineer 1", "u", ["Bengaluru, India"], level_hint="executive")
    assert classify(j, CFG).level == "entry"
    j.title = "Software Engineer - React Native"
    j.level_hint = "mid_senior_level"
    assert "senior level per job board" in classify(j, CFG).reason


# ── Jooble aggregator ────────────────────────────────────────────────────────
from radar.http import SourceDisabled
from radar.sources import jooble

JOOBLE = {"totalCount": 2, "jobs": [
    {"id": 111, "title": "Software Engineer - Fresher", "company": "Tiny Startup Pvt Ltd", "location": "Pune",
     "snippet": "Freshers welcome. 0-1 years. Java, Spring Boot", "updated": ago(2) + "T00:00:00.0000000",
     "link": "https://jooble.org/desc/111"},
    {"id": 222, "title": "Software Engineer I", "company": "Acme", "location": "Bengaluru, India",
     "snippet": "0-1 years", "updated": ago(1) + "T00:00:00.0000000", "link": "https://jooble.org/desc/222"}]}


def test_jooble_parse():
    j = jooble.parse(JOOBLE, {})[0]
    assert j.company == "Tiny Startup Pvt Ltd" and j.locations == ["Pune, India"] and j.posted_at == ago(2)
    assert classify(j, CFG).level == "entry"


def test_jooble_skipped_without_key(monkeypatch):
    monkeypatch.delenv("JOOBLE_KEY", raising=False)
    with pytest.raises(SourceDisabled):
        jooble.fetch({}, None)


def test_jooble_error_never_contains_the_key(monkeypatch):
    monkeypatch.setenv("JOOBLE_KEY", "secret-key-123")

    class H:
        def post_json(self, url, body, headers=None):
            raise RuntimeError(f"HTTP 403 at {url}")
    with pytest.raises(RuntimeError) as e:
        jooble.fetch({"queries": ["x"]}, H())
    assert "secret-key-123" not in str(e.value) and "***" in str(e.value)


def test_jooble_runs_after_boards_and_skips_known_jobs(repo, monkeypatch):
    monkeypatch.setenv("JOOBLE_KEY", "k")
    (repo / "companies.yaml").write_text(yaml.safe_dump({"companies": [
        {"name": "Jooble", "ats": "jooble", "queries": ["software engineer fresher"], "pages_per_query": 1},
        {"name": "Acme", "ats": "greenhouse", "slug": "acme"}]}))   # aggregator listed first on purpose

    class H(FakeHttp):
        def post_json(self, url, body, headers=None):
            assert url == "https://jooble.org/api/k"
            return JOOBLE
    r = run(root=repo, http=H({"boards/acme": GH}), do_notify=False, verbose=False)
    by = {(j.company, j.title): j for j in r["new"]}
    assert ("Acme", "Software Engineer I") in by and by[("Acme", "Software Engineer I")].source == ""   # from Acme's own board
    assert by[("Tiny Startup Pvt Ltd", "Software Engineer - Fresher")].source == "Jooble"
    assert len([k for k in by if k[1] == "Software Engineer I"]) == 1                                   # not repeated via Jooble

    # a second run that no longer lists the startup job closes it (by source, not company)
    monkeypatch.setattr(jooble, "parse", lambda data, c: [])
    run(root=repo, http=H({"boards/acme": GH}), do_notify=False, verbose=False)
    jobs = json.loads((repo / "data/jobs.json").read_text())
    tiny = [j for j in jobs.values() if j["company"] == "Tiny Startup Pvt Ltd"]
    assert tiny and tiny[0]["status"] == "closed"


def test_runner_skips_disabled_source_quietly(repo, monkeypatch):
    monkeypatch.delenv("JOOBLE_KEY", raising=False)
    (repo / "companies.yaml").write_text(yaml.safe_dump({"companies": [{"name": "Jooble", "ats": "jooble"}]}))
    r = run(root=repo, http=FakeHttp({}), do_notify=False, verbose=False)
    assert r["failing"] == [] and "Jooble" not in json.loads((repo / "data/health.json").read_text())


def test_workflow_passes_jooble_secret():
    assert "JOOBLE_KEY:         ${{ secrets.JOOBLE_KEY }}" in (ROOT / ".github/workflows/radar.yml").read_text()


# ── Freshteam, detection of every platform, and `radar add` ─────────────────
from radar import detect as detect_mod
from radar.sources import freshteam


def test_freshteam_parse_joins_branch_location():
    data = {"branches": [{"id": 9, "city": "Chennai", "state": "Tamil Nadu", "country_code": "IN", "location": "Chennai, Tamil Nadu"}],
            "jobs": [{"id": "1", "title": "Backend Developer (SDE 1)", "branch_id": "9", "created_at": ago(3) + "T11:44:56Z",
                      "description": "<p>0-1 years</p>", "remote": "False", "url": "https://acme.com/careers?jobId=x"},
                     {"id": "2", "title": "Gone", "branch_id": "9", "deleted": True}]}
    jobs = freshteam.parse(data, {"slug": "acme"})
    assert [j.title for j in jobs] == ["Backend Developer (SDE 1)"]
    assert jobs[0].locations == ["Chennai, Tamil Nadu, India"] and jobs[0].posted_at == ago(3)
    assert classify(jobs[0], CFG).level == "entry"


@pytest.mark.parametrize("text,expected", [
    ('<a href="https://jupiter.keka.com/careers">', {"ats": "keka", "host": "jupiter.keka.com"}),
    ('<a href="https://careers.kula.ai/cashfree">', {"ats": "kula", "slug": "cashfree"}),
    ('<script src="https://qualcomm.eightfold.ai/x.js">', {"ats": "eightfold", "host": "qualcomm.eightfold.ai", "domain": "qualcomm.com"}),
    ('fetch("https://ibqbjb.fa.ocs.oraclecloud.com/hcm") /sites/CX_1/jobs', {"ats": "oracle_hcm", "host": "ibqbjb.fa.ocs.oraclecloud.com", "site": "CX_1"}),
    ('<a href="https://ninjacart.freshteam.com/jobs">', {"ats": "freshteam", "slug": "ninjacart"}),
    ('job-boards.greenhouse.io/razorpaysoftwareprivatelimited', {"ats": "greenhouse", "slug": "razorpaysoftwareprivatelimited"}),
])
def test_detect_every_platform(text, expected):
    assert expected in detect_mod.detect_in(text)


def test_detect_successfactors_by_page_markers():
    hits = detect_mod.detect_in('<script src="https://hcm55.sapsf.eu/rmk-jobs-search/x.js">', "https://careers.wipro.com/search/")
    assert {"ats": "successfactors", "host": "careers.wipro.com"}.items() <= hits[0].items()


def test_add_company_appends_first_working_board(tmp_path):
    f = tmp_path / "companies.yaml"
    f.write_text("companies:\n  - { name: Old, ats: kula, slug: cashfree }\n")

    class H:
        def get_text(self, url):
            return {"https://new.example/careers": '<a href="https://careers.kula.ai/newco">jobs</a>',
                    "https://darwin.example/careers": '<script src="https://x.darwinbox.in/a.js">'}.get(url, "")

    import radar.sources.kula as kmod
    orig = kmod.fetch
    kmod.fetch = lambda c, h: [RawJob("1", "SDE 1", "u", ["Bengaluru, India"])]
    try:
        e, log = detect_mod.add_company("https://new.example/careers", "NewCo", f, H(), "2026-11-25")
        assert e and e["slug"] == "newco"
        saved = yaml.safe_load(f.read_text())["companies"]
        assert saved[-1] == {"name": "NewCo", "ats": "kula", "slug": "newco", "verified": date(2026, 11, 25)}
        # same name again, or a board already tracked, is refused
        assert detect_mod.add_company("https://new.example/careers", "NewCo", f, H(), "2026-11-25")[0] is None
        e2, log2 = detect_mod.add_company("https://new.example/careers", "Other", f, H(), "2026-11-25")
        assert e2 is None and "already tracked as NewCo" in log2[0]
        # an unsupported careers system is named
        e3, log3 = detect_mod.add_company("https://darwin.example/careers", "Darwin", f, H(), "2026-11-25")
        assert e3 is None and "Darwinbox" in log3[0]
    finally:
        kmod.fetch = orig


def test_keka_standard_page_without_custom_portal():
    class H:
        def get_text(self, url):
            return "<html><base href='/careers/'></html>"

        def get_json(self, url, **kw):
            assert url == "https://wingify.keka.com/careers/api/jobs/default/active"
            return [{"id": 1, "title": "Software Engineer - Fresher", "experience": "0-1 Years", "jobLocations": []}]
    assert len(keka.fetch({"host": "wingify.keka.com"}, H())) == 1


# ── fresher-hiring evidence and the Indian startups directory ───────────────
from radar.classify import fresher_role_kind
from radar.render import careers_link, startup_directory


@pytest.mark.parametrize("title,loc,desc,kind", [
    ("SDE I", "Bengaluru, India", "", "entry"),
    ("Fullstack Engineer, Product Team (New Grad)", "Bengaluru", "", "entry"),
    ("Associate Software Engineer", "Pune", "", "entry"),
    ("Software Engineer (0-1 years)", "Hyderabad", "", "entry"),
    ("Software Engineering Intern", "Bengaluru", "", "intern"),
    ("SDE II", "Bengaluru", "", None),
    ("Senior Backend Engineer", "Bengaluru", "", None),
    ("SDE I", "San Francisco, CA", "", None),
    ("Technical Support Engineer I", "Bengaluru", "", None),
    ("Software Engineer", "Bengaluru", "3+ years of experience", None),
    ("Software Engineer", "Bengaluru", "", None),            # no level stated: not evidence
])
def test_fresher_role_kind(title, loc, desc, kind):
    assert fresher_role_kind(J(title, loc, desc), CFG) == kind


def test_fresher_evidence_ignores_posting_age():
    old = RawJob("1", "SDE I", "u", ["Bengaluru, India"], posted_at="2025-01-01")
    assert not classify(old, CFG).ok and fresher_role_kind(old, CFG) == "entry"


def test_runner_records_fresher_history(repo):
    board = {"jobs": [
        {"id": 1, "title": "SDE I", "absolute_url": "https://x/1", "location": {"name": "Bengaluru, India"}, "first_published": "2025-01-01"},
        {"id": 2, "title": "Software Engineering Intern", "absolute_url": "https://x/2", "location": {"name": "Pune, India"}, "first_published": ago(1)},
        {"id": 3, "title": "Senior Engineer", "absolute_url": "https://x/3", "location": {"name": "Pune, India"}, "first_published": ago(1)}]}
    run(root=repo, http=FakeHttp({"boards/acme": board}), do_notify=False, verbose=False)
    rec = json.loads((repo / "data/companies.json").read_text())["Acme"]
    assert rec["open_entry"] == 1 and rec["open_intern"] == 1 and len(rec["seen"]) == 2
    # next run lists nothing: still remembered as evidence, but nothing open now
    run(root=repo, http=FakeHttp({"boards/acme": {"jobs": []}}), do_notify=False, verbose=False)
    rec = json.loads((repo / "data/companies.json").read_text())["Acme"]
    assert rec["open_entry"] == 0 and len(rec["seen"]) == 2 and rec["first_fresher_seen"]


def test_startup_directory(repo):
    (repo / "startups.yaml").write_text(yaml.safe_dump({"tracked": ["Acme"], "manual": [
        {"name": "Darwin Co", "careers": "https://darwin.example/careers", "system": "Darwinbox"}]}))
    board = {"jobs": [{"id": 1, "title": "SDE I", "absolute_url": "https://x/1", "location": {"name": "Bengaluru, India"},
                       "first_published": ago(1), "content": "0-1 years"}]}
    run(root=repo, http=FakeHttp({"boards/acme": board}), do_notify=False, verbose=False)
    from radar.store import Store
    d = {x["name"]: x for x in startup_directory(repo, Store(repo / "data"))}
    assert d["Acme"]["tracked"] and d["Acme"]["open_entry"] == 1 and d["Acme"]["fresher_seen"] == 1
    assert d["Acme"]["careers"] == "https://job-boards.greenhouse.io/acme" and d["Acme"]["examples"][0]["title"] == "SDE I"
    assert d["Darwin Co"] == {"name": "Darwin Co", "tracked": False, "system": "Darwinbox", "careers": "https://darwin.example/careers"}
    html = (repo / "docs/index.html").read_text()
    assert "Darwin Co" in html and 'id="startupbox"' in html


def test_careers_links():
    assert careers_link({"ats": "keka", "host": "jupiter.keka.com"}) == "https://jupiter.keka.com/careers/"
    assert careers_link({"ats": "lever", "slug": "cred"}) == "https://jobs.lever.co/cred"


def test_startups_yaml_names_are_tracked_companies():
    s = yaml.safe_load((ROOT / "startups.yaml").read_text())
    names = {c["name"] for c in yaml.safe_load((ROOT / "companies.yaml").read_text())["companies"]}
    assert set(s["tracked"]) <= names
    assert len(s["tracked"]) > 90 and len(s["manual"]) > 150
    assert not {m["name"] for m in s["manual"]} & set(s["tracked"])


@pytest.mark.parametrize("title", ["Test Jerin", "AI Writer - Guru", "Benefit Verification Specialist - AI Agents",
                                   "Intern - AI Search & SEO", "Growth Analyst – AI & Automation"])
def test_titles_without_a_dev_role_are_not_tech(title):
    assert "not a tech role" in classify(J(title, desc="freshers welcome"), OPEN).reason
    assert fresher_role_kind(J(title, desc="freshers welcome"), CFG) is None


@pytest.mark.parametrize("title", ["Machine Learning/ AI Intern", "SRE-1", "Software Development Engineer 1", "QA Engineer I",
                                   "Data Analyst - Fresher", "SDET - Software Development Engineer in Test"])
def test_dev_role_titles_still_count(title):
    assert fresher_role_kind(J(title, desc="0-1 years"), CFG) in ("entry", "intern")
