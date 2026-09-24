# Campus AutoGTM

Agentic GTM engine for education and training providers. It discovers colleges,
scores fit with Jev (TypeSafe System One), and writes qualified opportunities
into the BrainOpsHub CRM database.

## Pipeline

```
Campaign -> Prospector -> preflight -> Jev Scoring -> threshold -> ingest_lead()
                          (skip what   (only the      (campaign     one atomic,
                           the CRM      unseen)        min_fit_      idempotent
                           already has)                score)        batch)
```

Preflight runs before scoring because Jev is the cost and the database is
nearly free: re-running a campaign makes zero Jev calls.

An opportunity is created at stage `enquiry`, with `probability` carrying the
Jev fit score, and `notes` carrying the model's one-line rationale.

## Status

| Stage | State |
|---|---|
| Campaign definition | Working (in-process store, not persisted) |
| Prospector / signal discovery | **Stub** — returns one fixed fake lead; AICTE ingest not built |
| Jev scoring | Working |
| Qualification threshold | Working, per campaign |
| Persistence to BrainOpsHub | Working — atomic, idempotent, least privilege |
| Preflight deduplication | Working |
| Win/loss feedback -> ICP recalibration | Not built |

Campaign targeting is applied at discovery: `segment_states`, `college_types`
and `departments` filter the roster before anything is scored. Matching is on
word sets, so "Engineering Autonomous" finds a college typed "Autonomous
Engineering College"; an empty criterion means no constraint.

The pipeline is live end to end. Point `PROSPECTOR_FILE` at a roster and a
campaign produces real CRM opportunities.

Discovery deliberately does **not** scrape the AICTE dashboard. That is an
AngularJS front end over undocumented internal endpoints with no published
contract and no robots policy; a scraper on it would break silently on any
redeploy. The file source consumes AICTE exports directly, and the datagov
source uses the documented key-authenticated resource API.

## Quick start

```bash
pip install -r requirements.txt
cp Infra/env.example Infra/.env     # then edit it
set -a && . ./Infra/.env && set +a  # PowerShell: use $env: assignments
uvicorn app.main:app --reload
```

```bash
curl -X POST localhost:8000/campaigns/ -H 'content-type: application/json' -d '{
  "name": "Telangana AI Hackathon Sweep",
  "segment_states": ["Telangana"],
  "college_types": ["Engineering Autonomous"],
  "departments": ["CSE"],
  "objective": "Book 10 hackathons this quarter",
  "target_meetings_per_week": 5,
  "opportunity_type": "hackathon",
  "min_fit_score": 75
}'

curl -X POST localhost:8000/campaigns/1/run
```

`GET /health/` reports which credentials are present without revealing them.

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `TYPESAFE_API_KEY` | to score | Jev System One API key |
| `SUPABASE_URL` | to persist | BrainOpsHub project URL |
| `SUPABASE_ANON_KEY` | to persist | Sent as the `apikey` header |
| `SUPABASE_JWT_SECRET` | to persist | Signs a short-lived `autogtm_writer` token |
| `CRM_ROLE` | no | Defaults to `autogtm_writer` |
| `PROSPECTOR_SOURCE` | no | `file`, `datagov` or `stub` (default) |
| `PROSPECTOR_FILE` | for `file` | Path to a CSV/JSON college roster |
| `DATAGOV_RESOURCE_ID` / `DATAGOV_API_KEY` | for `datagov` | data.gov.in resource |
| `MIN_FIT_SCORE` | no | Default qualification threshold (70) |
| `JEV_API_URL` / `JEV_TIMEOUT_SECONDS` / `JEV_MAX_ATTEMPTS` | no | Transport tuning |

Nothing is read at import time. With no credentials the app still starts and
`/health/` still answers — so a misconfigured deploy is distinguishable from a
dead one. Without Supabase the pipeline scores and returns leads without
writing them.

**This repository is public.** `Infra/.env` is gitignored; never commit a real
key, and never log the service role key.

## Design notes

- **Failure is per lead.** One bad Jev response marks that lead `failed` and
  the run continues. Scores already paid for are never discarded.
- **Transport retries, shape does not.** 429/5xx back off and retry; a 4xx or
  an unrecognised body fails immediately.
- **No service role key.** This service signs a short-lived token for
  `autogtm_writer`, which can execute two functions and read no table. A bug
  here cannot reach payouts, contacts or anything else.
- **The database owns the schema.** `ingest_lead()` is atomic per lead,
  idempotent on `(campaign_ref, external_key)`, and fixes stage and source
  itself: the agent may open a deal, never advance or disguise one.
- **Campaigns live in memory.** They do not survive a restart and are not
  shared across workers. Single worker only, until they get a table.

## Tests

```bash
python -m pytest tests -q
```

51 tests, no credentials and no database required.
