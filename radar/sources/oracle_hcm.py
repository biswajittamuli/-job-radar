"""Oracle Recruiting Cloud (careers sites at <tenant>.fa.<region>.oraclecloud.com), used by
JPMorgan Chase and many other large employers.

  host:        jpmc.fa.oraclecloud.com
  site:        CX_1001                      (the siteNumber in the careers URL)
  location_id: 300000000289360              (India; from the site's location filter)
"""
from ..models import RawJob
from ..text import strip_html

PAGE = 25
MAX_PAGES = 20


def _api(c, res):
    return f"https://{c['host']}/hcmRestApi/resources/latest/{res}"


def fetch(company, http):
    jobs, offset = [], 0
    for _ in range(MAX_PAGES):
        finder = (f"findReqs;siteNumber={company['site']},facetsList=LOCATIONS,limit={PAGE},offset={offset},"
                  f"locationId={company['location_id']},sortBy=POSTING_DATES_DESC")
        data = http.get_json(_api(company, "recruitingCEJobRequisitions"), onlyData="true",
                             expand="requisitionList.secondaryLocations", finder=finder)
        item = (data.get("items") or [{}])[0]
        page = parse(item, company)
        jobs.extend(page)
        offset += PAGE
        if not page or offset >= item.get("TotalJobsCount", 0):
            break
    return jobs


def parse(item, company):
    out = []
    for r in item.get("requisitionList") or []:
        locs = [r.get("PrimaryLocation")] + [s.get("Name") for s in r.get("secondaryLocations") or []]
        out.append(RawJob(
            source_id=str(r["Id"]),
            title=(r.get("Title") or "").strip(),
            url=f"https://{company['host']}/hcmUI/CandidateExperience/en/sites/{company['site']}/job/{r['Id']}",
            locations=[l for l in locs if l],
            posted_at=(r.get("PostedDate") or "")[:10] or None,
            # The list only has a short summary, never the qualifications, so leave this empty:
            # the runner then fetches the full posting (describe) for jobs that pass the pre-check.
            description="",
            remote=(r.get("WorkplaceTypeCode") == "ORA_REMOTE") or None,
            team=r.get("JobFamily") or "",
        ))
    return out


def describe(company, job, http):
    data = http.get_json(_api(company, "recruitingCEJobRequisitionDetails"), expand="all", onlyData="true",
                         finder=f'ById;Id="{job.source_id}",siteNumber={company["site"]}')
    d = (data.get("items") or [{}])[0]
    job.description = " ".join(strip_html(d.get(k)) for k in ("ExternalQualificationsStr", "ExternalResponsibilitiesStr",
                                                                 "ExternalDescriptionStr") if d.get(k))
    return job
