import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore
from app.services.demo import SCENARIO_ENDPOINTS
from app.services.launch_checklist import (
    DEMO_KEY,
    EVAL_COMMANDS,
    EXPECTED_ARTIFACTS,
    INSTALL_COMMANDS,
    LOCAL_API_BASE,
    RUN_COMMANDS,
    TROUBLESHOOTING_NOTES,
)


REVIEWER_SEARCH_COMMAND = (
    r'rg "reviewer/quickstart|reviewer/walkthrough-pack|Reviewer Quickstart|'
    r'Walkthrough Pack|reviewer_packs|proof tour" app dashboard docs README.md tests scripts'
)

REVIEWER_ARTIFACT_COMMAND = (
    r"Get-ChildItem -Recurse -File data\reviewer_packs -ErrorAction SilentlyContinue "
    r"| Select-Object FullName,Length,LastWriteTime"
)

QUICKSTART_VERIFICATION_COMMANDS = [
    *EVAL_COMMANDS,
    REVIEWER_SEARCH_COMMAND,
    REVIEWER_ARTIFACT_COMMAND,
]

QUICKSTART_EXPECTED_OUTPUTS = [
    "pytest exits 0 with API, workflow, artifact, replay, policy, KB, leadership, portfolio, release, and reviewer tests passing.",
    "ruff exits 0 for app, tests, dashboard, and scripts.",
    "app.evals.run_eval prints deterministic local eval metrics and a passing summary.",
    "scripts/demo_run.py prints reviewer quickstart status/count and the Walkthrough Pack Markdown/JSON paths.",
    "rg finds reviewer endpoints, Reviewer Quickstart wording, Walkthrough Pack wording, reviewer_packs path, and proof tour wording across code, docs, tests, and scripts.",
    "Get-ChildItem lists generated Markdown and JSON files under data\\reviewer_packs after POST /reviewer/walkthrough-pack or scripts/demo_run.py.",
]

ENDPOINT_WALKTHROUGH_ORDER = [
    "POST /auth/demo-token",
    "GET /reviewer/quickstart",
    "POST /reviewer/walkthrough-pack",
    "POST /demo/evidence-pack",
    "GET /portfolio/evidence-index",
    "GET /release/quality-gate",
    "POST /tickets/ingest-samples",
    "POST /tickets/{ticket_id}/analyze",
    "GET /runs/{run_id}/trace",
    "GET /approvals",
    "POST /runs/{run_id}/approve",
    "GET /integrations/outbox",
    "POST /replay-lab/report",
    "POST /policies/export",
    "GET /metrics/agent-performance",
    "GET /audit/events",
]

AGENT_WORKFLOW_WALKTHROUGH = [
    {
        "step": "intake_classifier",
        "reviewer_focus": "Confirm the ticket is normalized, classified, and persisted before any downstream action.",
        "proof": ["POST /tickets/{ticket_id}/analyze", "GET /runs/{run_id}"],
    },
    {
        "step": "sla_risk_scorer",
        "reviewer_focus": "Check enterprise urgency and SLA risk drive human review instead of unsafe automation.",
        "proof": ["GET /runs/{run_id}", "POST /drills/sla-breach-simulation"],
    },
    {
        "step": "knowledge_retriever",
        "reviewer_focus": "Inspect citations, retry behavior, and failure traces for grounded support answers.",
        "proof": ["GET /runs/{run_id}/trace", "POST /drills/tool-failure"],
    },
    {
        "step": "customer_and_engineering_drafts",
        "reviewer_focus": "Verify the agent prepares customer and internal handoff drafts without dispatching early.",
        "proof": ["POST /runs/{run_id}/incident-brief", "POST /runs/{run_id}/remediation-checklist"],
    },
    {
        "step": "qa_and_policy_gate",
        "reviewer_focus": "Review QA findings, policy guardrails, replay risk, and approval requirements.",
        "proof": ["POST /policies/export", "POST /replay-lab/report"],
    },
    {
        "step": "human_approval_and_outbox",
        "reviewer_focus": "Approve locally and inspect fake Zendesk/Jira/Slack-shaped outbox dispatches.",
        "proof": ["POST /runs/{run_id}/approve", "GET /integrations/outbox"],
    },
]

ROLE_SPECIFIC_REVIEWER_NOTES = {
    "recruiter": [
        "Start with the one-command demo, Portfolio Evidence score, Release Candidate score, and generated Walkthrough Pack.",
        "The story is local-first enterprise agent operations: approval, observability, safety, and generated proof without external credentials.",
        "Use the GitHub README blurb from the Walkthrough Pack when summarizing the project.",
    ],
    "engineering_manager": [
        "Inspect human approval, outbox, audit events, and policy/replay outputs for operational safety.",
        "Review generated leadership, operator, release, and reviewer packs for handoff quality.",
        "Look for deterministic test/eval coverage instead of relying on screenshots or hosted services.",
    ],
    "senior_engineer": [
        "Read ServiceContainer wiring, AgentWorkflowService state transitions, JsonStateStore, and artifact services.",
        "Trace one run from ticket ingest through approval and outbox, then compare Replay Lab and Policy Guardrail behavior.",
        "Run pytest, ruff, eval, demo, rg, and artifact listing commands from the quickstart.",
    ],
}


class ReviewerService:
    def __init__(self, store: JsonStateStore, reviewer_packs_dir: Path):
        self.store = store
        self.reviewer_packs_dir = reviewer_packs_dir
        self.repo_root = Path(__file__).resolve().parents[2]

    async def quickstart(self) -> dict[str, Any]:
        state = await self.store.load()
        proof_map = self._artifact_proof_map()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "title": "Reviewer Quickstart",
            "status": "ready",
            "mode": "local-deterministic-reviewer-quickstart",
            "local_mock_only": True,
            "api_base": LOCAL_API_BASE,
            "auth": {
                "demo_token_endpoint": "POST /auth/demo-token",
                "header": f"x-api-key: {DEMO_KEY}",
                "default_key": DEMO_KEY,
            },
            "local_setup_commands": INSTALL_COMMANDS,
            "run_commands": RUN_COMMANDS,
            "one_command_demo": r".\.venv\Scripts\python.exe scripts\demo_run.py",
            "verification_commands": QUICKSTART_VERIFICATION_COMMANDS,
            "expected_outputs": QUICKSTART_EXPECTED_OUTPUTS,
            "endpoint_walkthrough_order": ENDPOINT_WALKTHROUGH_ORDER,
            "agent_workflow_walkthrough": AGENT_WORKFLOW_WALKTHROUGH,
            "artifact_proof_map": proof_map,
            "artifact_proof_count": len(proof_map),
            "runtime_snapshot": self._runtime_snapshot(state),
            "troubleshooting": TROUBLESHOOTING_NOTES,
            "role_specific_reviewer_notes": ROLE_SPECIFIC_REVIEWER_NOTES,
            "next_best_clicks": [
                "Open /docs after starting FastAPI.",
                "Open the Streamlit Reviewer Quickstart tab.",
                "Run POST /reviewer/walkthrough-pack and inspect data/reviewer_packs.",
            ],
        }

    async def export_walkthrough_pack(self) -> dict[str, Any]:
        quickstart = await self.quickstart()
        generated_at = datetime.now(timezone.utc)
        pack_id = f"reviewer_walkthrough_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        json_path = self.reviewer_packs_dir / f"{pack_id}.json"
        markdown_path = self.reviewer_packs_dir / f"{pack_id}.md"
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "title": "Reviewer Walkthrough Pack",
            "quickstart_status": quickstart["status"],
            "quickstart_artifact_proof_count": quickstart["artifact_proof_count"],
            "recruiter_friendly_story": self._recruiter_story(quickstart),
            "engineer_deep_dive_path": self._engineer_deep_dive_path(),
            "command_checklist": self._command_checklist(quickstart),
            "api_workflow_proof_tour": self._api_workflow_proof_tour(quickstart),
            "artifacts_to_inspect": quickstart["artifact_proof_map"],
            "limitations": self._limitations(),
            "github_readme_blurb": self._github_readme_blurb(quickstart),
            "role_specific_reviewer_notes": quickstart["role_specific_reviewer_notes"],
            "quickstart": quickstart,
            "artifact_paths": {
                "reviewer_walkthrough_pack_markdown": str(markdown_path),
                "reviewer_walkthrough_pack_json": str(json_path),
            },
        }
        markdown = self._markdown(pack)
        self.reviewer_packs_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "quickstart_status": quickstart["status"],
            "artifact_proof_count": quickstart["artifact_proof_count"],
            "pack": pack,
            "markdown": markdown,
        }

    def _artifact_proof_map(self) -> list[dict[str, Any]]:
        rows = [
            {
                "name": "Reviewer Walkthrough Pack",
                "directory": "data/reviewer_packs",
                "producer": "POST /reviewer/walkthrough-pack",
                "formats": ["markdown", "json"],
            },
            *EXPECTED_ARTIFACTS,
        ]
        return [
            {
                **item,
                "latest_paths": self._latest_paths(self.repo_root / item["directory"]),
                "local_ignored_by_default": item["directory"].startswith("data/"),
            }
            for item in rows
        ]

    def _latest_paths(self, directory: Path) -> list[str]:
        if not directory.exists():
            return []
        files = [path for path in directory.iterdir() if path.suffix in {".md", ".json"}]
        files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
        return [str(path) for path in files[:2]]

    def _runtime_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "tickets": len(state.get("tickets", {})),
            "runs": len(state.get("runs", {})),
            "traces": len(state.get("traces", {})),
            "approvals": len(state.get("approvals", {})),
            "outbox": len(state.get("outbox", {})),
            "audit_events": len(state.get("audit_events", {})),
            "scenario_endpoint_count": len(SCENARIO_ENDPOINTS),
            "reviewer_pack_directory": "data/reviewer_packs",
        }

    def _recruiter_story(self, quickstart: dict[str, Any]) -> list[str]:
        return [
            "This project is a local support escalation control tower for reviewing enterprise-grade agent operations in minutes.",
            "A reviewer can run one command, inspect API and dashboard surfaces, and see Markdown/JSON proof artifacts without cloud or SaaS credentials.",
            (
                "The strongest portfolio signal is the full chain: ticket analysis, grounded drafting, "
                "human approval, fake integration outbox, traces, replay, policy guardrails, leadership reporting, and release readiness."
            ),
            (
                f"The Reviewer Quickstart currently reports `{quickstart['status']}` with "
                f"{quickstart['artifact_proof_count']} artifact proof entries."
            ),
        ]

    def _engineer_deep_dive_path(self) -> list[dict[str, str]]:
        return [
            {
                "step": "API and dependency wiring",
                "inspect": "app/api/routes.py and app/services/factory.py",
                "why": "Confirms thin route handlers and explicit local service composition.",
            },
            {
                "step": "Workflow state machine",
                "inspect": "app/services/workflow.py and app/models/entities.py",
                "why": "Shows persisted run state, approval decisions, final actions, and node history.",
            },
            {
                "step": "Safety and failure behavior",
                "inspect": "app/services/policy_guardrails.py, app/services/replay_lab.py, app/services/knowledge.py",
                "why": "Shows policy gating, counterfactual replay, retries, and degraded-mode evidence.",
            },
            {
                "step": "Proof generation",
                "inspect": "app/services/demo.py, app/services/portfolio.py, app/services/release.py, app/services/reviewer.py",
                "why": "Shows how local runtime evidence becomes reviewer-readable Markdown and JSON artifacts.",
            },
            {
                "step": "Dashboard and tests",
                "inspect": "dashboard/streamlit_app.py and tests/test_api.py",
                "why": "Confirms the same surfaces are reviewable through UI and deterministic tests.",
            },
        ]

    def _command_checklist(self, quickstart: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"label": "Install", "command": command, "expected": "Environment setup succeeds."}
            for command in quickstart["local_setup_commands"]
        ] + [
            {
                "label": "Run FastAPI",
                "command": quickstart["run_commands"][0],
                "expected": "http://127.0.0.1:8000/health returns ok.",
            },
            {
                "label": "Run dashboard",
                "command": quickstart["run_commands"][1],
                "expected": "Streamlit opens with a Reviewer Quickstart tab.",
            },
            {
                "label": "One-command demo",
                "command": quickstart["one_command_demo"],
                "expected": "Prints reviewer quickstart status/count and Walkthrough Pack paths.",
            },
        ] + [
            {"label": f"Verify {index + 1}", "command": command, "expected": quickstart["expected_outputs"][index]}
            for index, command in enumerate(quickstart["verification_commands"])
        ]

    def _api_workflow_proof_tour(self, quickstart: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "tour_name": "reviewer proof tour",
                "description": "Start with the quickstart and generated Walkthrough Pack to orient the review.",
                "endpoints": quickstart["endpoint_walkthrough_order"][:3],
            },
            {
                "tour_name": "agent workflow proof tour",
                "description": "Exercise the ticket-to-approval-to-outbox path and inspect trace evidence.",
                "endpoints": quickstart["endpoint_walkthrough_order"][6:12],
            },
            {
                "tour_name": "safety and operations proof tour",
                "description": "Inspect replay, policy, metrics, audit, portfolio, and release readiness evidence.",
                "endpoints": [
                    "POST /replay-lab/report",
                    "POST /policies/export",
                    "GET /metrics/agent-performance",
                    "GET /audit/events",
                    "GET /portfolio/evidence-index",
                    "GET /release/quality-gate",
                ],
            },
        ]

    def _limitations(self) -> list[str]:
        return [
            "The default path is intentionally local/mock and does not call OpenAI, Azure, Zendesk, Jira, Slack, GitHub, or external SaaS APIs.",
            "The walkthrough pack proves repository behavior and generated artifacts; it does not publish a hosted demo.",
            "Generated files under data/reviewer_packs are ignored and should be regenerated by each reviewer.",
            "Dashboard screenshots remain a manual reviewer task; the pack focuses on runnable API, service, test, eval, and artifact proof.",
        ]

    def _github_readme_blurb(self, quickstart: dict[str, Any]) -> str:
        return (
            "Reviewer Quickstart: run the local Support Escalation Agent Control Tower in minutes with "
            "`GET /reviewer/quickstart` and `POST /reviewer/walkthrough-pack`. The quickstart returns exact "
            "setup, demo, verification, endpoint, workflow, artifact, troubleshooting, and role-specific review "
            f"guidance; the Walkthrough Pack writes Markdown/JSON under `data/reviewer_packs/` with a proof tour "
            f"covering {quickstart['artifact_proof_count']} local artifact entries."
        )

    def _markdown(self, pack: dict[str, Any]) -> str:
        story_rows = [f"- {item}" for item in pack["recruiter_friendly_story"]]
        engineer_rows = [
            f"- **{item['step']}**: inspect `{item['inspect']}`. {item['why']}"
            for item in pack["engineer_deep_dive_path"]
        ]
        command_rows = [
            f"- **{item['label']}**: `{item['command']}` Expected: {item['expected']}"
            for item in pack["command_checklist"]
        ]
        tour_rows = [
            f"- **{item['tour_name']}**: {item['description']} Endpoints: "
            + ", ".join(f"`{endpoint}`" for endpoint in item["endpoints"])
            for item in pack["api_workflow_proof_tour"]
        ]
        artifact_rows = [
            (
                f"- {item['name']}: `{item['directory']}` via `{item['producer']}` "
                f"(latest: `{', '.join(item['latest_paths']) or 'not generated yet'}`)"
            )
            for item in pack["artifacts_to_inspect"]
        ]
        limitation_rows = [f"- {item}" for item in pack["limitations"]]
        return "\n".join(
            [
                f"# Reviewer Walkthrough Pack: {pack['pack_id']}",
                "",
                "## Reviewer Quickstart",
                f"- Status: {pack['quickstart_status']}",
                f"- Artifact proof count: {pack['quickstart_artifact_proof_count']}",
                "- Local/mock only: true",
                "",
                "## Recruiter-Friendly Story",
                *story_rows,
                "",
                "## Engineer Deep-Dive Path",
                *engineer_rows,
                "",
                "## Command Checklist",
                *command_rows,
                "",
                "## API / Workflow Proof Tour",
                *tour_rows,
                "",
                "## Artifacts to Inspect",
                *artifact_rows,
                "",
                "## Limitations",
                *limitation_rows,
                "",
                "## GitHub README Blurb",
                pack["github_readme_blurb"],
                "",
            ]
        )
