# Architecture

The control tower is organized as an async FastAPI application with explicit service boundaries.

## Components

- **FastAPI API layer** exposes ticket, run, approval, metrics, audit, and health endpoints.
- **AgentWorkflowService** owns the LangGraph workflow and run lifecycle.
- **TicketService** persists and lists support tickets.
- **KnowledgeRetrievalService** retrieves KB context with retry/failure handling.
- **KnowledgeQualityService** audits KB readiness across sample articles, workflow retrieval evidence, ticket categories, replay modifiers, policy guardrails, incident narratives, and leadership scorecard signals, then exports KB refresh plans.
- **ApprovalService** creates and resolves human approval gates.
- **TraceService** persists node transitions, tool calls, latency, and failures.
- **MetricsService** aggregates node counts, latency, token use, and estimated cost.
- **RunbookQaService** evaluates operator handoff readiness across run state, traces, approvals, outbox records, drills, SLOs, and generated artifacts, then exports readiness packs.
- **LaunchChecklistService** packages reviewer setup, smoke checks, demo commands, eval commands, artifacts, troubleshooting, JD skills, and talking points into a local launch checklist.
- **PortfolioService** builds the Portfolio Evidence Index and writes the Interview Pack that maps JD skills to features, endpoints, tests/evals, artifacts, commands, and proof paths.
- **ReleaseService** builds the Release Candidate quality gate and writes the GitHub Publish Pack that combines release gate status, coverage, verification commands, expected outputs, endpoint inventory, artifact inventory, screenshot placeholders, commit/push notes, recruiter notes, and known limitations.
- **ReviewerService** builds the Reviewer Quickstart and writes the Walkthrough Pack that combines exact setup commands, one-command demo, verification commands, endpoint walkthrough order, agent workflow walkthrough, artifact proof map, recruiter story, engineer proof tour, GitHub README blurb, and limitations.
- **ArtifactInventoryService** indexes ignored generated artifact directories and writes the README Checklist Pack with badge suggestions, local commands, reviewer proof checklist, and regeneration notes.
- **UIVerificationService** runs Dashboard Smoke source checks for Streamlit tabs, endpoint references, generated artifact tabs, local run commands, and limitations, then writes the UI Verification Pack.
- **FinalHandoffService** runs the README Consistency Final Audit and writes the Final Handoff Pack that reconciles README/docs/API/demo/dashboard claims with implemented endpoints, scripts, artifact docs, and local/mock limitations.
- **OnCallHandoffService** builds the On-Call Handoff summary and Customer Communications Simulation Pack from tickets, runs, traces, approvals, guardrails, SLA deadlines, and Scenario Dataset coverage.
- **PostmortemRcaService** turns local escalation evidence into a Postmortem RCA summary and Corrective Action Tracking Pack with root cause category, contributing factors, action owners, due dates, recurrence risk, customer follow-up state, trace/audit links, and RCA scenario coverage.
- **GitReadinessService** runs read-only local git inspection for GitHub Push Readiness and Branch Hygiene, then writes the Push Plan with commit grouping and pre-push verification guidance.
- **RuntimeDemoService** returns fresh-clone runtime readiness for FastAPI and Streamlit, including source checks, dependency checks, safe read-only port/process checks, commands, health URLs, and Runtime Demo Server Pack exports.
- **ScenarioCatalogService** reads the enterprise fake scenario dataset, exposes expected outcome coverage, runs deterministic checks, and writes Scenario Dataset Eval Coverage Pack artifacts.
- **OpsService CI Doctor** inspects local repo files for CI commands, docs, Docker, env examples, dependency manifests, ignored generated artifacts, local/mock provider notes, and redacted secret scan findings, then writes Dependency/Secrets Audit Pack artifacts.
- **ReplayLabService** performs deterministic counterfactual replay over stored run state for Change Risk / Escalation Replay scenarios and exports Markdown/JSON reports.
- **PolicyGuardrailService** evaluates approval policy rules over run context, Replay Lab findings, requested automation actions, customer tier, adapter health, confidence, SLA pressure, and KB grounding, then exports policy packs.
- **IncidentNarrativeService** composes ticket, trace, approval, outbox, brief, checklist, weekly review, account health, SLO, replay, and policy evidence into a Customer Impact Timeline and Executive Incident Narrative.
- **LeadershipScorecardService** aggregates the local evidence corpus into automation KPI category scores, readiness status, risk flags, recommended actions, and Markdown/JSON leadership review packs.
- **AuditService** records operational events.
- **Adapters** isolate fake Zendesk, Jira, Slack, KB, and LLM provider behavior.

## Persistence

The default persistence layer is a local SQLite database configured by `CONTROL_TOWER_STATE_FILE`. The app stores one versioned state document in SQLite for the local portfolio runtime, while the service boundary keeps the project ready for a more normalized Postgres repository later. It stores:

- tickets
- workflow runs
- trace events
- approvals
- audit events
- aggregate metrics
- generated artifact paths under ignored `data/` folders, including `data/operator_packs/`
- Replay Lab reports under ignored `data/replay_reports/`
- Policy Guardrail packs under ignored `data/policy_packs/`
- Executive incident narratives under ignored `data/incident_narratives/`
- Leadership review packs under ignored `data/leadership_reviews/`
- KB refresh plans under ignored `data/kb_refresh_plans/`
- Local launch checklists under ignored `data/launch_checklists/`
- Portfolio Interview Pack artifacts under ignored `data/portfolio_packs/`
- Release Candidate Publish Pack artifacts under ignored `data/release_packs/`
- Reviewer Walkthrough Pack artifacts under ignored `data/reviewer_packs/`
- CI Doctor / Audit Pack artifacts under ignored `data/audit_packs/`
- Artifact Inventory / README Checklist Pack artifacts under ignored `data/artifact_indexes/`
- Dashboard Smoke / UI Verification Pack artifacts under ignored `data/ui_verification/`
- Final Handoff Pack artifacts under ignored `data/final_handoff/`
- Customer Communications Simulation Pack artifacts under ignored `data/customer_comms_packs/`
- GitHub Push Readiness / Branch Hygiene artifacts under ignored `data/git_packs/`
- Runtime Demo Server Pack artifacts under ignored `data/runtime_packs/`
- Scenario Dataset Eval Coverage Pack artifacts under ignored `data/scenario_packs/`
- Postmortem RCA + Corrective Action Tracking Pack artifacts under ignored `data/rca_packs/`

This keeps local setup dependency-free while still using a real durable database that persists state across process restarts.

## Provider Boundary

The project runs locally with `LocalMockLlmProvider`. Optional OpenAI or Azure OpenAI adapters can be added behind `LlmProvider` without changing workflow nodes.

## Security and Observability

All business endpoints require `x-api-key` or `Authorization: Bearer`. `/health` and `/auth/demo-token` are open for local demo use.

Every request gets an `x-trace-id`. Workflow runs get their own durable trace ID and trace events for node starts, node completions, tool calls, errors, latency, token use, cost, final action, and failure state.

Runbook QA is an observability consumer rather than another external integration. It reads local state and generated artifacts, can bootstrap a deterministic sample when no run exists, and never calls real Zendesk, Jira, Slack, Azure, or OpenAI services.

Replay Lab follows the same local-only boundary. It clones saved run state, applies scenario modifiers for SLA pressure, KB context, adapter health, confidence, and approval policy, then compares original and replay outcomes without invoking adapters or external providers.

The Policy Guardrail Center is also local-only. It uses deterministic policy rules rather than an external policy engine, and separates customer-visible replies from internal Jira, Slack, and engineering escalation actions so managers can preview approval policy behavior before automation changes ship.

The Incident Narrative service is a local evidence composer. It may generate missing local artifacts, but it only calls existing deterministic services and writes Markdown/JSON under ignored `data/incident_narratives/`.

The Leadership Scorecard is the executive reporting consumer over the same local state. It does not require external BI or a warehouse; it combines tickets, runs, traces, approvals, outbox, eval-style drills, SLOs, Replay Lab, policy guardrails, customer health, and operator readiness into deterministic automation KPI scores and exports review packs under ignored `data/leadership_reviews/`.

The Knowledge Quality Auditor is the KB governance consumer over the same corpus. It remains local-only, reads the sample KB and stored retrieval outputs, folds in Replay Lab missing/conflicting KB context, policy grounding rules, incident narrative evidence, and leadership readiness signals, then exports owner-ready KB refresh plans under ignored `data/kb_refresh_plans/`.

The Launch Checklist service is the GitHub reviewer handoff. It does not execute external checks; it deterministically lists the local smoke matrix, expected status codes, sample commands, artifact-producing endpoints, eval commands, troubleshooting notes, and generated artifact expectations, then writes Markdown/JSON under ignored `data/launch_checklists/`.

The Portfolio Evidence service is the recruiter/interviewer handoff. It does not execute external calls; it indexes local code, docs, tests, eval commands, endpoints, generated artifact directories, and proof paths into `GET /portfolio/evidence-index`, then writes a Markdown/JSON Interview Pack under ignored `data/portfolio_packs/`. This makes a fresh clone reviewable even before optional demo artifacts have been generated.

The Release Candidate service is the final GitHub publish handoff. It does not run shell commands or call GitHub; it deterministically inspects local repo files, route wiring, docs, tests, eval/demo hooks, CI workflow presence, `.gitignore`, endpoint inventory, and artifact definitions. `GET /release/quality-gate` returns the release gate status, score, blockers, warnings, coverage, local-only runtime notes, and publish readiness. `POST /release/publish-pack` writes the Markdown/JSON Publish Pack under ignored `data/release_packs/` for reviewer and recruiter handoff.

The Reviewer Quickstart service is the practical fresh-clone handoff. It does not run commands or call external services; `GET /reviewer/quickstart` returns exact setup, run, demo, verification, endpoint, workflow, artifact, troubleshooting, and role-specific review guidance. `POST /reviewer/walkthrough-pack` writes the Markdown/JSON Walkthrough Pack under ignored `data/reviewer_packs/`, including a recruiter-friendly story, engineer deep-dive path, command checklist, API/workflow proof tour, artifacts to inspect, limitations, and a GitHub README blurb.

The Artifact Inventory service is the final GitHub review table of contents. It does not execute producers or call external systems; `GET /artifacts/inventory` inspects configured local artifact folders, reports latest Markdown/JSON files, producer endpoints and commands, `.gitignore` ignored status, reviewer purpose, and freshness notes. `POST /artifacts/readme-checklist` writes the Markdown/JSON README Checklist Pack under ignored `data/artifact_indexes/`, including badge suggestions, README checklist suggestions, local commands, a reviewer proof checklist, and cleanup/regeneration notes.

The UI Verification service is the dashboard handoff for reviewers who want deterministic proof without opening a browser. `GET /ui/dashboard-smoke` inspects `dashboard/streamlit_app.py` and `app/api/routes.py` for expected view labels, endpoint references, and generated artifact tabs. `POST /ui/verification-pack` writes the Markdown/JSON UI Verification Pack under ignored `data/ui_verification/`, including Dashboard Smoke results, Streamlit run command, reviewer checklist, screenshot placeholders, troubleshooting, and limitations.

The Final Handoff service is the README Consistency gate for the final portfolio handoff. `GET /handoff/final-audit` inspects local README, docs/api, architecture/evaluation/workflow docs, demo output wiring, scripts, Dashboard Smoke wiring, generated artifact directory docs, and local/mock Azure limitation clarity. `POST /handoff/final-pack` writes the Markdown/JSON Final Handoff Pack under ignored `data/final_handoff/`, including final audit results, exact clone/run commands, end-to-end verification order, endpoint inventory summary, artifact inventory summary, dashboard smoke summary, recruiter-facing README blurb, and limitations. It remains local/mock only and does not call GitHub, Azure, OpenAI, Zendesk, Jira, Slack, or external services.

The On-Call Handoff service is the operational communications gate. `GET /handoff/on-call-summary` returns latest or scenario-derived owners, severity, status, SLA deadline, trace links, approval/guardrail status, customer communication readiness, customer update drafts, engineering incident ticket summary, and risk/gap checklist. `POST /handoff/customer-comms-pack` writes Markdown/JSON under ignored `data/customer_comms_packs/` with customer updates, internal handoff, engineering ticket draft, SLA/customer-impact timeline, approval checklist, trace IDs, local proof commands, and coverage across Scenario Dataset paths for high SLA risk, low-confidence approval pause, tool failure/retry, billing/privacy, and outage/API incidents. It remains local/mock only and does not dispatch customer communications or call Azure, OpenAI, Zendesk, Jira, Slack, GitHub, or external services.

The Postmortem RCA service is the operational learning layer after escalation handling. `GET /incidents/postmortem-summary` composes the latest or supplied local run evidence into incident summary, severity, timeline, root cause category, contributing factors, impacted customer/account, approval/comms status, trace links, corrective actions, recurrence risk, and readiness. `POST /incidents/rca-pack` writes Markdown/JSON under ignored `data/rca_packs/` with postmortem narrative, trace/audit evidence, owner and due-date tables, customer follow-up state, proof commands, limitations, and deterministic coverage for outage/API, tool failure/retry, privacy/data export, billing/customer risk, and low-confidence human-review scenarios.

The Git Readiness service is the final local Branch Hygiene layer before a human manually stages anything. `GET /git/readiness` uses only read-only git commands such as status, branch, rev-parse, ls-files, and check-ignore to report repo detection, current branch, dirty-worktree summary, ignored generated artifacts, suspicious large/generated files, required GitHub Actions workflow presence, README final handoff mention, `.env.example`, and recommended commit groups. `POST /git/push-plan` writes the GitHub Push Readiness + Branch Hygiene Pack under ignored `data/git_packs/`, including exact non-destructive review commands, do-not-commit generated artifact notes, pre-push checklist, limitations, and recruiter/GitHub README publish blurb. It does not stage, commit, push, reset, checkout, clean, delete files, or call GitHub APIs.

The Runtime Demo service is the fresh-clone local server handoff. `GET /runtime/demo-readiness` is public and read-only so reviewers can inspect exact commands, expected ports, environment defaults, dependency and file checks, safe socket/netstat checks, health URLs, smoke URLs, troubleshooting, and limitations before they have a token. `POST /runtime/demo-pack` writes the Markdown/JSON Runtime Demo Server Pack under ignored `data/runtime_packs/` with start/stop commands, health checks, demo flow order, screenshot placeholders, and recruiter/engineer explanations. It never kills processes and does not require Azure, OpenAI, Zendesk, Jira, Slack, GitHub, or external services.

The Scenario Dataset service makes eval coverage less dependent on one golden path. `GET /scenarios/catalog` reads `sample_data/scenarios.json` and returns scenario coverage, expected classification/SLA/approval/escalation outcomes, low-confidence review expectations, and failure/tool-retry expectations. `POST /scenarios/eval-pack` runs those fixtures through the local workflow and writes Markdown/JSON under ignored `data/scenario_packs/` with accuracy, coverage, gaps, warnings, and artifact paths.

The CI Doctor extends that maintainability surface with a narrower dependency/secrets audit. `GET /ops/ci-doctor` reads only local files and returns structured checks for pytest, ruff, eval, demo, GitHub Actions, Docker Compose, `.env.example`, README sections, docs presence, generated artifact ignores, dependency files, local/mock provider notes, and a suspicious secret-pattern scan summary. The secret scan redacts matched values and skips generated folders such as `data/`, `.git/`, and `.venv/`. `POST /ops/audit-pack` writes the Markdown/JSON Audit Pack under ignored `data/audit_packs/`. It does not call GitHub, PyPI, external vulnerability databases, or secret-scanning services.
