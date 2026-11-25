from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Job


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    """jobs.json (matched jobs), health.json (per-board status), runs.json (history).
    Plain JSON so every change is a readable git diff."""

    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, dict] = self._load("jobs.json", {})
        self.health: dict[str, dict] = self._load("health.json", {})
        self.runs: list[dict] = self._load("runs.json", [])
        # full descriptions fetched for boards whose list API omits them (Workday, SmartRecruiters)
        self.details: dict[str, dict] = self._load("details.json", {})

    def _load(self, name, default):
        p = self.dir / name
        if p.exists():
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError:
                return default
        return default

    def save(self):
        for name, obj in (("jobs.json", self.jobs), ("health.json", self.health),
                          ("runs.json", self.runs[-90:]), ("details.json", self.details)):
            (self.dir / name).write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False))

    # ── jobs ─────────────────────────────────────────────────────────────────
    def sync_company(self, company: str, matched: list[Job], ts: str) -> list[Job]:
        """Merge one company's current matches. Returns the jobs that are new."""
        new = []
        seen_ids = set()
        for j in matched:
            seen_ids.add(j.id)
            old = self.jobs.get(j.id)
            if old is None:
                j.first_seen = j.last_seen = ts
                self.jobs[j.id] = j.to_dict()
                new.append(j)
            else:
                d = j.to_dict()
                d["first_seen"] = old["first_seen"]
                d["last_seen"] = ts
                d["status"], d["closed_at"] = "open", None
                self.jobs[j.id] = d
        # anything of this company we had open but didn't see now has closed
        for jid, d in self.jobs.items():
            if d["company"] == company and d["status"] == "open" and jid not in seen_ids:
                d["status"], d["closed_at"] = "closed", ts
        return new

    def prune(self, keep_closed_days: int):
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_closed_days)
        self.jobs = {
            k: v for k, v in self.jobs.items()
            if v["status"] == "open" or datetime.fromisoformat(v["closed_at"]) > cutoff
        }

    def prune_details(self, days: int):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        self.details = {k: v for k, v in self.details.items()
                        if datetime.fromisoformat(v.get("seen", "1970-01-01T00:00:00+00:00")) > cutoff}

    # ── health ───────────────────────────────────────────────────────────────
    def record_health(self, company: str, ats: str, ts: str, *, ok: bool, fetched=0,
                      matched=0, error: str = "", kind: str = ""):
        h = self.health.get(company, {})
        h.update(ats=ats, last_run=ts, fetched=fetched if ok else h.get("fetched", 0),
                 matched=matched if ok else h.get("matched", 0))
        if ok:
            h.update(status="ok", error="", last_ok=ts, failures=0)
            if fetched == 0:
                h["status"] = "empty"
        else:
            h["failures"] = h.get("failures", 0) + 1
            h.update(status=kind or "error", error=error[:300])
        self.health[company] = h
