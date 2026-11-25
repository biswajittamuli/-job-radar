"""ATS adapters. Each module exposes `fetch(company: dict, http) -> list[RawJob]`
and a pure `parse(payload, company) -> list[RawJob]` used by the tests."""
from . import greenhouse, lever, ashby, smartrecruiters, workday, amazon, microsoft, google, oracle_hcm, keka, kula, uber, atlassian, successfactors, capgemini

ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
    "amazon": amazon,
    "microsoft": microsoft,      # Eightfold "pcsx" careers API (Microsoft's defaults)
    "eightfold": microsoft,      # same API for other Eightfold customers: host + domain
    "google": google,
    "oracle_hcm": oracle_hcm,    # Oracle Recruiting Cloud (JPMorgan Chase, …)
    "keka": keka,                # Keka Hire careers pages (Indian startups)
    "kula": kula,                # careers.kula.ai (Indian startups)
    "uber": uber,
    "atlassian": atlassian,
    "successfactors": successfactors,   # SAP SuccessFactors career sites (Wipro, HCLTech, …)
    "capgemini": capgemini,
}
