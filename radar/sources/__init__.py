"""ATS adapters. Each module exposes `fetch(company: dict, http) -> list[RawJob]`
and a pure `parse(payload, company) -> list[RawJob]` used by the tests."""
from . import greenhouse, lever, ashby, smartrecruiters, workday, amazon, microsoft, google, oracle_hcm

ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
    "amazon": amazon,
    "microsoft": microsoft,      # Eightfold "pcsx" careers API
    "google": google,
    "oracle_hcm": oracle_hcm,    # Oracle Recruiting Cloud (JPMorgan Chase, …)
}
