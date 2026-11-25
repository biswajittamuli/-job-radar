"""Build docs/index.html: one self-contained page with the data embedded,
so it works on GitHub Pages and also when opened straight from disk."""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("dashboard.html")


def build(root: Path, store) -> Path:
    jobs = sorted(store.jobs.values(), key=lambda j: (j["status"] != "open", -j["score"]))
    payload = {
        "generated_at": store.runs[-1]["at"] if store.runs else None,
        "jobs": jobs,
        "health": store.health,
        "runs": store.runs[-30:],
    }
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out = Path(root) / "docs" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.read_text().replace("__RADAR_DATA__", blob))
    (out.parent / ".nojekyll").touch()
    return out
