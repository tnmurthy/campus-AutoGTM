# Campus AutoGTM

Agentic GTM engine for education and training providers. It discovers colleges,
scores fit with Jev (TypeSafe System One), and writes qualified opportunities
into the BrainOpsHub CRM database.

## Pipeline

```
Campaign  ->  Prospector  ->  ICP state  ->  Jev Scoring  ->  threshold  ->  Postgres
                                            (fit 0-100,      (campaign      colleges
                                             send_now,        min_fit_       contacts
                                             rationale)       score)         opportunities
```

An opportunity is created at stage `enquiry`, with `probability` carrying the
Jev fit score, and `notes` carrying the model's one-line rationale.

## Status

| Stage | State |
|---|---|
| Campaign definition | Working (in-process store, not persisted) |
| Prospector / signal discovery | **Stub** — returns one fixed fake lead; AICTE ingest not built |
| Jev scoring | Working |
| Qualification threshold | Working, per campaign |
| Persistence to BrainOpsHub | Working |
| Win/loss feedback -> ICP recalibration | Not built |

Replacing `agents/prospector_agent.discover_leads` is the only remaining work
to make the pipeline live; everything downstream of it is real.

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
| `SUPABASE_SERVICE_ROLE_KEY` | to persist | **Bypasses RLS.** Server-side only |
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
- **Colleges are matched by name.** `colleges.name` has no unique constraint
  upstream, so this is lookup-then-insert, not a true upsert. Run one worker
  until `unique (colleges.name)` exists.
- **Campaigns live in memory.** They do not survive a restart and are not
  shared across workers. Single worker only, until they get a table.

## Tests

```bash
python -m pytest tests -q
```

25 tests, no credentials and no database required.
