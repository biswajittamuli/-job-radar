from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from . import notify, render
from .classify import classify
from .http import BoardNotFound, Http, RateLimited
from .models import Job, newest_first
from .sources import ADAPTERS
from .store import Store, now_iso

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def company_key(c: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-")


MAX_DESCRIBE_PER_BOARD = 60   # detail requests per board per run (cached afterwards)
ALERT_AFTER_FAILURES = 3      # a board must fail this many runs in a row before you're alerted


def enrich_and_classify(c: dict, raw: list, cfg: dict, store, http, ts: str, verbose=False):
    """Classify one board's jobs. Jobs whose list entry has no description get a cheap
    title/location/date pre-check first; only the survivors have their full posting fetched
    (and cached in data/details.json), so the experience/fresher checks can read it."""
    adapter = ADAPTERS[c["ats"]]
    describe = getattr(adapter, "describe", None)
    out, fetched, failed = [], 0, 0
    for r in raw:
        jid = f"{c['ats']}:{company_key(c)}:{r.source_id}"
        if describe and not r.description:
            if not classify(r, cfg, check_level=False).ok:
                continue
            cached = store.details.get(jid)
            if cached:
                r.description = cached.get("description", "")
                r.posted_at = cached.get("posted_at") or r.posted_at
                r.locations = cached.get("locations") or r.locations
                cached["seen"] = ts
            elif fetched < MAX_DESCRIBE_PER_BOARD:
                fetched += 1
                try:
                    describe(c, r, http)
                    store.details[jid] = {"description": r.description[:6000], "posted_at": r.posted_at,
                                          "locations": r.locations, "seen": ts}
                except Exception as e:  # noqa: BLE001 — classify on what we have
                    failed += 1
                    if verbose and failed == 1:
                        print(f"    ! {c['name']}: couldn't read a job description ({str(e)[:70]})")
        v = classify(r, cfg)
        if v.ok:
            out.append((r, v, jid))
    return out


def fetch_one(c: dict, http) -> tuple[dict, list, Exception | None]:
    try:
        return c, ADAPTERS[c["ats"]].fetch(c, http), None
    except Exception as e:  # noqa: BLE001 — every failure is recorded per board
        return c, [], e


def run(*, root: Path = ROOT, http=None, only: str | None = None, do_notify: bool = True,
        workers: int = 8, verbose: bool = True) -> dict:
    cfg = load_yaml(root / "config.yaml")
    companies = load_yaml(root / "companies.yaml")["companies"]
    if only:
        companies = [c for c in companies if only.lower() in c["name"].lower()]
    unknown = [c["name"] for c in companies if c.get("ats") not in ADAPTERS]
    if unknown:
        raise SystemExit(f"Unknown ats for: {unknown}. Use one of {sorted(ADAPTERS)}")

    http = http or Http()
    store = Store(root / "data")
    ts = now_iso()
    all_new: list[Job] = []
    newly_broken: list[str] = []
    fetched_total = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch_one, c, http) for c in companies]
        for fut in as_completed(futures):
            c, raw, err = fut.result()
            name = c["name"]
            if err is not None:
                kind = ("not_found" if isinstance(err, BoardNotFound)
                        else "rate_limited" if isinstance(err, RateLimited) else "error")
                store.record_health(name, c["ats"], ts, ok=False, error=str(err), kind=kind)
                # Alert once, and only when it's persistently broken: a single timeout or a
                # Workday rate limit fixes itself by the next run.
                if kind != "rate_limited" and store.health[name]["failures"] == ALERT_AFTER_FAILURES:
                    newly_broken.append(name)
                if verbose:
                    print(f"  ✗ {name:<14} {kind}: {str(err)[:90]}")
                continue

            matched, same = [], set()
            for r, v, jid in enrich_and_classify(c, raw, cfg, store, http, ts, verbose):
                # big companies often post one role several times (one per team/requisition)
                key = (r.title.strip().lower(), v.location.lower())
                if key in same:
                    continue
                same.add(key)
                matched.append(Job(
                    id=jid, company=name,
                    title=r.title, url=r.url, location=v.location, level=v.level,
                    skills=v.skills, score=v.score, posted_at=r.posted_at,
                    first_seen=ts, last_seen=ts, years=v.years, remote=v.remote))
            new = store.sync_company(name, matched, ts)
            all_new.extend(new)
            fetched_total += len(raw)
            store.record_health(name, c["ats"], ts, ok=True, fetched=len(raw), matched=len(matched))
            if verbose:
                print(f"  ✓ {name:<14} {len(raw):>4} jobs → {len(matched):>3} match, {len(new):>3} new")

    store.prune(cfg.get("keep_closed_days", 21))
    store.prune_details(days=30)
    all_new.sort(key=lambda j: newest_first(j.posted_at, j.score))
    open_count = sum(1 for j in store.jobs.values() if j["status"] == "open")
    failing = sorted(n for n, h in store.health.items() if h.get("status") in ("error", "not_found"))
    stats = (f"{len(companies)} boards · {fetched_total} postings scanned · "
             f"{open_count} open matches · {len(all_new)} new · {len(failing)} failing")
    store.runs.append({"at": ts, "new": len(all_new), "open": open_count,
                       "scanned": fetched_total, "failing": len(failing)})
    store.save()
    render.build(root, store)

    sent = []
    if do_notify:
        sent = notify.send_all(all_new, newly_broken, os.getenv("DASHBOARD_URL", ""), cfg, stats)
    if verbose:
        print("\n" + stats + (f" · alerted via {', '.join(sent)}" if sent else ""))
    return {"new": all_new, "open": open_count, "failing": failing, "stats": stats, "sent": sent}
