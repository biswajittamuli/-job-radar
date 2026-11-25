"""ATS adapters. Each module exposes `fetch(company: dict, http) -> list[RawJob]`
and a pure `parse(payload, company) -> list[RawJob]` used by the tests."""
from . import greenhouse, lever, ashby, smartrecruiters, workday, amazon

ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
    "amazon": amazon,
}
