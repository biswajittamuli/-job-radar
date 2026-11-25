# 🛰 Job Radar

Tracks company career pages for **fresher-friendly CSE roles in India and remote**, sorts
them by skill (Backend, AI/ML, DevOps/Cloud, Data, …), and pings you on Telegram when
something new opens up. It runs free on GitHub Actions four times a day, and the dashboard
is hosted on GitHub Pages.

## Why this works where "AI reads the careers page" doesn't

Most career pages are JavaScript apps. When a bot loads them it sees an empty shell, so
an AI that browses them misses jobs, invents jobs, or quietly fails. Behind almost every
careers page is an **ATS** (Greenhouse, Lever, Ashby, Workday, SmartRecruiters) with a
public JSON API that the page itself calls. Job Radar reads those APIs directly:

| | AI browsing | Job Radar |
|---|---|---|
| Sees every posting | Sometimes | Yes, exact feed from the ATS |
| Knows what's *new* vs already seen | No memory | Diffs against `data/jobs.json` |
| Knows a job *closed* | No | Marks it closed when it leaves the feed |
| Tells you when a source breaks | Fails silently | "Board health" table + one-time alert |
| Explains why a job was filtered | No | `python -m radar explain "<title>"` |
| Cost | Tokens per run | Free |

## Setup (about 10 minutes)

1. **Create a repo.** On GitHub, create a new **public** repo called `job-radar`. Pages is
   free on public repos; the data is just public job listings. Then:
   ```bash
   unzip job-radar.zip && cd job-radar
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<you>/job-radar.git
   git push -u origin main
   ```
2. **Allow the workflow to commit.** Go to Settings → Actions → General → Workflow
   permissions and select **Read and write**.
3. **Turn on the dashboard.** Go to Settings → Pages → Source: *Deploy from a branch* →
   `main` / `/docs`. The dashboard will be at `https://<you>.github.io/job-radar/`.
4. **Set up Telegram alerts** (recommended):
   - In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
   - Send any message to your new bot, then open
     `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
   - In the repo, go to Settings → Secrets and variables → Actions and add the secrets
     `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
   - Check it: Actions → *Test Telegram* → **Run workflow** (or `python -m radar test-notify`
     locally). It sends a test message, or fails with Telegram's exact error. Paste secrets
     without a trailing newline; Job Radar strips one now, but it used to cause a 404.
5. **First run.** Go to Actions → *Job Radar* → **Run workflow**. Once it finishes, open the
   dashboard. After that it runs by itself at **07:05, 11:05, 15:05 and 19:05 IST**
   (change the `cron` line in `.github/workflows/radar.yml`).

> The first run treats every matching job as "new", so you'll get one long message.
> `notify.max_items` in `config.yaml` caps it at 40.

**Email instead of / as well as Telegram:** add `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`,
`SMTP_USER=<you>@gmail.com`, `SMTP_PASS=<Gmail app password>` and `EMAIL_TO` as secrets.

## Which companies are tracked

`companies.yaml` has about 165 companies, each checked against its live careers site:

- **Indian startups and product companies**: Swiggy, PhonePe, Razorpay, Paytm, Meesho,
  CRED, Groww, Zeta, Freshworks, Cashfree, MoEngage, CleverTap, Slice, Acko, Jupiter,
  LambdaTest, Teachmint, Tekion, InMobi, Hevo …
- **Big tech and GCCs**: Microsoft, Google, Amazon, Uber, Atlassian, Qualcomm, NVIDIA,
  Micron, Citi, JPMorgan Chase, Morgan Stanley, American Express, PayPal, Oracle,
  Texas Instruments, Honeywell, Salesforce, Adobe …
- **Service companies**: Accenture, Wipro, Capgemini.

Supported careers systems (`ats:` in `companies.yaml`): greenhouse, lever, ashby,
smartrecruiters, workday, eightfold, oracle_hcm, keka, kula, successfactors, plus
company-specific adapters for amazon, microsoft, google, uber, atlassian and capgemini.

Not covered, because they have no public job API a script can read: Flipkart (TurboHire),
Walmart, TCS, Infosys, Cognizant, Tech Mahindra, HCLTech, and startups on Darwinbox
(Unacademy, PW, Spinny, PharmEasy), which sits behind a bot check. Most service companies
hire freshers through campus and national tests (TCS NQT, InfyTQ) rather than job posts.

Only software-development roles are kept: titles with words like *support*, *operations*,
*data centre*, *sales*, *customer* or *scientist* are skipped (`exclude_titles` in
`config.yaml`). If a company posts the same role twice, it's shown once.

Workday boards are read one at a time, slowly, because Workday rate-limits GitHub's
servers. A rate-limited board shows "Rate limited, retrying" under Board health and is
not reported as broken. Other boards alert you only after failing 3 runs in a row.

## Adding companies

```bash
pip install -r requirements.txt
python -m radar detect https://www.postman.com/company/careers/ https://razorpay.com/jobs/
```
`detect` finds which ATS a careers page uses and prints the block to paste into
`companies.yaml`. Then check that it works:
```bash
python -m radar run --only postman --no-notify
```

If `detect` finds nothing, the company runs its own site, as Google, Microsoft, Flipkart
and most service companies do. Those need a custom adapter in `radar/sources/`. Use
`amazon.py` as the example (about 50 lines): open the careers page, watch DevTools →
Network → Fetch/XHR, and you'll usually find a JSON endpoint to copy.

## Tuning what counts as "for me" (`config.yaml`)

- `level.mode: entry` (the default) is **strict fresher**: a job needs a fresher signal in
  its title (new grad, SDE-1, Associate, Trainee, "2026 batch") or its **description**
  ("freshers", "0–1 years", "entry level", "recent graduates", "1+ years"). The full
  description is read for every board, including Workday and SmartRecruiters, whose
  lists don't include it (it's fetched once per job and cached in `data/details.json`).
  `open` also lets in tech roles that state no level at all. That's more noise.
- `level.max_years: 1` drops a job if its description asks for more than 1 year.
- `exclude_titles: [scientist, …]` skips titles containing those words.
- `freshness.max_posted_age_days: 90` drops jobs posted more than 90 days ago (startups keep
  fresher openings up for weeks; alerts still fire only once per job). Jobs whose
  board gives no posting date are kept. Workday's "Posted 30+ Days Ago" counts as 30.
- `notify.skills: [backend, ai_ml]` limits alerts to those buckets. The dashboard
  still shows everything.
- `skills:` holds the keyword buckets. Edit them freely.

Debug a filter decision:
```bash
python -m radar explain "Software Engineer II" --loc "Bengaluru"
# FAIL senior title (Engineer II)
python -m radar explain "Backend Engineer" --desc "1+ years of experience with FastAPI"
# PASS match
#   level=entry skills=['backend'] years=1 score=70 loc=Bengaluru, India
```

## Dashboard

You can search, filter by level, skill, recency, remote and company, and sort by match
score or newest. **Applied** and **Hide** marks are saved in your browser. The
**Board health** table at the bottom shows any company whose slug is wrong or whose
ATS changed. It opens automatically when something is failing.

## Layout

```
companies.yaml        boards to watch
config.yaml           filters, skill buckets, alert settings
radar/sources/        one adapter per ATS (greenhouse, lever, ashby, workday, smartrecruiters, amazon)
radar/classify.py     tech-role / seniority / location / years / skill rules
radar/store.py        new / seen / closed diff → data/*.json
radar/notify.py       Telegram, email, GitHub run summary
radar/dashboard.html  dashboard template → docs/index.html
tests/                offline tests (pytest -q)
```
