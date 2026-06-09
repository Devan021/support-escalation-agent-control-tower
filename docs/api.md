# API

Base URL: `http://localhost:8000`

Auth: send `x-api-key: demo-control-tower-key` or `Authorization: Bearer demo-control-tower-key`.

## Endpoints

- `POST /auth/demo-token`
  Returns the local demo token.

- `POST /tickets/ingest`
  Creates a ticket.

- `POST /tickets/ingest-samples`
  Loads the bundled local sample tickets for deterministic demos.

- `GET /tickets`
  Lists tickets.

- `POST /tickets/{ticket_id}/analyze`
  Starts an agent run for a ticket. The run executes all workflow nodes and pauses at approval before dispatching customer replies or engineering tickets.

- `GET /runs/{run_id}`
  Returns run state, classification, SLA risk, KB results, drafts, QA result, approval ID, metrics, final action, and failure state.

- `GET /runs/{run_id}/trace`
  Returns node and tool trace events.

- `POST /runs/{run_id}/replay-lab`
  Runs the Change Risk Simulator / Escalation Replay Lab for one stored run. The optional body accepts `modifiers` with `sla_pressure` (`normal`, `high`, `critical`), `kb_context` (`full`, `missing`, `conflicting`), `adapter_health` (`healthy`, `degraded`, `failing`), optional `confidence_override`, and `approval_policy` (`strict`, `standard`, `auto_internal_only`). The response compares original vs replay classification, SLA risk, final action, approval requirement, failure state, tool attempts, latency/token/cost estimates, changed decisions, risk score, and recommended operator action.

- `POST /replay-lab/run`
  Same replay comparison, but accepts an optional `run_id` in the body and falls back to the latest run or a deterministic sample when omitted.

- `POST /replay-lab/report`
  Writes Markdown and JSON under the ignored replay report folder, normally `data/replay_reports/`. The report includes comparison, modifiers, trace IDs, risk flags, local verification commands, JD skills demonstrated, and five interviewer talking points.

- `POST /policies/simulate`
  Runs the Agent Policy Guardrail Center approval policy simulator for a supplied `run_id`, the latest local run, or a deterministic sample fallback when omitted. The optional body accepts Replay Lab `modifiers`, `requested_actions`, and `replay_risk_threshold`. The response includes policy decision, required approval type, approval chain, blocked actions, allowed actions, matched rules, warnings, recommended operator action, approval matrix, and replay summary. Default rules cover low confidence, high/critical SLA pressure, enterprise/VIP customer tier, external reply vs internal action, degraded/failing adapters, replay risk above threshold, and missing/conflicting KB context.

- `POST /policies/export`
  Writes Markdown and JSON under the ignored policy pack folder, normally `data/policy_packs/`. The pack includes simulated policies, primary matched rules, approval matrix, sample scenario outcomes, local verification commands, JD skills demonstrated, and five interviewer talking points.

- `POST /incidents/timeline`
  Builds the Customer Impact Timeline for a supplied `run_id`, the latest local run, or a deterministic sample fallback when omitted. The response includes ordered timeline events, customer impact summary, internal/external action split, policy guardrail annotations, Replay Lab annotations, unresolved risks, owner next steps, impact status, and evidence artifact links. It reuses existing local exports such as incident brief, remediation checklist, weekly review, account brief, optimization report, and replay report.

- `POST /incidents/executive-narrative`
  Writes Markdown and JSON under the ignored narrative folder, normally `data/incident_narratives/`. The optional body can include `run_id`; otherwise it uses the latest/sample fallback. The export includes the timeline, executive summary, customer impact, decisions made, approval evidence, policy guardrail decision, replay risk, SLO posture, owner actions, local commands, JD skills demonstrated, and five interviewer talking points.

- `GET /incidents/postmortem-summary`
  Returns the latest or deterministic sample Postmortem RCA summary with incident summary, severity, timeline, root cause category, contributing factors, impacted customer/account, approval and communications status, trace links, corrective actions, customer follow-up state, recurrence risk, readiness summary, proof commands, and Scenario Dataset RCA coverage.

- `POST /incidents/rca-pack`
  Writes Markdown and JSON under the ignored RCA folder, normally `data/rca_packs/`. The optional body can include `run_id`; otherwise it uses the latest/sample fallback. The pack includes a postmortem narrative, timeline, trace/audit evidence, action owners, due dates, recurrence risk, customer follow-up state, deterministic RCA coverage across outage/API, tool failure/retry, privacy/data export, billing/customer risk, and low-confidence human-review scenarios, proof commands, and limitations.

- `GET /leadership/scorecard`
  Returns the Support Automation KPI Scorecard for leadership review. The response includes numeric scores for automation safety, approval health, SLA risk, escalation quality, retry/failure behavior, policy blocks, replay risk, customer impact, and operator readiness. It also includes trend-ish local values, risk flags, recommended actions, artifact links, KPI definitions, local commands, and readiness status.

- `POST /leadership/review-pack`
  Writes Markdown and JSON under the ignored leadership review folder, normally `data/leadership_reviews/`. The pack includes the scorecard, KPI definitions, local evidence links, top risks, recommended next actions, local verification commands, JD skills demonstrated, and five interviewer talking points. It remains fully local/mock and does not call external BI, warehouse, or support systems.

- `GET /knowledge/quality-audit`
  Returns the Knowledge Quality Auditor result for support leadership. The response includes `kb_coverage_score`, readiness status, freshness/coverage/conflict/citation metrics, weak or missing articles, impacted ticket types, owner recommendations, risk flags, local commands, and evidence sources from local KB snippets, workflow retrieval outputs, ticket categories, Replay Lab KB-context modifiers, policy guardrails, incident narratives, and the leadership scorecard.

- `POST /knowledge/refresh-plan`
  Writes Markdown and JSON under the ignored KB refresh folder, normally `data/kb_refresh_plans/`. The plan includes article refresh tasks, owners, acceptance criteria, impacted workflows, local verification commands, JD skills demonstrated, and five interviewer talking points. It remains fully local/mock and does not call an external knowledge-base system.

- `POST /playbooks/recommend`
  Accepts either `ticket_id` or an inline `ticket` payload plus optional `top_n`. Returns ranked playbooks with match reasons, confidence, checklist steps, owner roles, escalation policy, and customer update template. If a stored ticket has already been analyzed, the recommender uses its classification and SLA risk context.

- `POST /runs/{run_id}/incident-brief`
  Exports a Markdown and JSON incident brief for a run. The response includes file paths plus structured content with customer impact, classification, SLA risk, KB citations, customer reply draft, engineering escalation draft, approval status, trace summary, outbox status, and recommended next steps. Local files are written under the ignored runtime briefs folder, normally `data/briefs/`.

- `POST /runs/{run_id}/remediation-checklist`
  Exports a Markdown and JSON remediation checklist for a run. The response includes file paths plus structured content with ticket context, classification, SLA risk, selected playbook, checklist steps, owner roles, approval status, and next customer update template. Local files are written under the ignored runtime checklists folder, normally `data/checklists/`. The optional body can include `playbook_id` to force a specific playbook.

- `POST /runs/{run_id}/approve`
  Approves pending drafts and dispatches fake Zendesk/Jira/Slack actions.

- `POST /runs/{run_id}/reject`
  Rejects pending drafts and marks the run rejected.

- `GET /approvals`
  Lists pending approvals.

- `GET /integrations/outbox`
  Lists persisted fake external dispatch records for Zendesk, Jira, and Slack. Each row includes `trace_id`, `run_id`, `ticket_id`, `action_type`, `destination`, `payload`, `status`, and `created_at`.

- `GET /integrations/outbox/{outbox_id}`
  Returns one outbox dispatch record.

- `POST /drills/tool-failure`
  Runs a deterministic local failure drill by ingesting a low-confidence ticket that forces KB retries to fail. The response includes the run, approval, full trace, and failed tool-call timeline.

- `POST /drills/sla-breach-simulation`
  Creates or reuses local SLA simulator tickets, analyzes them, and returns a prioritized queue. Each row includes `ticket_id`, `customer_tier`, `minutes_to_sla`, `risk_level`, `recommended_action`, `run_id`, and `approval_id`.

- `GET /metrics/agent-performance`
  Returns run counts, approval counts, outbox dispatch counts, failure-drill counts, failure counts, average latency/token/cost metrics, node metrics, and estimated cost.

- `GET /analytics/ops-snapshot`
  Returns a leadership snapshot across local tickets, runs, approvals, outbox, drills, reports, and incident briefs. The response includes counts by ticket category, ticket status, SLA risk, final action, approval status, outbox destination/action, and failure type; average latency/tokens/cost; top risky tickets; SLA queue highlights; failure drill summary; outbox dispatch summary; incident brief paths; and recommended operational actions.

- `POST /analytics/weekly-review`
  Writes Markdown and JSON under the ignored local reports folder, normally `data/reports/`. The report includes summary metrics, SLA queue highlights, failure drill summary when present, outbox dispatch summary, incident brief paths when present, top risky tickets, and next actions.

- `GET /ops/slo-budget`
  Returns deterministic local SLO status for agent workflow latency, token usage per run, estimated cost per run, workflow failure count, pending approvals, and outbox dispatch delay. Each metric includes `thresholds`, `current_value`, `status` as `pass`, `warn`, or `fail`, and a `recommendation`.

- `POST /ops/optimization-report`
  Writes Markdown and JSON under the ignored local optimization reports folder, normally `data/optimization_reports/`. The report includes SLO statuses, top slow nodes, high-token nodes, failure hotspots, approval bottlenecks, and recommended fixes.

- `GET /ops/ci-doctor`
  Returns the Local CI Doctor for publish-safety review. The response includes structured checks for the pytest command, ruff command, eval command, demo command, GitHub Actions workflow presence, Docker Compose presence, `.env.example`, README required sections, docs presence, generated artifact ignores, dependency files, local/mock provider notes, and a redacted suspicious secret-pattern scan summary. It is deterministic, local-only, and does not call GitHub, PyPI, secret-scanning vendors, or external services.

- `POST /ops/audit-pack`
  Writes Markdown and JSON under the ignored local audit folder, normally `data/audit_packs/`. The Audit Pack includes the CI Doctor result, dependency inventory, secret scan summary, local verification commands, publish-safety checklist, remediation notes, and recruiter/interviewer explanation.

- `GET /ops/smoke-matrix`
  Returns the Local Launch Checklist smoke matrix for GitHub reviewers. Each row includes endpoint, purpose, auth requirement, expected status, sample `curl.exe` and PowerShell `Invoke-RestMethod` commands, artifact expectation, and the overall launch readiness summary.

- `POST /ops/launch-checklist`
  Writes Markdown and JSON under the ignored local launch checklist folder, normally `data/launch_checklists/`. The checklist includes install/run commands, API smoke matrix, demo command, eval commands, generated artifact expectations and latest paths, troubleshooting notes, JD skills demonstrated, and five interviewer talking points.

- `GET /portfolio/evidence-index`
  Returns the Portfolio Evidence Index for recruiter/interviewer review. The response includes `evidence_score`, `evidence_count`, covered skill count, JD skill evidence, implemented features, endpoints, tests/evals, artifacts, demo commands, verification commands, local proof paths, runtime counts, and latest generated artifact paths. It remains fully local/mock and does not call Azure, OpenAI, Zendesk, Jira, Slack, or external systems.

- `POST /portfolio/interview-pack`
  Writes Markdown and JSON under the ignored local portfolio folder, normally `data/portfolio_packs/`. The Interview Pack includes a 3-minute demo script, 8-10 technical talking points, architecture walk-through, failure mode story, local verification commands, metrics/eval summary, artifact inventory, resume/GitHub README bullets, and the embedded Portfolio Evidence Index.

- `GET /release/quality-gate`
  Returns the Release Candidate quality gate for GitHub publish readiness. The response includes status, score, blockers, warnings, verification checklist, CI/docs/test/eval/demo/API coverage, artifact coverage, endpoint inventory, local-only runtime notes, and publish readiness. It is a deterministic local release gate and does not call GitHub, Azure, OpenAI, Zendesk, Jira, or Slack.

- `POST /release/publish-pack`
  Writes Markdown and JSON under the ignored local release folder, normally `data/release_packs/`. The Publish Pack includes the embedded Release Candidate gate, release summary, setup/demo commands, verification commands, expected outputs, endpoint inventory, artifact inventory, screenshot/manual verification placeholders, GitHub repo checklist, commit/push readiness notes, recruiter review notes, and known limitations.

- `GET /reviewer/quickstart`
  Returns the Reviewer Quickstart for GitHub reviewers. The response includes exact local setup commands, run commands, one-command demo, verification commands, endpoint walkthrough order, agent workflow walkthrough, artifact proof map, expected outputs, troubleshooting, role-specific reviewer notes, and local/mock runtime counts.

- `POST /reviewer/walkthrough-pack`
  Writes Markdown and JSON under the ignored local reviewer folder, normally `data/reviewer_packs/`. The Walkthrough Pack includes a recruiter-friendly story, engineer deep-dive path, command checklist, API/workflow proof tour, artifacts to inspect, limitations, GitHub README blurb, and the embedded Reviewer Quickstart.

- `GET /artifacts/inventory`
  Returns the Artifact Inventory for GitHub reviewers. The response lists generated artifact directories, resolved local directories, latest Markdown/JSON files, producer endpoints and PowerShell commands, `.gitignore` ignored status, reviewer purpose, file counts, local verification commands, and freshness notes. It remains deterministic and local-only.

- `POST /artifacts/readme-checklist`
  Writes Markdown and JSON under the ignored local artifact index folder, normally `data/artifact_indexes/`. The README Checklist Pack includes the Artifact Inventory, README badge suggestions, README checklist suggestions, local commands, reviewer proof checklist, and cleanup/regeneration notes.

- `GET /ui/dashboard-smoke`
  Returns Dashboard Smoke source checks for GitHub reviewers. The response includes expected Streamlit view labels, endpoint references, generated artifact tabs, local run commands, pass/fail check details, and limitations. It inspects local source files only and does not launch Streamlit, a browser, or external services.

- `POST /ui/verification-pack`
  Writes Markdown and JSON under the ignored local UI verification folder, normally `data/ui_verification/`. The UI Verification Pack includes the Dashboard Smoke results, Streamlit run command, reviewer checklist, screenshot placeholders, troubleshooting notes, and limitations.

- `GET /handoff/final-audit`
  Returns the README Consistency Final Audit for final portfolio review. The response includes structured checks for README endpoint mentions, docs/api coverage, architecture/evaluation/workflow coverage, demo output claims, required scripts, dashboard smoke script presence, generated artifact directory docs, local/mock Azure limitation clarity, endpoint inventory summary, artifact inventory summary, dashboard smoke summary, and local-only notes. It inspects local source files only and does not call GitHub, Azure, OpenAI, Zendesk, Jira, Slack, or external services.

- `POST /handoff/final-pack`
  Writes Markdown and JSON under the ignored local final handoff folder, normally `data/final_handoff/`. The Final Handoff Pack includes final audit results, exact clone/run commands, end-to-end verification order, endpoint inventory summary, artifact inventory summary, dashboard smoke summary, recruiter-facing final README blurb, artifact paths, and local/mock limitations.

- `GET /handoff/on-call-summary`
  Returns the latest or scenario-derived On-Call Handoff summary. The response includes owners, severity, current status, SLA deadline, trace links, customer communication readiness, approval and guardrail status, customer update drafts, engineering incident ticket summary, and a risk/gap checklist.

- `POST /handoff/customer-comms-pack`
  Writes Markdown and JSON under the ignored local customer communications folder, normally `data/customer_comms_packs/`. The pack includes customer update drafts, internal on-call handoff, engineering ticket draft, SLA/customer-impact timeline, approval checklist, guardrail status, trace IDs, deterministic coverage across Scenario Dataset paths, local proof commands, and limitations. It drafts only; it does not dispatch customer-visible communications.

- `GET /git/readiness`
  Returns GitHub Push Readiness and Branch Hygiene checks from read-only local git inspection. The response includes git repo detection, current branch, tracked/untracked/modified/ignored summary, generated artifact directories that should stay ignored, changed source/doc/test/dashboard buckets, suspicious large/generated files, required GitHub Actions workflow presence, README final handoff mention, `.env.example` presence, dirty-worktree guidance, and recommended commit groups. It does not call GitHub APIs or mutate the repository.

- `POST /git/push-plan`
  Writes Markdown and JSON under the ignored local git pack folder, normally `data/git_packs/`. The Branch Hygiene pack includes exact non-destructive review commands, suggested commit grouping, do-not-commit generated artifact notes, pre-push verification checklist, repo limitations, and a recruiter/GitHub README publish blurb. It does not stage, commit, push, reset, checkout, clean, delete files, or call GitHub APIs.

- `GET /api/contract-audit`
  Returns the API Contract Audit for fresh-clone reviewers. The response is derived from the local OpenAPI schema and FastAPI route dependency metadata, then cross-checks auth-protected endpoint count, important README/docs coverage, dashboard smoke alignment, generated artifact endpoint coverage, demo flow endpoint coverage, missing docs warnings, deprecated/duplicate route warnings, and local-only limitations.

- `POST /api/reviewer-collection`
  Writes Markdown and JSON under the ignored local API contract folder, normally `data/api_contracts/`. The Reviewer Collection includes endpoint inventory grouped by domain, sample `curl.exe` and PowerShell commands with `X-API-Key`, demo-token flow, expected status codes, auth notes, generated artifact endpoints, one-command verification order, and recruiter/engineer explanations.

- `GET /runtime/demo-readiness`
  Returns source-only Runtime Demo readiness for fresh-clone reviewers. The response includes install and start commands, `scripts\runtime_check.py`, optional `scripts\start_demo.ps1`, expected FastAPI and Streamlit ports, environment defaults, dependency and file checks, safe read-only socket/netstat port checks, health URLs, smoke URLs, known limitations, and troubleshooting. It does not require a running external service and does not kill processes.

- `POST /runtime/demo-pack`
  Writes Markdown and JSON under the ignored local runtime pack folder, normally `data/runtime_packs/`. The Runtime Demo Server Pack includes exact start commands, stop commands for manual use, health checks, demo flow order, screenshot checklist placeholders, troubleshooting, recruiter and engineer explanations, known limitations, artifact paths, and the embedded readiness report.

- `GET /scenarios/catalog`
  Returns the Scenario Dataset catalog from `sample_data/scenarios.json`. The response includes scenario metadata, expected classification, SLA, approval, escalation, low-confidence review, failure/tool-retry outcomes, required domain presence, and scenario coverage summary.

- `POST /scenarios/eval-pack`
  Runs deterministic local checks over the Scenario Dataset and writes Markdown plus JSON under the ignored local scenario pack folder, normally `data/scenario_packs/`. The pack includes classification accuracy, SLA routing, approval pause coverage, escalation coverage, low-confidence review coverage, failure/tool-retry coverage, generated artifact paths, and gaps/warnings.

- `POST /ops/runbook-qa`
  Evaluates operator handoff completeness for a supplied `run_id`, the latest local run, or a deterministic sample fallback when no run exists. The response includes score, pass/fail status, missing sections, warnings, linked artifact paths, and recommended fixes for ticket summary, classification, SLA risk, customer impact, KB context, drafts, approval state, trace ID, outbox, failure drill, remediation owners, SLO budget, optimization recommendations, and customer/account health.

- `POST /ops/operator-readiness-pack`
  Writes Markdown and JSON under the ignored local operator pack folder, normally `data/operator_packs/`. The pack includes the Runbook QA result, critical metrics, endpoint list, local demo command, JD skills demonstrated, and five interviewer talking points. The optional body can include `run_id`.

- `POST /demo/scenario-run`
  Runs the complete deterministic local interview scenario using existing services. The response includes the primary ticket/run, generated artifact paths, API endpoints exercised, summary metrics, key metrics, and links to trace, approval, outbox, ops, customer health, and SLO views. It covers ticket analysis, trace, approval, outbox dispatch, failure drill, SLA simulation, incident brief, weekly review, remediation checklist, customer health, account brief, SLO budget, and optimization report.

- `POST /demo/evidence-pack`
  Runs the local scenario and writes Markdown plus JSON under the ignored demo pack folder, normally `data/demo_packs/`. The pack includes summary, generated artifact paths, API endpoints exercised, key metrics, summary metrics, links, and interview talking points.

- `GET /customers/health`
  Returns account health summaries grouped from local ticket state and `sample_data/customers.json` metadata when available. Each row includes `customer`, `account`, ticket counts, open/pending/escalated counts, high-SLA-risk count, recent failure count, pending approval count, recommended playbook count, deterministic `health_score` from 0-100, `risk_level`, and `recommended_action`.

- `POST /customers/{customer_id_or_name}/account-brief`
  Writes Markdown and JSON under the ignored local account brief folder, normally `data/account_briefs/`. The brief includes customer health, active tickets, recent runs, recommended playbooks, pending approvals, outbox summary, and next actions. The path parameter can be the returned `customer_id` slug or the account/customer name.

- `GET /audit/events`
  Returns audit events.

- `GET /health`
  Returns service health.

## Example

```bash
curl -X POST http://localhost:8000/tickets/ingest \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{
    "subject": "Enterprise SSO outage blocking all agents",
    "body": "SAML SSO login is down for all support agents and SLA breach is near.",
    "priority": "urgent",
    "customer_tier": "enterprise",
    "tags": ["auth", "sso", "outage"]
  }'
```

After approving a run, inspect the local integration outbox:

```bash
curl http://localhost:8000/integrations/outbox \
  -H "x-api-key: demo-control-tower-key"
```

Run the reliability drill:

```bash
curl -X POST http://localhost:8000/drills/tool-failure \
  -H "x-api-key: demo-control-tower-key"
```

Run Replay Lab with changed conditions:

```bash
curl -X POST http://localhost:8000/replay-lab/run \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{
    "modifiers": {
      "sla_pressure": "critical",
      "kb_context": "missing",
      "adapter_health": "degraded",
      "confidence_override": 0.48,
      "approval_policy": "strict"
    }
  }'

curl -X POST http://localhost:8000/replay-lab/report \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}", "modifiers": {"adapter_health": "failing"}}'
```

Simulate and export approval policy guardrails:

```bash
curl -X POST http://localhost:8000/policies/simulate \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{
    "run_id": "{run_id}",
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

curl -X POST http://localhost:8000/policies/export \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}", "modifiers": {"sla_pressure": "critical"}}'
```

Build the Customer Impact Timeline and export the executive narrative:

```bash
curl -X POST http://localhost:8000/incidents/timeline \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}"}'

curl -X POST http://localhost:8000/incidents/executive-narrative \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}"}'
```

Review leadership automation KPIs and export the review pack:

```bash
curl http://localhost:8000/leadership/scorecard \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/leadership/review-pack \
  -H "x-api-key: demo-control-tower-key"
```

Audit KB readiness and export a KB refresh plan:

```bash
curl http://localhost:8000/knowledge/quality-audit \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/knowledge/refresh-plan \
  -H "x-api-key: demo-control-tower-key"
```

Run the SLA simulator and export a brief:

```bash
curl -X POST http://localhost:8000/drills/sla-breach-simulation \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/runs/{run_id}/incident-brief \
  -H "x-api-key: demo-control-tower-key"
```

Recommend a playbook and export a remediation checklist:

```bash
curl -X POST http://localhost:8000/playbooks/recommend \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"ticket_id": "{ticket_id}", "top_n": 3}'

curl -X POST http://localhost:8000/runs/{run_id}/remediation-checklist \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"playbook_id": "pb_sso_outage"}'
```

Export the weekly ops review:

```bash
curl http://localhost:8000/analytics/ops-snapshot \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/analytics/weekly-review \
  -H "x-api-key: demo-control-tower-key"
```

Inspect SLO budget and export optimization recommendations:

```bash
curl http://localhost:8000/ops/slo-budget \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/ops/optimization-report \
  -H "x-api-key: demo-control-tower-key"
```

Run the CI Doctor and export the Dependency/Secrets Audit Pack:

```bash
curl http://localhost:8000/ops/ci-doctor \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/ops/audit-pack \
  -H "x-api-key: demo-control-tower-key"
```

Run Runbook QA and export an operator readiness pack:

```bash
curl -X POST http://localhost:8000/ops/runbook-qa \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}"}'

curl -X POST http://localhost:8000/ops/operator-readiness-pack \
  -H "content-type: application/json" \
  -H "x-api-key: demo-control-tower-key" \
  -d '{"run_id": "{run_id}"}'
```

Review the Smoke Matrix and export the Launch Checklist:

```bash
curl http://localhost:8000/ops/smoke-matrix \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/ops/launch-checklist \
  -H "x-api-key: demo-control-tower-key"
```

Review the Release Candidate gate and export the Publish Pack:

```bash
curl http://localhost:8000/release/quality-gate \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/release/publish-pack \
  -H "x-api-key: demo-control-tower-key"
```

Review customer health and export an account brief:

```bash
curl http://localhost:8000/customers/health \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/customers/northstar-health/account-brief \
  -H "x-api-key: demo-control-tower-key"
```

Run the full interview scenario or export the evidence pack:

```bash
curl -X POST http://localhost:8000/demo/scenario-run \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/demo/evidence-pack \
  -H "x-api-key: demo-control-tower-key"
```

Run Dashboard Smoke and export the UI Verification Pack:

```bash
curl http://localhost:8000/ui/dashboard-smoke \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/ui/verification-pack \
  -H "x-api-key: demo-control-tower-key"
```

Review the On-Call Handoff and export the Customer Communications pack:

```bash
curl http://localhost:8000/handoff/on-call-summary \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/handoff/customer-comms-pack \
  -H "x-api-key: demo-control-tower-key"
```

Review the Postmortem RCA and export the Corrective Action Tracking Pack:

```bash
curl http://localhost:8000/incidents/postmortem-summary \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/incidents/rca-pack \
  -H "x-api-key: demo-control-tower-key"
```

Run the OpenAPI-derived API Contract Audit and export the Reviewer Collection:

```bash
curl http://localhost:8000/api/contract-audit \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/api/reviewer-collection \
  -H "x-api-key: demo-control-tower-key"
```

Run Runtime Demo readiness and export the Runtime Demo Server Pack:

```bash
curl http://localhost:8000/runtime/demo-readiness

curl -X POST http://localhost:8000/runtime/demo-pack \
  -H "x-api-key: demo-control-tower-key"
```

Review the Scenario Dataset and export the Eval Coverage Pack:

```bash
curl http://localhost:8000/scenarios/catalog \
  -H "x-api-key: demo-control-tower-key"

curl -X POST http://localhost:8000/scenarios/eval-pack \
  -H "x-api-key: demo-control-tower-key"
```
