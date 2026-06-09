# Evaluation

The included pytest suite covers the core behavior expected of the control tower:

- ticket classification
- SLA risk scoring and escalation routing
- KB retrieval
- retry exhaustion and human review
- approval creation, approval, and rejection
- approval dispatch writing the integration outbox
- trace output for required workflow nodes
- deterministic failure-drill retry timeline
- SLA breach simulator ordering and required queue fields
- incident brief contents for leadership and engineering handoff
- playbook recommendation ranking and match reasons
- remediation checklist Markdown/JSON export contents and local file creation
- ops analytics snapshot fields and top-risk recommendations
- weekly review Markdown/JSON export contents and local file creation
- customer health scoring by account
- account brief Markdown/JSON export contents and local file creation
- SLO budget metric fields and pass/warn/fail status shape
- optimization report Markdown/JSON export contents and local file creation
- demo scenario runner artifact paths, endpoint list, and summary metrics
- demo evidence pack Markdown/JSON contents and local file creation
- Runbook QA pass/fail scoring, missing-section detection, linked artifact paths, and recommended fixes
- operator readiness pack Markdown/JSON contents and local file creation under `data/operator_packs/`
- Replay Lab changed-decision detection, degraded/failing adapter scenarios, fallback/sample endpoint behavior, and report export under `data/replay_reports/`
- Policy Guardrail simulation for low confidence, SLA pressure, enterprise/VIP tier, external vs internal actions, adapter health, replay risk, missing/conflicting KB context, fallback behavior, and pack export under `data/policy_packs/`
- Customer Impact Timeline ordering, latest/sample fallback, policy/replay annotations, endpoint errors, and Executive Incident Narrative export under `data/incident_narratives/`
- Leadership Scorecard calculation, risk flags, endpoint behavior, and review pack export under `data/leadership_reviews/`
- Knowledge Quality Auditor coverage score, missing citation detection, conflict detection, workflow retrieval evidence, endpoint behavior, and KB refresh plan export under `data/kb_refresh_plans/`
- Smoke Matrix endpoint shape and Launch Checklist Markdown/JSON export under `data/launch_checklists/`
- Portfolio Evidence Index skill coverage and Interview Pack Markdown/JSON export under `data/portfolio_packs/`
- Release Candidate quality gate coverage and GitHub Publish Pack Markdown/JSON export under `data/release_packs/`
- Reviewer Quickstart endpoint shape and Walkthrough Pack Markdown/JSON export under `data/reviewer_packs/`
- CI Doctor checks for CI/docs/tests/env/Docker/dependencies/local-mock notes plus redacted secret scan summary, and Audit Pack Markdown/JSON export under `data/audit_packs/`
- GitHub Push Readiness and Branch Hygiene checks plus Push Plan Markdown/JSON export under `data/git_packs/`
- Runtime Demo readiness endpoint, source-only `scripts/runtime_check.py`, dashboard tab wiring, and Runtime Demo Server Pack export under `data/runtime_packs/`
- Scenario Dataset catalog coverage and Eval Coverage Pack export under `data/scenario_packs/`
- Dashboard Smoke source wiring for Streamlit views, endpoint references, generated artifact tabs, and UI Verification Pack export under `data/ui_verification/`
- metrics aggregation
- auth behavior
- health endpoint

## Manual Eval Ideas

Use `sample_data/tickets.json` as seed cases:

- Enterprise SSO outage should classify as authentication or incident, score high SLA risk, draft engineering escalation, and pause for approval.
- Billing invoice question should classify as billing, retrieve billing KB, draft customer reply, and pause for approval.
- API/webhook latency should retrieve API KB and draft an engineering escalation for enterprise impact.
- SSO outage, webhook regression, billing dispute, privacy export, and API key rotation tickets should rank the matching local playbook near the top with concrete match reasons.

## Scenario Dataset Eval

The richer Scenario Dataset lives in `sample_data/scenarios.json` and covers security, billing, data export/privacy, outage, webhook/API, enterprise onboarding, renewal risk, low-confidence ambiguity, and a deterministic KB failure path.

```bash
curl http://localhost:8000/scenarios/catalog \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/scenarios/eval-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- `GET /scenarios/catalog` returns scenario metadata, expected outcomes, and scenario coverage summary.
- `POST /scenarios/eval-pack` writes Markdown and JSON under `data/scenario_packs/`.
- the pack reports classification accuracy, SLA routing, approval pause coverage, escalation coverage, low-confidence review coverage, failure/tool-retry coverage, and gaps/warnings.
- one forced KB failure fixture proves retry exhaustion and human review without calling external systems.

## Tool Failure Eval

Create a ticket whose body contains `force-kb-failure`. The fake KB adapter will fail every search attempt. The run should record failed tool calls, set `failure_state`, and remain in human review/approval rather than silently drafting with unsupported context.

The faster packaged path is:

```bash
curl -X POST http://localhost:8000/drills/tool-failure \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- three failed `internal_kb.search` trace events when the default retry count is `3`
- final run status `awaiting_approval`
- QA finding `Knowledge retrieval failed after retries.`
- a pending approval for human review
- `/metrics/agent-performance` increments `failure_drill_count` and `tool_failure_count`

## Outbox Eval

Approve an analyzed enterprise escalation run, then call `GET /integrations/outbox`. A complete high-risk approval should record local dispatches for `customer_reply`, `zendesk_update`, `engineering_escalation`, `jira_issue`, and `slack_alert`, each with destination, payload, status, run ID, trace ID, and ticket ID.

## SLA Simulator Eval

Call:

```bash
curl -X POST http://localhost:8000/drills/sla-breach-simulation \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- four queue rows ordered as `breached`, `critical`, `warning`, then `watch`
- each row has `ticket_id`, `customer_tier`, `minutes_to_sla`, `risk_level`, `recommended_action`, `run_id`, and `approval_id`
- each run pauses for approval with deterministic local fake-provider behavior

## Incident Brief Eval

Export a brief for one simulator `run_id`:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/incident-brief \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under the ignored local briefs folder
- brief includes customer impact, classification, SLA risk, KB citations, customer reply draft, engineering escalation draft, approval status, trace summary, outbox status, and recommended next steps
- pending approvals show `pending_approval_no_dispatch`; approved runs show dispatched outbox events

## Playbook and Remediation Eval

Recommend playbooks for a stored ticket:

```bash
curl -X POST http://localhost:8000/playbooks/recommend \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"ticket_id": "{ticket_id}", "top_n": 3}'
```

Expected evidence:

- SSO outage tickets rank `pb_sso_outage` first
- webhook 5xx/regression tickets rank `pb_webhook_regression` first
- each recommendation includes confidence, match reasons, checklist steps, owner roles, escalation policy, and customer update template
- analyzed runs include `state.playbook_recommendations`

Export a remediation checklist for a run:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/remediation-checklist \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under the ignored local checklists folder
- export includes ticket, classification, SLA risk, selected playbook, checklist, owners, approval status, and next update template
- checklist steps have owner-role assignments and pending status

## Ops Analytics Eval

After running the tool-failure drill, SLA simulator, at least one incident brief export, and at least one approval, call:

```bash
curl http://localhost:8000/analytics/ops-snapshot \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- counts exist for ticket category, SLA risk, final action, approval status, outbox destination, outbox action, and failure type
- failure type includes `knowledge_retrieval_retry_exhausted` after the failure drill
- averages include latency per run, tokens per run, and cost per run
- top risky tickets include ticket/run IDs and recommended actions
- snapshot includes SLA queue highlights, failure drill summary, outbox dispatch summary, incident brief paths, and recommended operational actions

## Weekly Review Eval

Call:

```bash
curl -X POST http://localhost:8000/analytics/weekly-review \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under the ignored local reports folder
- report includes summary metrics, SLA queue highlights, failure drill summary, outbox dispatch summary, incident brief links or paths when present, top risky tickets, and next actions
- returned `markdown_path` and `json_path` point to local files that exist

## SLO Budget and Optimization Eval

After running at least one failure drill, one SLA simulator run, and one approval, call:

```bash
curl http://localhost:8000/ops/slo-budget \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- metrics exist for `agent_workflow_latency_ms`, `token_usage_per_run`, `cost_usd_per_run`, `failure_count`, `pending_approvals`, and `outbox_dispatch_delay_minutes`
- each metric includes deterministic thresholds, current value, `pass`/`warn`/`fail` status, and a recommendation
- the overall status reflects the worst individual SLO status

Export an optimization report:

```bash
curl -X POST http://localhost:8000/ops/optimization-report \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under the ignored local optimization reports folder
- report includes SLO statuses, top slow nodes, high-token nodes, failure hotspots, approval bottlenecks, and recommended fixes
- returned `markdown_path` and `json_path` point to local files that exist

## Customer Health and Account Brief Eval

After running at least one analyzed high-SLA-risk ticket for an account, call:

```bash
curl http://localhost:8000/customers/health \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- each account row includes ticket counts, open/pending/escalated counts, high-SLA-risk count, recent failure count, pending approval count, recommended playbook count, `health_score`, `risk_level`, and `recommended_action`
- high-SLA-risk or pending-approval accounts score below 100 and rank ahead of healthy accounts
- scores are deterministic from local state and do not call external systems

Export an account brief:

```bash
curl -X POST http://localhost:8000/customers/northstar-health/account-brief \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under the ignored local account brief folder
- export includes customer health, active tickets, recent runs, recommended playbooks, pending approvals, outbox summary, and next actions
- returned `markdown_path` and `json_path` point to local files that exist

## Interview Scenario and Evidence Pack Eval

Run the complete scenario:

```bash
curl -X POST http://localhost:8000/demo/scenario-run \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response mode is `local-deterministic`
- primary run completes after approval and records outbox dispatches
- summary metrics include ticket/run/trace IDs, trace event count, approval status, failure-drill attempts, SLA simulator ticket count, SLO status, optimization fix count, and replay risk score
- artifact paths exist for remediation checklist, incident brief, weekly review, account brief, optimization report, Replay Lab report, and executive incident narrative
- endpoint list covers ticket analysis, trace, approval, outbox, failure drill, SLA simulation, incident brief, weekly review, checklist, customer health, account brief, SLO, optimization, Replay Lab, metrics, and audit

Export the pack:

```bash
curl -X POST http://localhost:8000/demo/evidence-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/demo_packs/`
- pack includes summary, generated artifact paths, API endpoints exercised, key metrics, summary metrics, links, and interview talking points
- JSON links the evidence pack path plus all scenario artifact paths
- Markdown includes `## API Endpoints Exercised`, `## Key Metrics`, and `## Interview Talking Points`

One-command local version:

```bash
python scripts/demo_run.py
```

Expected evidence:

- output includes operator readiness score/status
- output includes the exported operator readiness Markdown and JSON paths
- output includes replay risk score, recommended action, and Replay Lab report path
- output includes policy decision, required approval type, and Policy Guardrail Pack path
- output includes leadership readiness score/status and Leadership Review Pack path
- output includes KB readiness score/status and KB refresh plan path
- output includes launch readiness and the launch checklist Markdown/JSON paths
- output includes portfolio evidence score/count and the Interview Pack Markdown/JSON paths
- output includes release gate status/score and the Publish Pack Markdown/JSON paths
- output includes reviewer quickstart status/proof count and the Walkthrough Pack Markdown/JSON paths
- output includes CI Doctor status/score, secret scan finding count, and Audit Pack Markdown/JSON paths
- output includes Dashboard Smoke status/check count and UI Verification Pack Markdown/JSON paths
- output includes incident impact status and Executive Incident Narrative path
- generated files are under `data/operator_packs/`

## Dashboard Smoke and UI Verification Eval

Run the source smoke script without launching Streamlit or a browser:

```powershell
.\.venv\Scripts\python.exe scripts\dashboard_smoke.py
```

Expected evidence:

- output starts with `Dashboard Smoke: PASS`
- output prints total, passed, and failed check counts
- checked views include `UI Verification`, `Launch Checklist`, `Reviewer Quickstart`, and `Artifact Inventory`
- checked endpoints include `GET /ui/dashboard-smoke` and `POST /ui/verification-pack`
- no external service, browser, or Streamlit process is launched

Inspect the API shape and export the UI Verification Pack:

```bash
curl http://localhost:8000/ui/dashboard-smoke \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/ui/verification-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- `GET /ui/dashboard-smoke` returns status `pass`, expected views, endpoint references, generated artifact tabs, local run commands, and limitations
- `POST /ui/verification-pack` writes Markdown and JSON files under `data/ui_verification/`
- pack includes Dashboard Smoke results, the Streamlit run command, reviewer checklist, screenshot placeholders, troubleshooting, and limitations
- Markdown includes `Dashboard Smoke`, `## Screenshot Placeholders`, and `## Limitations`

Required local UI verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\dashboard_smoke.py
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "ui/dashboard-smoke|ui/verification-pack|Dashboard Smoke|UI Verification|ui_verification|dashboard smoke" app dashboard docs README.md tests scripts
Get-ChildItem -Recurse -File data\ui_verification -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

## Runtime Demo Server Pack Eval

Run the source-only runtime readiness script without launching FastAPI, Streamlit, a browser, or external services:

```powershell
.\.venv\Scripts\python.exe scripts\runtime_check.py
```

Expected evidence:

- output starts with `Runtime Demo Readiness:`
- output prints total, passed, warning, and failed check counts
- output lists exact FastAPI, Streamlit, runtime check, and demo run commands
- output lists expected health URLs including `/health` and `/runtime/demo-readiness`
- dependency checks include FastAPI, uvicorn, Streamlit, requests, pytest, and ruff
- port checks are safe/read-only and never stop or kill processes

Inspect the API shape and export the Runtime Demo Server Pack:

```bash
curl http://localhost:8000/runtime/demo-readiness

curl -X POST http://localhost:8000/runtime/demo-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- `GET /runtime/demo-readiness` returns run commands, expected ports, env requirements, dependency checks, file checks, read-only process/port checks, known limitations, and health/smoke URLs
- `POST /runtime/demo-pack` writes Markdown and JSON files under `data/runtime_packs/`
- pack includes start commands, stop commands, health checks, demo flow order, screenshot checklist placeholders, troubleshooting, recruiter explanation, and engineer explanation
- the Streamlit dashboard includes a `Runtime Demo` tab
- one-command demo output includes Runtime Demo readiness status and Runtime Demo Pack Markdown/JSON paths

Required local Runtime Demo verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\dashboard_smoke.py
.\.venv\Scripts\python.exe scripts\runtime_check.py
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "runtime/demo-readiness|runtime/demo-pack|Runtime Demo|runtime_packs|runtime_check|start_demo" app dashboard docs README.md tests scripts
Get-ChildItem -Recurse -File data\runtime_packs -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

## Final Handoff and README Consistency Eval

Inspect the README Consistency final audit:

```bash
curl http://localhost:8000/handoff/final-audit \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response title is `README Consistency Final Audit`
- checks include README endpoint mentions, docs/api coverage, architecture/evaluation/workflow coverage, demo output claims, scripts present, Dashboard Smoke script presence, generated artifact directory docs, and local/mock Azure limitation clarity
- endpoint inventory summary includes `GET /handoff/final-audit` and `POST /handoff/final-pack`
- artifact inventory summary includes `data/final_handoff`
- dashboard smoke summary reports zero failed checks

Export the Final Handoff Pack:

```bash
curl -X POST http://localhost:8000/handoff/final-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/final_handoff/`
- pack includes final audit results, exact clone/run commands, end-to-end verification order, endpoint inventory summary, artifact inventory summary, dashboard smoke summary, recruiter-facing final README blurb, and limitations
- one-command demo output includes final audit status/score and Final Handoff Pack paths

Required local Final Handoff verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\dashboard_smoke.py
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "handoff/final-audit|handoff/final-pack|Final Handoff|final_handoff|README Consistency|final audit" app dashboard docs README.md tests scripts
Get-ChildItem -Recurse -File data\final_handoff -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

This Final Handoff check is local/mock only. It inspects repo files and generated artifact folders without calling GitHub, Azure, OpenAI, Zendesk, Jira, Slack, or external services.

## On-Call Handoff and Customer Communications Eval

Inspect the On-Call Handoff summary:

```bash
curl http://localhost:8000/handoff/on-call-summary \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response title is `On-Call Handoff Summary`
- response includes owners, severity, status, SLA deadline, trace links, approval/guardrail status, customer update drafts, engineering incident ticket summary, risk/gap checklist, and communication readiness
- low-confidence, tool-failure, and high-SLA runs remain approval-bound instead of sending customer updates

Export the Customer Communications Simulation Pack:

```bash
curl -X POST http://localhost:8000/handoff/customer-comms-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/customer_comms_packs/`
- pack includes customer updates, internal handoff, engineering ticket draft, SLA/customer-impact timeline, approval checklist, guardrail status, trace IDs, local proof commands, and limitations
- scenario coverage includes high SLA risk, low-confidence approval pause, tool failure/retry, billing/privacy, and outage/API incident paths from `sample_data/scenarios.json`
- dashboard smoke includes the On-Call Handoff tab and both handoff endpoints

Required local Customer Communications verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\dashboard_smoke.py
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "handoff/on-call-summary|handoff/customer-comms-pack|On-Call Handoff|Customer Communications|customer_comms_packs|communication readiness" app dashboard docs README.md tests scripts sample_data
Get-ChildItem -Recurse -File data\customer_comms_packs -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

This On-Call Handoff check is local/mock only. It creates deterministic draft communications and proof artifacts without dispatching to customers or calling Azure, OpenAI, Zendesk, Jira, Slack, GitHub, or external services.

## Postmortem RCA and Corrective Action Eval

Inspect the Postmortem RCA summary:

```bash
curl http://localhost:8000/incidents/postmortem-summary \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response title is `Postmortem RCA Summary`
- response includes incident summary, severity, timeline, root cause category, contributing factors, impacted customer/account, approval/comms status, trace links, corrective actions, customer follow-up state, recurrence risk, readiness summary, and proof commands
- scenario coverage includes outage/API incident, tool failure/retry, privacy/data export, billing/customer risk, and low-confidence ambiguity requiring human review

Export the Postmortem RCA + Corrective Action Tracking Pack:

```bash
curl -X POST http://localhost:8000/incidents/rca-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/rca_packs/`
- pack includes postmortem narrative, timeline, trace/audit evidence, action owners, due dates, recurrence risk, customer follow-up state, proof commands, and limitations
- dashboard smoke includes the Postmortem RCA tab and both RCA endpoints

Required local Postmortem RCA verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\dashboard_smoke.py
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "incidents/postmortem-summary|incidents/rca-pack|Postmortem RCA|Corrective Action|rca_packs|root cause" app dashboard docs README.md tests scripts sample_data
Get-ChildItem -Recurse -File data\rca_packs -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

This Postmortem RCA check is local/mock only. It classifies RCA paths and writes reviewer artifacts without inspecting production logs, sending customer communications, or calling Azure, OpenAI, Zendesk, Jira, Slack, GitHub, or external services.

## GitHub Push Readiness and Branch Hygiene Eval

Inspect the local git readiness status:

```bash
curl http://localhost:8000/git/readiness \
  -H "x-api-key: demo-control-tower-key"
```

Expected:

- title is `GitHub Push Readiness + Branch Hygiene`
- response includes git repo detection, current branch, tracked/untracked/modified/ignored summary, generated artifact directories, changed source/doc/test/dashboard buckets, suspicious large/generated files, GitHub Actions workflow presence, README final handoff mention, `.env.example`, dirty-worktree guidance, and recommended commit groups
- generated artifact directories include `data/git_packs`
- the endpoint uses read-only local git inspection and does not call GitHub APIs

Export the Branch Hygiene Push Plan:

```bash
curl -X POST http://localhost:8000/git/push-plan \
  -H "x-api-key: demo-control-tower-key"
```

Expected:

- Markdown and JSON files are written under `data/git_packs/`
- pack includes exact non-destructive review commands, suggested commit grouping, do-not-commit generated artifact notes, pre-push verification checklist, repo limitations, and recruiter/GitHub README publish blurb
- one-command demo output includes Git readiness status/branch plus Push Plan Markdown/JSON paths

Required local Git Readiness verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\dashboard_smoke.py
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "git/readiness|git/push-plan|GitHub Push Readiness|git_packs|Branch Hygiene|Git Readiness" app dashboard docs README.md tests scripts
Get-ChildItem -Recurse -File data\git_packs -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

This GitHub Push Readiness check is local/mock only. It uses non-destructive git inspection and does not stage, commit, push, reset, checkout, clean, delete files, or call GitHub APIs.

## CI Doctor and Audit Pack Eval

Inspect the Local CI Doctor:

```bash
curl http://localhost:8000/ops/ci-doctor \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response title is `CI Doctor`
- response mode is `local-deterministic-ci-doctor`
- status is `ready`, `ready_with_warnings`, or `blocked`
- score is at least 90 for the maintained local repo
- structured checks include pytest command, ruff command, eval command, demo command, GitHub Actions workflow, Docker Compose, `.env.example`, README sections, docs presence, generated artifact ignores, dependency files, local/mock provider notes, and suspicious secret-pattern scan summary
- dependency inventory includes `pyproject.toml`, `requirements.txt`, and `requirements-dev.txt`
- secret scan summary includes scanned file count, finding count, redacted findings, skipped generated directories, and local-only notes
- local verification commands include pytest, ruff, eval, demo, CI Doctor text search, and audit artifact listing

Export the Dependency/Secrets Audit Pack:

```bash
curl -X POST http://localhost:8000/ops/audit-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/audit_packs/`
- pack embeds CI Doctor results, dependency inventory, secret scan summary, local verification commands, publish-safety checklist, remediation notes, and recruiter/interviewer explanation
- Markdown includes `## CI Doctor`, `## Dependency Inventory`, `## Secret Scan Summary`, and `## Publish-Safety Checklist`
- one-command demo output includes CI Doctor status/score and the Audit Pack paths

Required local CI Doctor verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "ops/ci-doctor|ops/audit-pack|CI Doctor|Audit Pack|audit_packs|secret scan" app dashboard docs README.md tests scripts
Get-ChildItem -Recurse -File data\audit_packs -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

## Release Candidate Quality Gate and Publish Pack Eval

Inspect the Release Candidate release gate:

```bash
curl http://localhost:8000/release/quality-gate \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response title is `Release Candidate Quality Gate`
- status is `ready` or `ready_with_warnings`
- score is at least 90 and blockers are empty
- coverage includes CI, docs, tests, eval, demo, API, and artifacts
- verification checklist includes pytest, ruff, eval, demo, release text search, and release artifact listing commands
- endpoint inventory includes `GET /release/quality-gate` and `POST /release/publish-pack`
- artifact coverage includes `data/release_packs`
- publish readiness marks commit, push, and recruiter review as ready when blockers are empty

Export the GitHub Publish Pack:

```bash
curl -X POST http://localhost:8000/release/publish-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/release_packs/`
- pack includes release summary, embedded quality gate, setup/demo commands, verification commands, expected outputs, endpoint inventory, artifact inventory, screenshot/manual verification placeholders, GitHub repo checklist, commit/push readiness notes, recruiter review notes, and known limitations
- Markdown includes `Release Candidate Publish Pack`, `## Release Gate`, `## Verification Commands`, and `## GitHub Repo Checklist`
- one-command demo output includes release gate status/score and the Publish Pack paths

Required local RC verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "release/quality-gate|release/publish-pack|Release Candidate|Publish Pack|release_packs|release gate" app dashboard docs README.md tests scripts
Get-ChildItem -Recurse -File data\release_packs -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

## Reviewer Quickstart and Walkthrough Pack Eval

Inspect the Reviewer Quickstart:

```bash
curl http://localhost:8000/reviewer/quickstart \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response title is `Reviewer Quickstart`
- status is `ready` and `local_mock_only` is true
- response includes exact local setup commands, run commands, one-command demo, verification commands, expected outputs, endpoint walkthrough order, agent workflow walkthrough, artifact proof map, troubleshooting, and role-specific reviewer notes
- endpoint walkthrough includes `GET /reviewer/quickstart`, `POST /reviewer/walkthrough-pack`, `POST /demo/evidence-pack`, `GET /portfolio/evidence-index`, `GET /release/quality-gate`, approval, trace, outbox, replay, policy, metrics, and audit surfaces
- artifact proof map includes `data/reviewer_packs`

Export the Walkthrough Pack:

```bash
curl -X POST http://localhost:8000/reviewer/walkthrough-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/reviewer_packs/`
- pack includes recruiter-friendly story, engineer deep-dive path, command checklist, API/workflow proof tour, artifacts to inspect, limitations, GitHub README blurb, and the embedded quickstart
- Markdown includes `Reviewer Walkthrough Pack`, `## Recruiter-Friendly Story`, `## API / Workflow Proof Tour`, and `## GitHub README Blurb`
- one-command demo output includes reviewer quickstart status/proof count and the Walkthrough Pack paths

Required local reviewer verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "reviewer/quickstart|reviewer/walkthrough-pack|Reviewer Quickstart|Walkthrough Pack|reviewer_packs|proof tour" app dashboard docs README.md tests scripts
Get-ChildItem -Recurse -File data\reviewer_packs -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

## Artifact Inventory and README Checklist Eval

Inspect the Artifact Inventory:

```bash
curl http://localhost:8000/artifacts/inventory \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response title is `Artifact Inventory`
- response includes generated artifact directories, latest files, producer endpoints/commands, ignored status, reviewer purpose, local commands, and freshness notes
- artifact list includes `data/artifact_indexes`, `data/demo_packs`, `data/reviewer_packs`, `data/release_packs`, and `data/audit_packs`
- generated rows show latest Markdown/JSON files after the demo or producer endpoints run

Export the README Checklist Pack:

```bash
curl -X POST http://localhost:8000/artifacts/readme-checklist \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/artifact_indexes/`
- pack includes Artifact Inventory, README Badge suggestions, README Checklist suggestions, local commands, reviewer proof checklist, and cleanup/regeneration notes
- Markdown includes `README Checklist Pack`, `## Artifact Inventory`, `## Reviewer Proof Checklist`, and `## Cleanup and Regeneration Notes`
- one-command demo output includes artifact inventory count and README Checklist paths

Required local artifact index verification command set:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts
.\.venv\Scripts\python.exe -m app.evals.run_eval
.\.venv\Scripts\python.exe scripts\demo_run.py
rg "artifacts/inventory|artifacts/readme-checklist|Artifact Inventory|README Checklist|artifact_indexes|reviewer proof checklist" app dashboard docs README.md tests scripts
Get-ChildItem -Recurse -File data\artifact_indexes -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime
```

## Launch Checklist Eval

Inspect the API smoke matrix:

```bash
curl http://localhost:8000/ops/smoke-matrix \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- readiness summary status is `ready`
- matrix includes `GET /ops/smoke-matrix`, `POST /ops/launch-checklist`, and `POST /demo/evidence-pack`
- every row includes expected status, auth requirement, sample `curl.exe` command, PowerShell command, and artifact expectation

Export the reviewer checklist:

```bash
curl -X POST http://localhost:8000/ops/launch-checklist \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/launch_checklists/`
- checklist includes install/run commands, API smoke matrix, demo command, eval commands, generated artifacts, troubleshooting notes, JD skills demonstrated, and five interviewer talking points
- one-command demo prints launch readiness and the checklist paths

## Portfolio Evidence and Interview Pack Eval

Inspect the Portfolio Evidence Index:

```bash
curl http://localhost:8000/portfolio/evidence-index \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response includes `evidence_score`, `evidence_count`, `covered_skill_count`, and `local_mock_only`
- skill coverage includes LangGraph/stateful workflow, human approval, fake Zendesk/Jira/Slack adapters, retry/failure handling, observability/traces, metrics, launch checklist, KB quality, policy guardrails, replay, and leadership/incident artifacts
- every skill maps to implemented features, endpoints, tests/evals, artifacts, demo commands, verification commands, and local proof paths
- artifact inventory includes `data/portfolio_packs`

Export the Interview Pack:

```bash
curl -X POST http://localhost:8000/portfolio/interview-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/portfolio_packs/`
- pack includes a 3-minute demo script, 8-10 technical talking points, architecture walk-through, failure mode story, local verification commands, metrics/eval summary, artifact inventory, and resume/GitHub README bullets
- Markdown includes `Portfolio Evidence`, `Interview Pack`, `## 3-Minute Demo Script`, and `## Failure Mode Story`
- one-command demo output includes the portfolio evidence score/count and generated Interview Pack paths

## Knowledge Quality Auditor Eval

Audit the local KB:

```bash
curl http://localhost:8000/knowledge/quality-audit \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response mode is `local-deterministic-knowledge-quality-auditor`
- `kb_coverage_score` is a deterministic 0-100 score
- metrics include coverage, freshness, citations, conflicts, retrieval evidence, and high-impact gap count
- weak or missing articles include missing review-date/citation findings and conflict findings when policy guardrails disagree with article language
- evidence sources include workflow retrieval runs, Replay Lab KB-context modifiers, policy guardrail signal, incident narrative signal, and leadership scorecard signal
- readiness status is one of `not_ready_refresh_required`, `review_ready_with_kb_risks`, or `ready_for_agentic_escalation`

Export the KB refresh plan:

```bash
curl -X POST http://localhost:8000/knowledge/refresh-plan \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/kb_refresh_plans/`
- export includes article refresh tasks, owners, acceptance criteria, impacted workflows, local commands, JD skills demonstrated, and five interviewer talking points
- tasks are owner-ready and map KB issues back to ticket types and workflows such as `knowledge_retriever`, `qa_evaluator`, `policy_guardrails`, and `incident_narrative`

## Leadership Scorecard Eval

After running the demo scenario or local evidence pack, call:

```bash
curl http://localhost:8000/leadership/scorecard \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- response mode is `local-deterministic-automation-kpi-scorecard`
- KPI categories include automation safety, approval health, SLA risk, escalation quality, retry/failure behavior, policy blocks, replay risk, customer impact, and operator readiness
- every KPI category has a numeric 0-100 score, status, local values, risk flags, and recommended actions
- trend-ish local values include run count, approval rate, pending approvals, SLA risk count, failure behavior, outbox count, SLO status, replay risk score, policy decision, and operator readiness score
- risk flags surface pending approvals, high SLA risk, retry failures, policy blocks, replay risk, customer impact, or readiness gaps when present
- artifact links point to local evidence such as incident narrative, replay report, policy pack, operator pack, and leadership review files when those have been exported

Export the leadership review pack:

```bash
curl -X POST http://localhost:8000/leadership/review-pack \
  -H "x-api-key: demo-control-tower-key"
```

Expected evidence:

- Markdown and JSON files are written under `data/leadership_reviews/`
- export includes the scorecard, KPI definitions, local evidence links, top risks, recommended next actions, local commands, JD skills demonstrated, and five interviewer talking points
- no external BI, warehouse, CRM, Zendesk, Jira, Slack, Azure, or OpenAI service is required

## Policy Guardrail Eval

Run the approval policy simulator:

```bash
curl -X POST http://localhost:8000/policies/simulate \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{
    "modifiers": {
      "sla_pressure": "critical",
      "kb_context": "conflicting",
      "adapter_health": "degraded",
      "confidence_override": 0.44,
      "approval_policy": "strict"
    },
    "requested_actions": ["customer_reply", "jira_issue", "slack_alert"],
    "replay_risk_threshold": 70
  }'
```

Expected evidence:

- response includes `policy_decision`, `required_approval_type`, `blocked_actions`, `allowed_actions`, `matched_rules`, `warnings`, `recommended_operator_action`, and `approval_matrix`
- matched rules can cover `low_confidence`, `high_or_critical_sla_pressure`, `enterprise_or_vip_customer`, `external_reply_requires_approval`, `adapter_degraded_or_failing`, `replay_risk_above_threshold`, and `missing_or_conflicting_kb_context`
- with no body, the endpoint uses the latest local run or bootstraps a deterministic sample
- external customer replies and Zendesk updates are treated differently from internal Jira, Slack, and engineering escalation actions
- the simulator remains fully local/mock and reuses Replay Lab findings rather than calling an external policy engine

Export the pack:

```bash
curl -X POST http://localhost:8000/policies/export \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"modifiers": {"sla_pressure": "critical", "adapter_health": "failing"}}'
```

Expected evidence:

- Markdown and JSON files are written under `data/policy_packs/`
- pack includes simulated policies, matched rules, approval matrix, sample scenario outcomes, local verification commands, JD skills demonstrated, and five interviewer talking points

## Customer Impact Timeline and Executive Narrative Eval

Build the timeline:

```bash
curl -X POST http://localhost:8000/incidents/timeline \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}"}'
```

Expected evidence:

- events are ordered by timestamp and sequence
- response includes customer impact summary, impact status, internal actions, external actions, policy annotations, replay annotations, unresolved risks, owner next steps, and evidence artifact links
- phases cover ticket intake, triage, approval, customer reply or pending customer update, engineering escalation or pending owner action, policy decision, replay risk, remediation plan, customer health, weekly review, and SLO posture
- with no body, the endpoint uses the latest local run or bootstraps a deterministic sample incident

Export the executive narrative:

```bash
curl -X POST http://localhost:8000/incidents/executive-narrative \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}"}'
```

Expected evidence:

- Markdown and JSON files are written under `data/incident_narratives/`
- export includes executive summary, timeline, customer impact, decisions made, approval evidence, policy guardrail decision, replay risk, SLO posture, owner actions, local commands, JD skills demonstrated, and five interviewer talking points
- one-command demo output includes the narrative path and incident impact status

## Change Risk and Escalation Replay Eval

Run a counterfactual replay:

```bash
curl -X POST http://localhost:8000/replay-lab/run \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{
    "modifiers": {
      "sla_pressure": "critical",
      "kb_context": "conflicting",
      "adapter_health": "degraded",
      "confidence_override": 0.42,
      "approval_policy": "strict"
    }
  }'
```

Expected evidence:

- response includes `original`, `replay`, and `comparison`
- changed decisions identify shifts in confidence, SLA risk, final action, approval requirement, failure state, or tool attempts
- degraded adapter replay records one failed attempt followed by recovery
- failing adapter replay records exhausted attempts and a replay `failure_state`
- risk flags include relevant entries such as `decision_changed`, `high_sla_risk`, `missing_kb_context`, `conflicting_kb_context`, `adapter_degraded`, or `adapter_failure`
- recommended operator action tells reviewers whether to block automation approval, require lead review, or continue standard checks

Export a report:

```bash
curl -X POST http://localhost:8000/replay-lab/report \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"modifiers": {"sla_pressure": "critical", "adapter_health": "failing"}}'
```

Expected evidence:

- Markdown and JSON files are written under `data/replay_reports/`
- report includes modifiers, original and replay trace IDs, risk flags, local verification commands, JD skills demonstrated, and five interviewer talking points

## Runbook QA and Operator Readiness Eval

Call Runbook QA with a known approved run:

```bash
curl -X POST http://localhost:8000/ops/runbook-qa \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}"}'
```

Expected evidence:

- score is deterministic from the 15 required handoff sections
- pass/fail status reflects missing sections rather than only the numeric score
- missing sections include unapproved-run gaps such as `outbox_dispatches` and missing drill evidence such as `failure_drill_result`
- linked artifact paths include incident brief, remediation checklist, weekly review, account brief, and optimization report files
- recommended fixes explain exactly what an operator should export, approve, or run next

Export the operator readiness pack:

```bash
curl -X POST http://localhost:8000/ops/operator-readiness-pack \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}"}'
```

Expected evidence:

- Markdown and JSON files are written under `data/operator_packs/`
- pack includes Runbook QA result, critical metrics, endpoint list, local demo command, JD skills demonstrated, and five interviewer talking points
- a fresh clone can omit the body; the service will use the latest run or bootstrap a deterministic local sample
