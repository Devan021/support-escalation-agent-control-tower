# Workflow

The workflow uses LangGraph when available. If LangGraph cannot import in a constrained local environment, the app keeps the same graph abstraction and executes a documented sequential fallback with the same node names and state contract.

## Nodes

1. `intake_classifier`
   Classifies category, priority, sentiment, confidence, and rationale.

2. `sla_risk_scorer`
   Scores SLA risk using priority, customer tier, outage terms, breach terms, and production impact.

3. `playbook_recommender`
   Ranks local operational playbooks using ticket text, tags, classification, SLA risk, priority, and customer tier. The run state stores top recommendations with confidence, match reasons, checklist steps, owner roles, escalation policy, and customer update template.

4. `knowledge_retriever`
   Searches the internal KB adapter with retry handling and records every tool call.

5. `customer_reply_drafter`
   Drafts a customer-safe reply using local mock LLM behavior and retrieved KB context.

6. `engineering_escalation_drafter`
   Drafts a Jira-ready escalation when SLA risk, incident, auth, API, or integration signals warrant it.

7. `qa_evaluator`
   Checks confidence, KB failures, risky categories, and high-SLA-risk conditions.

8. `human_approval`
   Creates a pending approval. The system always pauses before customer replies or engineering tickets.

9. `finalizer`
   During initial analysis, marks the run as awaiting approval without dispatching external actions. After approval, it sends fake Zendesk/Jira/Slack actions and writes each dispatch to the local integration outbox. After rejection, it records rejection.

## Failure Handling

Tool failures retry up to `CONTROL_TOWER_MAX_TOOL_ATTEMPTS`. Exhausted retries set `failure_state`, lower QA confidence, and force human review. The trace endpoint shows every failed attempt.

`POST /drills/tool-failure` demonstrates this behavior with a deterministic ticket containing `force-kb-failure`. The drill records each failed KB attempt, leaves the run awaiting human approval, and returns the failure timeline for reliability review.

## Integration Outbox

Approved runs persist fake external actions in `outbox` before or alongside the fake adapter call. Supported action types are:

- `customer_reply`
- `zendesk_update`
- `engineering_escalation`
- `jira_issue`
- `slack_alert`

Each event includes trace/run/ticket identifiers, destination, payload, dispatch status, and creation time. This gives interviewers an inspectable record of what would have gone to Zendesk, Jira, and Slack without requiring external accounts.

## SLA Breach Simulation

`POST /drills/sla-breach-simulation` creates or reuses deterministic local tickets with breached, critical, warning, and watch SLA windows. Each ticket is analyzed through the same workflow, paused at approval, and returned as a manager queue with `minutes_to_sla`, `risk_level`, `recommended_action`, `run_id`, and `approval_id`.

The simulator uses only local fixtures and fake providers. Azure OpenAI, Zendesk, Jira, and Slack remain optional integration targets and are not required for the drill.

## Incident Brief Export

`POST /runs/{run_id}/incident-brief` packages one run into Markdown and JSON under the ignored runtime briefs folder. The brief is meant for leadership review or engineering handoff and includes customer impact, classification, SLA risk, KB citations, customer reply draft, engineering escalation draft, approval status, trace summary, outbox status, and recommended next steps.

Pending runs show `pending_approval_no_dispatch` in the outbox section. Approved runs include the local fake dispatch records written by the finalizer.

## Playbook Recommendation and Remediation

The local playbook library lives in `sample_data/playbooks.json` and covers SSO outage, webhook regression, billing dispute, privacy export, and API key rotation scenarios. `POST /playbooks/recommend` can rank playbooks for a stored `ticket_id` or an inline ticket payload.

Analyzed runs include `state.playbook_recommendations`, so dashboard and demo handoffs can show the top playbook without another service call. `POST /runs/{run_id}/remediation-checklist` exports the selected playbook into Markdown and JSON under the ignored local checklists folder, normally `data/checklists/`. The export includes ticket context, classification, SLA risk, selected playbook, owner-role assignments for each checklist step, approval status, and the next customer update template.

## Ops Analytics and Weekly Review

`GET /analytics/ops-snapshot` reads only local state and report files to summarize operational trends across tickets, runs, approvals, outbox dispatches, drills, and incident briefs. It reports counts by ticket category, SLA risk, final action, approval status, outbox destination/action, and failure type, plus average latency, tokens, and cost.

The snapshot also includes top risky tickets and recommended operational actions so a support lead can decide what to clear first.

`POST /analytics/weekly-review` writes a Markdown and JSON report under the ignored local reports folder, normally `data/reports/`. The report includes summary metrics, SLA queue highlights, failure drill summary when present, outbox dispatch summary, incident brief paths when present, top risky tickets, and next actions.

These analytics endpoints do not call Azure, Zendesk, Jira, Slack, or any external service. They are local demo surfaces for support leadership review.

## SLO Budget and Optimization Recommendations

`GET /ops/slo-budget` turns the local metrics stream into production-style SLO budget status. It checks deterministic thresholds for agent workflow latency, token usage per run, estimated cost per run, workflow failure count, pending approvals, and outbox dispatch delay. Every metric returns its thresholds, current value, `pass`/`warn`/`fail` status, and an optimization recommendation.

`POST /ops/optimization-report` writes Markdown and JSON under `data/optimization_reports/`. The report packages the same SLO statuses with top slow nodes, high-token nodes, failure hotspots, approval bottlenecks, and recommended fixes. This gives the demo an operator-facing loop from observability to concrete tuning work without requiring external APM, billing, or queueing systems.

## Runbook QA and Operator Readiness Pack

`POST /ops/runbook-qa` evaluates whether a run is complete enough for operator handoff. It checks ticket summary, classification, SLA risk, customer impact, KB citations/context, drafted reply, engineering escalation, approval state, trace ID, outbox dispatches, failure drill result, remediation owners, SLO budget, optimization recommendations, and customer/account health.

The endpoint accepts an optional `run_id`. Without one, it uses the latest local run; if no run exists, it bootstraps a deterministic sample run so a fresh clone can still demonstrate the readiness surface.

`POST /ops/operator-readiness-pack` writes Markdown and JSON under `data/operator_packs/`. The pack includes the Runbook QA result, critical metrics, endpoint list, local demo command, JD skills demonstrated, and five interviewer talking points. It remains local/mock only and reuses existing artifacts instead of calling external systems.

## Local Launch Checklist and Smoke Matrix

`GET /ops/smoke-matrix` is the reviewer-facing smoke surface. It lists the key local endpoints, whether they require an API key, expected status codes, sample `curl.exe` and PowerShell commands, artifact expectations, and a launch readiness summary.

`POST /ops/launch-checklist` writes Markdown and JSON under `data/launch_checklists/`. The checklist packages install and run commands, the API smoke matrix, one-command demo path, eval commands, expected/generated artifacts, troubleshooting notes, JD skills demonstrated, and five interviewer talking points. It remains fully local/mock and is intended to make a fresh GitHub clone easy to demo.

## Portfolio Evidence Index and Interview Pack

`GET /portfolio/evidence-index` is the recruiter/interviewer evidence map. It returns a deterministic Portfolio Evidence score/count and maps JD skill areas to implemented features, endpoints, tests/evals, artifact directories, demo commands, verification commands, and local proof paths. Required coverage includes the stateful workflow, human approval, fake Zendesk/Jira/Slack adapters, retry/failure handling, observability/traces, metrics, launch checklist, KB quality, policy guardrails, replay, and leadership/incident artifacts.

`POST /portfolio/interview-pack` writes Markdown and JSON under `data/portfolio_packs/`. The Interview Pack includes a 3-minute demo script, 8-10 technical talking points, architecture walk-through, failure mode story, local verification commands, metrics/eval summary, artifact inventory, and resume/GitHub README bullets. It remains local/mock only and does not require Azure, OpenAI, Zendesk, Jira, Slack, or any external account.

## Release Candidate Quality Gate and Publish Pack

`GET /release/quality-gate` is the final Release Candidate release gate before publishing the repo. It returns status, score, blockers, warnings, verification checklist, CI/docs/test/eval/demo/API coverage, artifact coverage, local-only runtime notes, and publish readiness.

`POST /release/publish-pack` writes Markdown and JSON under `data/release_packs/`. The GitHub Publish Pack includes the embedded gate, release summary, setup commands, demo commands, verification commands, expected outputs, endpoint inventory, artifact inventory, screenshot/manual verification placeholders, GitHub repo checklist, commit/push readiness notes, recruiter review notes, and known limitations. It remains local/mock only and does not call GitHub or external integrations.

## Reviewer Quickstart and Walkthrough Pack

`GET /reviewer/quickstart` is the minutes-to-review entrypoint. It returns exact local setup commands, run commands, one-command demo, verification commands, endpoint walkthrough order, agent workflow walkthrough, artifact proof map, expected outputs, troubleshooting, role-specific reviewer notes, and local/mock runtime counts.

`POST /reviewer/walkthrough-pack` writes Markdown and JSON under `data/reviewer_packs/`. The Walkthrough Pack includes a recruiter-friendly story, engineer deep-dive path, command checklist, API/workflow proof tour, artifacts to inspect, limitations, GitHub README blurb, and the embedded Reviewer Quickstart. It remains local/mock only and is designed to make GitHub review possible without reading the whole codebase first.

## Artifact Inventory and README Checklist Pack

`GET /artifacts/inventory` is the reviewer-facing index of generated local proof. It returns every expected artifact directory, latest Markdown/JSON files when present, producer endpoint and PowerShell command, ignored status from `.gitignore`, reviewer purpose, file counts, and freshness notes. It includes existing packs such as demo, operator, launch, portfolio, release, reviewer, audit, replay, policy, leadership, KB, incident, account, and optimization artifacts plus `data/artifact_indexes/`.

`POST /artifacts/readme-checklist` writes Markdown and JSON under `data/artifact_indexes/`. The README Checklist Pack includes the Artifact Inventory, README Badge suggestions, README Checklist suggestions, local commands, reviewer proof checklist, and cleanup/regeneration notes. It is deterministic and local/mock only; reviewers can delete `data/artifact_indexes/` and regenerate it with the endpoint or the one-command demo.

## Dashboard Smoke and UI Verification Pack

`GET /ui/dashboard-smoke` is the no-browser dashboard verification surface. It inspects `dashboard/streamlit_app.py` and `app/api/routes.py` for expected Streamlit view labels, endpoint references, generated artifact tabs, local run commands, and limitations. The same checks are available from `scripts/dashboard_smoke.py`, which prints a PASS/FAIL summary plus the checked views and endpoints.

`POST /ui/verification-pack` writes Markdown and JSON under `data/ui_verification/`. The UI Verification Pack includes Dashboard Smoke results, the Streamlit run command, reviewer checklist, screenshot placeholders, troubleshooting notes, and limitations. It remains local/mock only and does not start Streamlit, open a browser, or call external services.

## Runtime Demo Server Pack

`GET /runtime/demo-readiness` is the fresh-clone runtime handoff for reviewers who need to start FastAPI and Streamlit without guessing commands. It returns install and start commands, `scripts/runtime_check.py`, optional `scripts/start_demo.ps1`, expected ports, environment defaults, dependency checks, required-file checks, safe read-only socket/netstat checks, health URLs, smoke URLs, troubleshooting, and known limitations.

`POST /runtime/demo-pack` writes Markdown and JSON under `data/runtime_packs/`. The Runtime Demo Server Pack includes the embedded readiness report, exact start and manual stop commands, health checks, demo flow order, screenshot checklist placeholders, troubleshooting, recruiter explanation, and engineer explanation. It remains local/mock only, never kills processes, and does not call Azure, OpenAI, Zendesk, Jira, Slack, GitHub, or external services.

## Final Handoff and README Consistency

`GET /handoff/final-audit` is the README Consistency final audit. It compares local README endpoint mentions and `docs/api.md` coverage against implemented FastAPI routes, verifies architecture/evaluation/workflow coverage, confirms demo output claims, checks required scripts and the Dashboard Smoke script, verifies generated artifact directory docs for `data/final_handoff/`, and checks local/mock Azure limitation clarity.

`POST /handoff/final-pack` writes Markdown and JSON under `data/final_handoff/`. The Final Handoff Pack includes the final audit results, exact clone/run commands, end-to-end verification order, endpoint inventory summary, artifact inventory summary, dashboard smoke summary, recruiter-facing final README blurb, and limitations. It remains local/mock only and does not call GitHub, Azure, OpenAI, Zendesk, Jira, Slack, or external services.

## On-Call Handoff and Customer Communications

`GET /handoff/on-call-summary` returns the latest or scenario-derived On-Call Handoff. It includes owners, severity, status, SLA deadline, trace links, approval and guardrail status, customer communication readiness, customer update drafts, engineering incident ticket summary, and risk/gap checklist.

`POST /handoff/customer-comms-pack` writes Markdown and JSON under `data/customer_comms_packs/`. The Customer Communications Simulation Pack includes customer update drafts, internal handoff, engineering ticket draft, SLA/customer-impact timeline, approval checklist, trace IDs, local proof commands, and Scenario Dataset coverage for high SLA risk, low-confidence approval pause, tool failure/retry, billing/privacy, and outage/API incidents. It is local/mock only and drafts communications without dispatching to Zendesk, Jira, Slack, Azure, OpenAI, GitHub, or external services.

## Postmortem RCA and Corrective Actions

`GET /incidents/postmortem-summary` returns the latest or deterministic sample Postmortem RCA summary. It connects tickets, runs, traces, approvals, outbox/customer comms state, on-call handoff readiness, and Scenario Dataset coverage into incident summary, severity, timeline, root cause category, contributing factors, impacted customer/account, approval/comms status, trace links, corrective actions, recurrence risk, customer follow-up state, readiness, and proof commands.

`POST /incidents/rca-pack` writes Markdown and JSON under `data/rca_packs/`. The pack includes postmortem narrative, timeline, trace/audit evidence, corrective action owners, due dates, recurrence risk, customer follow-up state, proof commands, limitations, and deterministic RCA coverage for outage/API incident, tool failure/retry, privacy/data export, billing/customer risk, and low-confidence ambiguity needing human review.

## Git Readiness and Branch Hygiene

`GET /git/readiness` is the local GitHub Push Readiness gate. It uses only read-only git inspection to report repo detection, current branch, tracked/untracked/modified/ignored summary, generated artifact directories that should stay ignored, source/doc/test/dashboard files changed, suspicious large/generated files, GitHub Actions workflow presence, README final handoff mention, `.env.example`, dirty-worktree guidance, and recommended commit groups.

`POST /git/push-plan` writes Markdown and JSON under `data/git_packs/`. The Branch Hygiene Pack includes exact non-destructive review commands, suggested commit grouping, do-not-commit generated artifact notes, pre-push verification checklist, repo limitations, and a recruiter/GitHub README publish blurb. It remains local/mock only and does not stage, commit, push, reset, checkout, clean, delete files, or call GitHub APIs.

## CI Doctor and Audit Pack

`GET /ops/ci-doctor` is the local maintainability doctor for the repository itself. It checks that the pytest, ruff, eval, and demo commands are represented; GitHub Actions and Docker Compose are present; `.env.example`, README sections, docs, generated artifact ignores, and dependency files are in place; local/mock provider notes are documented; and a suspicious secret-pattern scan can be reviewed.

The secret scan is deliberately local and redacted. It scans committed repo surfaces, skips generated or environment-heavy folders such as `data/`, `.git/`, `.venv/`, `.pytest_cache/`, and `.ruff_cache/`, and reports only file, line, pattern name, and a redacted snippet. It is useful for publish readiness, but it is not a substitute for production-grade CI secret scanning.

`POST /ops/audit-pack` writes Markdown and JSON under `data/audit_packs/`. The Audit Pack embeds the CI Doctor result, dependency inventory, secret scan summary, local verification commands, publish-safety checklist, remediation notes, and recruiter/interviewer explanation. It remains fully local/mock and does not call GitHub, PyPI, vulnerability databases, or external secret-scanning services.

## Change Risk Simulator and Escalation Replay Lab

Replay Lab is a deterministic counterfactual layer over stored run state. It does not call Zendesk, Jira, Slack, Azure, OpenAI, or the fake adapters. Instead, it clones a past run, applies scenario modifiers, recomputes operator-facing risk decisions, and returns an original-vs-replay comparison.

Supported modifiers are:

- `sla_pressure`: `normal`, `high`, or `critical`
- `kb_context`: `full`, `missing`, or `conflicting`
- `adapter_health`: `healthy`, `degraded`, or `failing`
- `confidence_override`: optional float from `0.0` to `1.0`
- `approval_policy`: `strict`, `standard`, or `auto_internal_only`

`POST /runs/{run_id}/replay-lab` targets one run. `POST /replay-lab/run` can accept a `run_id`, use the latest local run, or bootstrap a deterministic sample. The response compares classification, SLA risk, final action, approval requirement, failure state, tool attempts, latency/token/cost estimates, changed decisions, risk score, and recommended operator action.

`POST /replay-lab/report` writes Markdown and JSON under `data/replay_reports/` with modifiers, trace IDs, risk flags, local verification commands, JD skills demonstrated, and five interviewer talking points. This lets operators ask, "Would this automation change still be safe if the KB were missing, SLA pressure rose, or the adapter degraded?"

## Agent Policy Guardrail Center

The Policy Guardrail Center turns the run and Replay Lab context into an approval policy decision for automation actions. It is deterministic and local-only: no external policy engine, Azure service, Zendesk, Jira, or Slack account is required.

`POST /policies/simulate` accepts an optional `run_id`, Replay Lab `modifiers`, `requested_actions`, and `replay_risk_threshold`. Without a `run_id`, it uses the latest local run or bootstraps the same deterministic sample path used by Replay Lab.

Default approval policy rules evaluate:

- low confidence
- high or critical SLA pressure
- enterprise or VIP customer tier
- external customer reply/Zendesk update vs internal Jira, Slack, and engineering escalation actions
- degraded or failing adapter health
- Replay Lab risk above threshold
- missing or conflicting KB context

The response returns the policy decision, required approval type, approval chain, blocked actions, allowed actions, matched rules with evidence, warnings, and recommended operator action.

`POST /policies/export` writes Markdown and JSON under `data/policy_packs/`. The pack includes simulated policies, matched rules, approval matrix, sample scenario outcomes, local verification commands, JD skills demonstrated, and five interviewer talking points so support managers can explain why an automation policy would or would not be approved.

## Customer Impact Timeline and Executive Incident Narrative

`POST /incidents/timeline` is the executive story layer over the local control tower evidence. It accepts an optional `run_id`; without one, it uses the latest local run or bootstraps a deterministic sample incident. The service builds a time-ordered Customer Impact Timeline from the ticket, workflow trace, human approvals, outbox dispatches, incident brief, remediation checklist, weekly review, account brief, SLO posture, Replay Lab output, and policy guardrail decision.

The timeline response separates internal owner work from external customer-visible actions, annotates the story with policy and replay risk, lists unresolved risks, suggests owner next steps, and links the evidence artifacts that were generated locally.

`POST /incidents/executive-narrative` writes Markdown and JSON under `data/incident_narratives/`. The export includes executive summary, timeline, customer impact, decisions made, approval evidence, policy guardrail decision, replay risk, SLO posture, owner actions, local commands, JD skills demonstrated, and five interviewer talking points. It remains fully local/mock and does not call external systems.

## Leadership Scorecard and Review Pack

`GET /leadership/scorecard` is the executive automation KPI layer over the local corpus. It aggregates tickets, runs, traces, approvals, outbox dispatches, drills, ops analytics, SLO budget, customer health, Replay Lab, policy guardrails, incident artifacts, and operator readiness into deterministic category scores.

The scorecard categories are automation safety, approval health, SLA risk, escalation quality, retry/failure behavior, policy blocks, replay risk, customer impact, and operator readiness. Each category returns a 0-100 score, status, local sample values, risk flags, and recommended actions. The response also includes trend-ish local values, artifact links, KPI definitions, local commands, and an overall readiness status for support leadership.

`POST /leadership/review-pack` writes Markdown and JSON under `data/leadership_reviews/`. The pack includes the scorecard, KPI definitions, local evidence links, top risks, next actions, verification commands, JD skills demonstrated, and five interviewer talking points. It remains fully local/mock; no BI warehouse, CRM, Zendesk, Jira, Slack, Azure, or OpenAI dependency is required.

## Knowledge Quality Auditor and KB Refresh Plan

`GET /knowledge/quality-audit` is the support-lead view of whether the internal KB is ready for agentic escalation. It reads the sample KB snippets, stored workflow `kb_results`, ticket categories, Replay Lab KB-context modifiers, policy guardrail grounding rules, incident narrative artifacts, and Leadership Scorecard signals.

The audit returns a deterministic coverage score, freshness/coverage/citation/conflict metrics, weak or missing articles, impacted ticket types, owner recommendations, risk flags, and readiness status. It treats missing review dates, missing citations, policy conflicts, missing workflow grounding, and high-impact incident/API/auth/security gaps as readiness risks.

`POST /knowledge/refresh-plan` writes Markdown and JSON under `data/kb_refresh_plans/`. The export converts audit findings into owner-ready article refresh tasks with owners, acceptance criteria, impacted workflows, local commands, JD skills demonstrated, and five interviewer talking points. It remains fully local/mock and does not call an external KB, search index, or document system.

## Customer Health and Account Brief

`GET /customers/health` groups local tickets by explicit `customer` or `account` metadata, falling back to a readable email-domain account for older tickets. When an account exists in `sample_data/customers.json`, the summary includes segment, tier, and region metadata.

The health score is deterministic and local. It starts at 100 and subtracts weighted risk points for open/analyzing work, pending approval, escalated tickets, high SLA risk, recent workflow failures, and active playbook recommendations. Scores map to `healthy`, `watch`, `at_risk`, or `critical`, with a recommended action for customer success and support leadership.

`POST /customers/{customer_id_or_name}/account-brief` writes Markdown and JSON under `data/account_briefs/`. The brief packages the account health row with active tickets, recent runs, recommended playbooks, pending approvals, outbox summary, and next actions. It reuses the same local state as tickets, approvals, outbox, playbooks, and runs, so no CRM or external support tool is required.

## Routing

High-SLA-risk tickets draft an engineering escalation. Low-confidence or risky actions also require approval. Because all outbound customer and engineering actions require approval, the approval gate is universal by design.
