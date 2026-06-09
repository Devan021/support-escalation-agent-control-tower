import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore
from app.services.launch_checklist import EVAL_COMMANDS, EXPECTED_ARTIFACTS


DEMO_COMMANDS = [
    r".\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000",
    r".\.venv\Scripts\streamlit.exe run dashboard\streamlit_app.py",
    r".\.venv\Scripts\python.exe scripts\demo_run.py",
]

LOCAL_VERIFICATION_COMMANDS = [
    *EVAL_COMMANDS,
    (
        r'rg "portfolio/evidence-index|portfolio/interview-pack|Portfolio Evidence|'
        r'Interview Pack|portfolio_packs|evidence score" app dashboard docs README.md tests scripts'
    ),
    (
        r"Get-ChildItem -Recurse -File data\portfolio_packs -ErrorAction SilentlyContinue "
        r"| Select-Object FullName,Length,LastWriteTime"
    ),
]

JD_EVIDENCE = [
    {
        "skill_id": "stateful_agent_workflow",
        "jd_skill": "LangGraph/stateful workflow orchestration",
        "implemented_features": [
            "AgentWorkflowService stores typed run state, node history, decisions, and final actions.",
            "Workflow nodes cover intake classification, SLA scoring, KB retrieval, drafting, QA, approval, and dispatch.",
        ],
        "endpoints": ["POST /tickets/{ticket_id}/analyze", "GET /runs/{run_id}"],
        "tests_evals": [
            "tests/test_api.py::test_analyze_trace_and_approval",
            "app/evals/run_eval.py",
        ],
        "artifacts": ["data/demo_packs", "data/operator_packs"],
        "local_proof_paths": [
            "app/services/workflow.py",
            "app/models/entities.py",
            "docs/workflow.md",
        ],
    },
    {
        "skill_id": "human_approval",
        "jd_skill": "Human approval and controlled automation",
        "implemented_features": [
            "Risky runs pause with approval records before customer-visible or escalation actions dispatch.",
            "Approval and rejection endpoints preserve reviewer identity and notes.",
        ],
        "endpoints": ["GET /approvals", "POST /runs/{run_id}/approve", "POST /runs/{run_id}/reject"],
        "tests_evals": [
            "tests/test_api.py::test_approval_dispatch_writes_outbox",
            "tests/test_policy_guardrails.py",
        ],
        "artifacts": ["data/operator_packs", "data/policy_packs"],
        "local_proof_paths": [
            "app/services/approvals.py",
            "app/services/workflow.py",
            "dashboard/streamlit_app.py",
        ],
    },
    {
        "skill_id": "fake_integrations",
        "jd_skill": "Fake Zendesk/Jira/Slack adapters for local-safe demos",
        "implemented_features": [
            "Outbox records Zendesk, Jira, Slack, engineering escalation, and customer reply payloads locally.",
            "Fake adapters and sample fixtures make fresh-clone demos deterministic without credentials.",
        ],
        "endpoints": ["GET /integrations/outbox", "GET /integrations/outbox/{outbox_id}"],
        "tests_evals": ["tests/test_api.py::test_approval_dispatch_writes_outbox"],
        "artifacts": ["data/demo_packs", "data/leadership_reviews"],
        "local_proof_paths": [
            "app/adapters/fake.py",
            "app/services/outbox.py",
            "sample_data/adapter_fixtures.json",
        ],
    },
    {
        "skill_id": "retry_failure_handling",
        "jd_skill": "Retry and failure handling",
        "implemented_features": [
            "Knowledge retrieval retries failed tool calls and records failure state after exhaustion.",
            "Tool failure drill proves degraded paths still pause for human review.",
        ],
        "endpoints": ["POST /drills/tool-failure", "GET /metrics/agent-performance"],
        "tests_evals": [
            "tests/test_api.py::test_failure_drill_retries_and_pauses_for_review",
            "tests/test_retrieval_retry_metrics.py",
        ],
        "artifacts": ["data/operator_packs", "data/optimization_reports"],
        "local_proof_paths": [
            "app/services/knowledge.py",
            "app/services/drills.py",
            "docs/evaluation.md",
        ],
    },
    {
        "skill_id": "observability_metrics",
        "jd_skill": "Observability, traces, metrics, and audit evidence",
        "implemented_features": [
            "Trace events capture node, status, latency, token, and cost estimates for every run.",
            "Metrics, audit events, SLO budget, and ops analytics expose reviewer-friendly evidence.",
        ],
        "endpoints": [
            "GET /runs/{run_id}/trace",
            "GET /metrics/agent-performance",
            "GET /audit/events",
            "GET /ops/slo-budget",
        ],
        "tests_evals": [
            "tests/test_api.py::test_metrics_and_audit",
            "tests/test_api.py::test_slo_budget_and_optimization_report",
        ],
        "artifacts": ["data/reports", "data/optimization_reports"],
        "local_proof_paths": [
            "app/services/trace.py",
            "app/services/metrics.py",
            "app/services/ops.py",
            "docs/architecture.md",
        ],
    },
    {
        "skill_id": "launch_readiness",
        "jd_skill": "Launch checklist and smoke-test readiness",
        "implemented_features": [
            "Smoke matrix lists protected endpoints, expected statuses, commands, and artifact expectations.",
            "Launch checklist packages fresh-clone setup, eval commands, troubleshooting, and reviewer talking points.",
        ],
        "endpoints": ["GET /ops/smoke-matrix", "POST /ops/launch-checklist"],
        "tests_evals": ["tests/test_api.py::test_smoke_matrix_and_launch_checklist_export"],
        "artifacts": ["data/launch_checklists"],
        "local_proof_paths": [
            "app/services/launch_checklist.py",
            "README.md",
            "docs/api.md",
        ],
    },
    {
        "skill_id": "kb_quality",
        "jd_skill": "Knowledge-base quality and grounding",
        "implemented_features": [
            "KB quality audit scores coverage, freshness, citations, conflicts, and impacted ticket types.",
            "Refresh plan converts audit findings into owner-ready local Markdown and JSON tasks.",
        ],
        "endpoints": ["GET /knowledge/quality-audit", "POST /knowledge/refresh-plan"],
        "tests_evals": ["tests/test_knowledge_quality.py"],
        "artifacts": ["data/kb_refresh_plans"],
        "local_proof_paths": [
            "app/services/knowledge.py",
            "sample_data/kb_articles.json",
            "docs/evaluation.md",
        ],
    },
    {
        "skill_id": "policy_guardrails",
        "jd_skill": "Policy guardrails and approval policy simulation",
        "implemented_features": [
            "Policy simulator blocks or gates risky customer-visible and internal actions.",
            "Exported policy pack explains matched rules, approval chain, blocked actions, and replay risk.",
        ],
        "endpoints": ["POST /policies/simulate", "POST /policies/export"],
        "tests_evals": ["tests/test_policy_guardrails.py"],
        "artifacts": ["data/policy_packs"],
        "local_proof_paths": [
            "app/services/policy_guardrails.py",
            "docs/workflow.md",
        ],
    },
    {
        "skill_id": "replay_lab",
        "jd_skill": "Replay and counterfactual risk analysis",
        "implemented_features": [
            "Replay Lab replays stored runs under SLA, KB, adapter, confidence, and approval modifiers.",
            "Reports compare changed decisions, risk flags, tool attempts, and recommended operator action.",
        ],
        "endpoints": [
            "POST /runs/{run_id}/replay-lab",
            "POST /replay-lab/run",
            "POST /replay-lab/report",
        ],
        "tests_evals": ["tests/test_api.py::test_replay_lab_detects_changed_decisions"],
        "artifacts": ["data/replay_reports"],
        "local_proof_paths": [
            "app/services/replay_lab.py",
            "docs/workflow.md",
            "docs/evaluation.md",
        ],
    },
    {
        "skill_id": "leadership_incident_artifacts",
        "jd_skill": "Leadership and incident artifacts",
        "implemented_features": [
            "Incident narratives, Postmortem RCA packs, leadership scorecards, weekly reviews, and account briefs connect agent evidence to business outcomes.",
            "Demo evidence pack ties the full scenario to generated Markdown and JSON proof paths.",
        ],
        "endpoints": [
            "POST /incidents/executive-narrative",
            "GET /incidents/postmortem-summary",
            "POST /incidents/rca-pack",
            "GET /leadership/scorecard",
            "POST /leadership/review-pack",
            "POST /demo/evidence-pack",
        ],
        "tests_evals": [
            "tests/test_incident_narrative.py",
            "tests/test_postmortem_rca.py",
            "tests/test_leadership.py",
            "tests/test_api.py::test_demo_evidence_pack_writes_markdown_and_json",
        ],
        "artifacts": [
            "data/incident_narratives",
            "data/rca_packs",
            "data/leadership_reviews",
            "data/demo_packs",
        ],
        "local_proof_paths": [
            "app/services/incident_narrative.py",
            "app/services/postmortem_rca.py",
            "app/services/leadership.py",
            "app/services/demo.py",
        ],
    },
]


class PortfolioService:
    def __init__(self, store: JsonStateStore, portfolio_packs_dir: Path):
        self.store = store
        self.portfolio_packs_dir = portfolio_packs_dir
        self.data_root = portfolio_packs_dir.parent
        self.repo_root = Path(__file__).resolve().parents[2]

    async def evidence_index(self) -> dict[str, Any]:
        state = await self.store.load()
        evidence_items = [self._with_item_score(item) for item in JD_EVIDENCE]
        covered = len([item for item in evidence_items if item["coverage_status"] == "covered"])
        score = round((covered / len(evidence_items)) * 100)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "local-deterministic-portfolio-evidence",
            "local_mock_only": True,
            "portfolio_title": "Portfolio Evidence Index",
            "evidence_score": score,
            "evidence_count": len(evidence_items),
            "covered_skill_count": covered,
            "summary": (
                "Deterministic local index mapping recruiter JD skills to implementation, API, "
                "test, eval, artifact, command, and proof-path evidence."
            ),
            "fresh_clone_ready": True,
            "runtime_snapshot": self._runtime_snapshot(state),
            "demo_commands": DEMO_COMMANDS,
            "verification_commands": LOCAL_VERIFICATION_COMMANDS,
            "jd_skill_evidence": evidence_items,
            "artifact_inventory": self._artifact_inventory(),
            "local_proof_paths": sorted({path for item in evidence_items for path in item["local_proof_paths"]}),
        }

    async def export_interview_pack(self) -> dict[str, Any]:
        evidence = await self.evidence_index()
        generated_at = datetime.now(timezone.utc)
        pack_id = f"portfolio_interview_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "title": "Interview Pack",
            "evidence_score": evidence["evidence_score"],
            "evidence_count": evidence["evidence_count"],
            "three_minute_demo_script": self._demo_script(evidence),
            "technical_talking_points": self._technical_talking_points(evidence),
            "architecture_walkthrough": self._architecture_walkthrough(),
            "failure_mode_story": self._failure_mode_story(),
            "local_verification_commands": LOCAL_VERIFICATION_COMMANDS,
            "metrics_eval_summary": self._metrics_eval_summary(evidence),
            "artifact_inventory": evidence["artifact_inventory"],
            "resume_github_readme_bullets": self._resume_bullets(evidence),
            "evidence_index": evidence,
        }
        markdown = self._markdown(pack)
        self.portfolio_packs_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.portfolio_packs_dir / f"{pack_id}.json"
        markdown_path = self.portfolio_packs_dir / f"{pack_id}.md"
        pack["artifact_paths"] = {
            "portfolio_interview_pack_json": str(json_path),
            "portfolio_interview_pack_markdown": str(markdown_path),
        }
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "evidence_score": evidence["evidence_score"],
            "evidence_count": evidence["evidence_count"],
            "pack": pack,
            "markdown": markdown,
        }

    def _with_item_score(self, item: dict[str, Any]) -> dict[str, Any]:
        proof_exists = [path for path in item["local_proof_paths"] if self._repo_path(path).exists()]
        endpoints = item["endpoints"]
        tests = item["tests_evals"]
        artifacts = [
            {
                "directory": artifact,
                "latest_path": self._latest_path(Path(artifact)),
                "producer_hint": self._producer_for_artifact(artifact),
            }
            for artifact in item["artifacts"]
        ]
        checklist = {
            "features": bool(item["implemented_features"]),
            "endpoints": bool(endpoints),
            "tests_evals": bool(tests),
            "artifacts": bool(artifacts),
            "proof_paths": len(proof_exists) == len(item["local_proof_paths"]),
        }
        item_score = round((sum(1 for value in checklist.values() if value) / len(checklist)) * 100)
        return {
            **item,
            "demo_commands": DEMO_COMMANDS,
            "verification_commands": LOCAL_VERIFICATION_COMMANDS,
            "artifact_outputs": artifacts,
            "proof_path_status": [
                {"path": path, "exists": self._repo_path(path).exists()}
                for path in item["local_proof_paths"]
            ],
            "coverage_checklist": checklist,
            "item_score": item_score,
            "coverage_status": "covered" if item_score >= 80 else "partial",
        }

    def _runtime_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticket_count": len(state.get("tickets", {})),
            "run_count": len(state.get("runs", {})),
            "trace_count": len(state.get("traces", {})),
            "approval_count": len(state.get("approvals", {})),
            "outbox_dispatch_count": len(state.get("outbox", {})),
            "drill_count": len(state.get("drills", {})),
            "latest_artifacts": self._artifact_inventory()[:8],
        }

    def _repo_path(self, relative_path: str) -> Path:
        return self.repo_root / relative_path

    def _artifact_inventory(self) -> list[dict[str, Any]]:
        inventory = []
        for artifact in EXPECTED_ARTIFACTS:
            directory = artifact["directory"]
            inventory.append(
                {
                    **artifact,
                    "latest_path": self._latest_path(Path(directory)),
                    "local_ignored_by_default": directory.startswith("data/"),
                }
            )
        return inventory

    def _latest_path(self, directory: Path) -> str:
        if not directory.exists():
            return "not generated yet"
        files = [path for path in directory.iterdir() if path.suffix in {".md", ".json"}]
        if not files:
            return "not generated yet"
        files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
        return str(files[0])

    def _producer_for_artifact(self, artifact: str) -> str:
        for item in EXPECTED_ARTIFACTS:
            if item["directory"] == artifact:
                return item["producer"]
        return "generated by linked demo command"

    def _portfolio_artifact_definition(self) -> dict[str, Any]:
        return {
            "name": "Portfolio interview pack",
            "directory": "data/portfolio_packs",
            "producer": "POST /portfolio/interview-pack",
            "formats": ["markdown", "json"],
        }

    def _demo_script(self, evidence: dict[str, Any]) -> list[str]:
        return [
            "Open with the premise: this is a local-first support escalation control tower designed for enterprise agent operations without external credentials.",
            "Run the one-command demo and point to the evidence score/count plus the generated Interview Pack path.",
            "Show the workflow run, trace, pending/approved human gate, and local outbox actions for Zendesk/Jira/Slack-shaped dispatches.",
            "Switch to failure proof: tool-failure drill, Replay Lab, policy guardrails, KB quality, and SLO/metrics surfaces.",
            f"Close by showing Portfolio Evidence coverage: {evidence['evidence_score']} across {evidence['evidence_count']} JD skill areas, with Markdown/JSON artifacts under ignored data folders.",
        ]

    def _technical_talking_points(self, evidence: dict[str, Any]) -> list[str]:
        return [
            f"Evidence index maps {evidence['evidence_count']} JD skill areas to code, endpoints, tests, evals, and artifacts.",
            "The workflow is stateful and auditable: each run stores classification, SLA risk, KB citations, drafts, QA, approval, node history, and metrics.",
            "Human approval is a first-class control, not a dashboard-only convention; dispatch only happens after approve.",
            "Fake adapters and the local outbox preserve production integration shape while keeping fresh-clone demos credential-free.",
            "Retries and failure drills prove degraded tool behavior and escalation to human review.",
            "Trace, audit, metrics, SLO, and ops reports make the system observable from API, dashboard, and generated artifacts.",
            "Replay Lab and policy guardrails turn safety into repeatable local simulations instead of subjective review.",
            "KB quality and refresh-plan exports show governance around grounding and support content quality.",
            "Leadership and incident artifacts translate engineering evidence into executive-ready narratives.",
            "The launch checklist and portfolio pack make the repository reviewable with deterministic commands.",
        ]

    def _architecture_walkthrough(self) -> list[str]:
        return [
            "FastAPI exposes protected local operations endpoints and open health/token endpoints for demos.",
            "ServiceContainer wires deterministic services over a SQLite-backed JsonStateStore.",
            "AgentWorkflowService owns the state machine; adapters and outbox keep integration side effects local.",
            "Artifact services compose stored run evidence into Markdown and JSON packs under ignored data folders.",
            "Streamlit reads the same API to provide operator, leadership, quality, replay, policy, and portfolio views.",
        ]

    def _failure_mode_story(self) -> dict[str, Any]:
        return {
            "scenario": "Knowledge retrieval fails repeatedly during an enterprise SLA-risk incident.",
            "system_response": [
                "Retry attempts are recorded as trace events with node status and metadata.",
                "The run stores failure_state and QA findings instead of silently dispatching.",
                "Human approval remains required, and policy/replay surfaces can explain the risk.",
                "Operator and leadership artifacts preserve the failure evidence for review.",
            ],
            "proof": [
                "POST /drills/tool-failure",
                "GET /runs/{run_id}/trace",
                "GET /metrics/agent-performance",
                "POST /ops/operator-readiness-pack",
            ],
        }

    def _metrics_eval_summary(self, evidence: dict[str, Any]) -> dict[str, Any]:
        snapshot = evidence["runtime_snapshot"]
        return {
            "portfolio_evidence_score": evidence["evidence_score"],
            "portfolio_evidence_count": evidence["evidence_count"],
            "runtime_counts": snapshot,
            "expected_eval_signals": [
                "pytest validates API workflows, artifacts, replay, policy, KB quality, leadership, and launch checks.",
                "ruff validates app, tests, dashboard, and scripts.",
                "app.evals.run_eval prints classification accuracy, routing accuracy, approval pauses, latency, token usage, and pass/fail.",
                "scripts/demo_run.py prints evidence score/count and generated Interview Pack path.",
            ],
        }

    def _resume_bullets(self, evidence: dict[str, Any]) -> list[str]:
        return [
            (
                "Built a local-first support escalation agent control tower with stateful workflow, "
                "human approval, fake Zendesk/Jira/Slack adapters, traces, metrics, replay, and policy guardrails."
            ),
            (
                f"Created deterministic Portfolio Evidence Index covering {evidence['evidence_count']} "
                "enterprise agent engineering skill areas with endpoints, tests, artifacts, and local proof paths."
            ),
            (
                "Packaged interviewer-ready Markdown/JSON artifacts, demo scripts, eval commands, "
                "failure-mode narrative, and leadership-ready incident evidence for fresh-clone review."
            ),
        ]

    def _markdown(self, pack: dict[str, Any]) -> str:
        demo_rows = [f"{index + 1}. {item}" for index, item in enumerate(pack["three_minute_demo_script"])]
        talking_rows = [f"- {point}" for point in pack["technical_talking_points"]]
        architecture_rows = [f"- {point}" for point in pack["architecture_walkthrough"]]
        failure_rows = [f"- {point}" for point in pack["failure_mode_story"]["system_response"]]
        command_rows = [f"- `{command}`" for command in pack["local_verification_commands"]]
        artifact_rows = [
            (
                f"- {item['name']}: `{item['directory']}` via `{item['producer']}` "
                f"(latest: `{item['latest_path']}`)"
            )
            for item in pack["artifact_inventory"]
        ]
        resume_rows = [f"- {bullet}" for bullet in pack["resume_github_readme_bullets"]]
        return "\n".join(
            [
                f"# Interview Pack: {pack['pack_id']}",
                "",
                "## Portfolio Evidence",
                f"- evidence score: {pack['evidence_score']}",
                f"- evidence count: {pack['evidence_count']}",
                "- local/mock only: true",
                "",
                "## 3-Minute Demo Script",
                *demo_rows,
                "",
                "## Technical Talking Points",
                *talking_rows,
                "",
                "## Architecture Walk-Through",
                *architecture_rows,
                "",
                "## Failure Mode Story",
                f"Scenario: {pack['failure_mode_story']['scenario']}",
                *failure_rows,
                "",
                "## Local Verification Commands",
                *command_rows,
                "",
                "## Metrics / Eval Summary",
                f"- Portfolio evidence score: {pack['metrics_eval_summary']['portfolio_evidence_score']}",
                f"- Portfolio evidence count: {pack['metrics_eval_summary']['portfolio_evidence_count']}",
                "",
                "## Artifact Inventory",
                *artifact_rows,
                "",
                "## Resume / GitHub README Bullets",
                *resume_rows,
                "",
            ]
        )
