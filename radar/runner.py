from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from . import notify, render
from .classify import classify
from .http import BoardNotFound, Http
from .models import Job, newest_first
from .sources import ADAPTERS
from .store import Store, now_iso

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def company_key(c: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-")


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
                kind = "not_found" if isinstance(err, BoardNotFound) else "error"
                store.record_health(name, c["ats"], ts, ok=False, error=str(err), kind=kind)
                if store.health[name]["failures"] == 1:   # alert once, not every run
                    newly_broken.append(name)
                if verbose:
                    print(f"  ✗ {name:<14} {kind}: {str(err)[:90]}")
                continue

            matched = []
            for r in raw:
                v = classify(r, cfg)
                if not v.ok:
                    continue
                matched.append(Job(
                    id=f"{c['ats']}:{company_key(c)}:{r.source_id}", company=name,
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
