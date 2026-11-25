"""
python -m radar run                 fetch every board, update data/, rebuild dashboard, alert
python -m radar run --only cred     just one company (substring match)
python -m radar run --no-notify     don't send Telegram/email
python -m radar check               health-check every board without saving jobs
python -m radar detect <url> ...    find a company's ATS from its careers page
python -m radar explain "<title>" [--loc ..] [--desc ..] [--posted YYYY-MM-DD]   why would this job pass/fail?
python -m radar test-notify         send a Telegram test message; exits 1 with Telegram's error
"""
from __future__ import annotations

import argparse
import sys

import yaml

from . import notify
from .classify import classify
from .detect import detect
from .http import Http
from .models import RawJob
from .runner import ROOT, fetch_one, load_yaml, run


def main(argv=None):
    p = argparse.ArgumentParser(prog="radar", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--only")
    r.add_argument("--no-notify", action="store_true")
    sub.add_parser("check")
    d = sub.add_parser("detect")
    d.add_argument("urls", nargs="+")
    e = sub.add_parser("explain")
    e.add_argument("title")
    e.add_argument("--loc", default="Bengaluru, India")
    e.add_argument("--desc", default="")
    e.add_argument("--posted", default=None, help="posted date, YYYY-MM-DD")
    sub.add_parser("test-notify")
    a = p.parse_args(argv)

    if a.cmd == "run":
        res = run(only=a.only, do_notify=not a.no_notify)
        total = len(load_yaml(ROOT / "companies.yaml")["companies"])
        # Fail the CI run (so GitHub emails you) only if most boards broke at once —
        # that means something systemic, e.g. network or a code bug.
        return 1 if len(res["failing"]) > total / 2 else 0

    if a.cmd == "check":
        http = Http(retries=1)
        bad = 0
        for c in load_yaml(ROOT / "companies.yaml")["companies"]:
            _, jobs, err = fetch_one(c, http)
            mark = "✓" if err is None and jobs else ("∅" if err is None else "✗")
            bad += err is not None
            print(f"{mark} {c['name']:<14} {c['ats']:<16} "
                  f"{len(jobs) if err is None else type(err).__name__ + ': ' + str(err)[:70]}")
        return 1 if bad else 0

    if a.cmd == "detect":
        http = Http(retries=1)
        for u in a.urls:
            try:
                hits = detect(u, http)
            except Exception as ex:  # noqa: BLE001
                print(f"# {u}\n#   could not load: {ex}\n")
                continue
            if not hits:
                print(f"# {u}\n#   no known ATS found (may be a custom site — see README)\n")
                continue
            print(f"# {u}")
            for h in hits:
                print(yaml.safe_dump([{"name": "CHANGE_ME", **h}], sort_keys=False).strip())
            print()
        return 0

    if a.cmd == "explain":
        cfg = load_yaml(ROOT / "config.yaml")
        v = classify(RawJob("x", a.title, "", [a.loc], posted_at=a.posted, description=a.desc), cfg)
        print(("PASS " if v.ok else "FAIL ") + v.reason)
        if v.ok:
            print(f"  level={v.level} skills={v.skills} years={v.years} score={v.score} loc={v.location}")
        return 0

    if a.cmd == "test-notify":
        try:
            print(f"[notify] telegram OK: {notify.send_test_message()}")
            return 0
        except notify.TelegramError as ex:
            print(f"[notify] telegram failed: {ex}")
            notify.warn("Alert failed", f"telegram: {ex}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
