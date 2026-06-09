import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOCAL_API_BASE = "http://127.0.0.1:8000"
DEMO_KEY = "demo-control-tower-key"

INSTALL_COMMANDS = [
    r"python -m venv .venv",
    r".\.venv\Scripts\python.exe -m pip install -e "".[dev]""",
    r"copy .env.example .env",
]

RUN_COMMANDS = [
    r".\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000",
    r".\.venv\Scripts\streamlit.exe run dashboard\streamlit_app.py",
]

EVAL_COMMANDS = [
    r".\.venv\Scripts\python.exe -m pytest -q",
    r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
    r".\.venv\Scripts\python.exe -m app.evals.run_eval",
    r".\.venv\Scripts\python.exe scripts\demo_run.py",
]

JD_SKILLS_DEMONSTRATED = [
    "FastAPI operations endpoints with API-key protection and OpenAPI discoverability.",
    "Local-first deterministic agent workflow with fake adapters for safe demos.",
    "Human-in-the-loop approval, audit, trace, and outbox evidence for risky support actions.",
    "Operational readiness reporting across SLOs, policy guardrails, replay, KB quality, and leadership KPIs.",
    "Portfolio-quality developer experience with one-command demo, evals, dashboard, and generated artifacts.",
]

INTERVIEWER_TALKING_POINTS = [
    "A reviewer can validate the product from one smoke matrix and one launch checklist artifact.",
    "The stack stays fully local and mock-backed while preserving production-shaped controls.",
    "Every demo path produces Markdown and JSON evidence that can be inspected without external services.",
    "The smoke matrix maps endpoint expectations to commands and artifact outputs for quick GitHub review.",
    "The checklist connects implementation depth to job-relevant skills: APIs, workflow, safety, observability, and ops.",
]

TROUBLESHOOTING_NOTES = [
    "If protected endpoints return 401, call POST /auth/demo-token and pass x-api-key: demo-control-tower-key.",
    "If port 8000 is busy, run uvicorn on another port and set CONTROL_TOWER_API_BASE_URL for the dashboard.",
    "If Streamlit cannot connect, confirm the FastAPI server is running and CONTROL_TOWER_API_KEY matches the demo key.",
    "If artifacts are missing, run the one-command demo to regenerate ignored files under data/.",
    "If evals use stale state, delete ignored local data/*.db files and rerun the deterministic demo.",
]

EXPECTED_ARTIFACTS = [
    {
        "name": "Demo evidence pack",
        "directory": "data/demo_packs",
        "producer": "POST /demo/evidence-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Operator readiness pack",
        "directory": "data/operator_packs",
        "producer": "POST /ops/operator-readiness-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Launch checklist",
        "directory": "data/launch_checklists",
        "producer": "POST /ops/launch-checklist",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Portfolio interview pack",
        "directory": "data/portfolio_packs",
        "producer": "POST /portfolio/interview-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Release Candidate Publish Pack",
        "directory": "data/release_packs",
        "producer": "POST /release/publish-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Reviewer Walkthrough Pack",
        "directory": "data/reviewer_packs",
        "producer": "POST /reviewer/walkthrough-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Replay report",
        "directory": "data/replay_reports",
        "producer": "POST /replay-lab/report",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Policy pack",
        "directory": "data/policy_packs",
        "producer": "POST /policies/export",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Leadership review",
        "directory": "data/leadership_reviews",
        "producer": "POST /leadership/review-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "KB refresh plan",
        "directory": "data/kb_refresh_plans",
        "producer": "POST /knowledge/refresh-plan",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Incident narrative",
        "directory": "data/incident_narratives",
        "producer": "POST /incidents/executive-narrative",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Postmortem RCA + Corrective Action Tracking Pack",
        "directory": "data/rca_packs",
        "producer": "POST /incidents/rca-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Incident brief",
        "directory": "data/briefs",
        "producer": "POST /runs/{run_id}/incident-brief",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Remediation checklist",
        "directory": "data/checklists",
        "producer": "POST /runs/{run_id}/remediation-checklist",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Weekly ops review",
        "directory": "data/reports",
        "producer": "POST /analytics/weekly-review",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Account brief",
        "directory": "data/account_briefs",
        "producer": "POST /customers/{customer_id_or_name}/account-brief",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Optimization report",
        "directory": "data/optimization_reports",
        "producer": "POST /ops/optimization-report",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Dashboard Smoke + UI Verification Pack",
        "directory": "data/ui_verification",
        "producer": "POST /ui/verification-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Final Handoff Pack",
        "directory": "data/final_handoff",
        "producer": "POST /handoff/final-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "On-Call Handoff + Customer Communications Pack",
        "directory": "data/customer_comms_packs",
        "producer": "POST /handoff/customer-comms-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "GitHub Push Readiness + Branch Hygiene Pack",
        "directory": "data/git_packs",
        "producer": "POST /git/push-plan",
        "formats": ["markdown", "json"],
    },
    {
        "name": "API Contract Reviewer Collection",
        "directory": "data/api_contracts",
        "producer": "POST /api/reviewer-collection",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Runtime Demo Server Pack",
        "directory": "data/runtime_packs",
        "producer": "POST /runtime/demo-pack",
        "formats": ["markdown", "json"],
    },
    {
        "name": "Scenario Dataset Eval Coverage Pack",
        "directory": "data/scenario_packs",
        "producer": "POST /scenarios/eval-pack",
        "formats": ["markdown", "json"],
    },
]


class LaunchChecklistService:
    def __init__(self, launch_checklists_dir: Path):
        self.launch_checklists_dir = launch_checklists_dir
        self.data_root = launch_checklists_dir.parent

    async def smoke_matrix(self) -> dict[str, Any]:
        matrix = self._endpoint_matrix()
        artifact_rows = [row for row in matrix if row["artifact_expectation"]["writes_artifact"]]
        readiness_summary = {
            "status": "ready",
            "label": "launch readiness",
            "total_checks": len(matrix),
            "protected_checks": len([row for row in matrix if row["requires_api_key"]]),
            "artifact_writing_checks": len(artifact_rows),
            "local_mock_only": True,
            "recommended_demo_command": r".\.venv\Scripts\python.exe scripts\demo_run.py",
            "checklist_endpoint": "POST /ops/launch-checklist",
            "notes": [
                "Start FastAPI first, then run token, smoke, demo, eval, and dashboard checks.",
                "All integrations are fake/local; no Zendesk, Jira, Slack, OpenAI, or warehouse credentials are required.",
            ],
        }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "api_base": LOCAL_API_BASE,
            "readiness_summary": readiness_summary,
            "matrix": matrix,
        }

    async def export_checklist(self) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc)
        checklist_id = f"launch_checklist_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        smoke = await self.smoke_matrix()
        checklist = {
            "checklist_id": checklist_id,
            "generated_at": generated_at.isoformat(),
            "readiness_summary": smoke["readiness_summary"],
            "install_commands": INSTALL_COMMANDS,
            "run_commands": RUN_COMMANDS,
            "api_smoke_matrix": smoke["matrix"],
            "demo_command": r".\.venv\Scripts\python.exe scripts\demo_run.py",
            "eval_commands": EVAL_COMMANDS,
            "generated_artifacts": self._generated_artifacts(),
            "troubleshooting_notes": TROUBLESHOOTING_NOTES,
            "jd_skills_demonstrated": JD_SKILLS_DEMONSTRATED,
            "interviewer_talking_points": INTERVIEWER_TALKING_POINTS,
        }
        self.launch_checklists_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.launch_checklists_dir / f"{checklist_id}.json"
        markdown_path = self.launch_checklists_dir / f"{checklist_id}.md"
        checklist["generated_artifacts"] = [
            *checklist["generated_artifacts"],
            {
                "name": "Launch checklist Markdown",
                "directory": "data/launch_checklists",
                "producer": "POST /ops/launch-checklist",
                "formats": ["markdown"],
                "latest_path": str(markdown_path),
            },
            {
                "name": "Launch checklist JSON",
                "directory": "data/launch_checklists",
                "producer": "POST /ops/launch-checklist",
                "formats": ["json"],
                "latest_path": str(json_path),
            },
        ]
        markdown = self._markdown(checklist)
        json_path.write_text(json.dumps(checklist, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return {
            "checklist_id": checklist_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "readiness_summary": checklist["readiness_summary"],
            "checklist": checklist,
            "markdown": markdown,
        }

    def _endpoint_matrix(self) -> list[dict[str, Any]]:
        rows = [
            self._row("GET", "/health", False, "Service health and LangGraph availability.", False),
            self._row("POST", "/auth/demo-token", False, "Returns the deterministic local demo key.", False),
            self._row("GET", "/ops/smoke-matrix", True, "Returns this launch smoke matrix.", False),
            self._row("POST", "/ops/launch-checklist", True, "Writes this launch checklist.", True, "data/launch_checklists"),
            self._row("GET", "/portfolio/evidence-index", True, "Returns recruiter-ready portfolio evidence.", False),
            self._row("POST", "/portfolio/interview-pack", True, "Writes the Interview Pack.", True, "data/portfolio_packs"),
            self._row("GET", "/release/quality-gate", True, "Returns Release Candidate readiness.", False),
            self._row("POST", "/release/publish-pack", True, "Writes the Publish Pack.", True, "data/release_packs"),
            self._row("GET", "/reviewer/quickstart", True, "Returns the Reviewer Quickstart.", False),
            self._row("POST", "/reviewer/walkthrough-pack", True, "Writes the Walkthrough Pack.", True, "data/reviewer_packs"),
            self._row("GET", "/ui/dashboard-smoke", True, "Returns dashboard source smoke checks.", False),
            self._row("POST", "/ui/verification-pack", True, "Writes the UI Verification Pack.", True, "data/ui_verification"),
            self._row("GET", "/handoff/on-call-summary", True, "Returns On-Call Handoff communication readiness.", False),
            self._row("POST", "/handoff/customer-comms-pack", True, "Writes Customer Communications proof.", True, "data/customer_comms_packs"),
            self._row("GET", "/incidents/postmortem-summary", True, "Returns Postmortem RCA summary and corrective action status.", False),
            self._row("POST", "/incidents/rca-pack", True, "Writes Postmortem RCA + Corrective Action proof.", True, "data/rca_packs"),
            self._row("GET", "/git/readiness", True, "Returns local git push readiness and branch hygiene checks.", False),
            self._row("POST", "/git/push-plan", True, "Writes the GitHub Push Readiness + Branch Hygiene Pack.", True, "data/git_packs"),
            self._row("GET", "/api/contract-audit", True, "Returns OpenAPI-derived API contract checks.", False),
            self._row("POST", "/api/reviewer-collection", True, "Writes the API Contract Reviewer Collection.", True, "data/api_contracts"),
            self._row("GET", "/runtime/demo-readiness", False, "Returns local runtime readiness and start commands.", False),
            self._row("POST", "/runtime/demo-pack", True, "Writes the Runtime Demo Server Pack.", True, "data/runtime_packs"),
            self._row("GET", "/scenarios/catalog", True, "Returns the scenario catalog and coverage summary.", False),
            self._row("POST", "/scenarios/eval-pack", True, "Writes the Scenario Dataset Eval Coverage Pack.", True, "data/scenario_packs"),
            self._row("POST", "/tickets/ingest-samples", True, "Loads sample tickets for manual demos.", False),
            self._row("GET", "/tickets", True, "Confirms authenticated ticket listing works.", False),
            self._row("POST", "/demo/evidence-pack", True, "Runs the complete demo and writes evidence.", True, "data/demo_packs plus linked artifacts"),
            self._row("POST", "/ops/operator-readiness-pack", True, "Exports operator handoff readiness evidence.", True, "data/operator_packs"),
            self._row("GET", "/leadership/scorecard", True, "Checks leadership KPI readiness.", False),
            self._row("GET", "/knowledge/quality-audit", True, "Checks KB quality readiness.", False),
            self._row("GET", "/ops/slo-budget", True, "Checks deterministic local SLO status.", False),
            self._row("GET", "/audit/events", True, "Confirms audit evidence can be inspected.", False),
        ]
        return rows

    def _row(
        self,
        method: str,
        path: str,
        requires_api_key: bool,
        purpose: str,
        writes_artifact: bool,
        artifact_path: str | None = None,
    ) -> dict[str, Any]:
        return {
            "method": method,
            "path": path,
            "endpoint": f"{method} {path}",
            "purpose": purpose,
            "requires_api_key": requires_api_key,
            "expected_status": 200,
            "sample_commands": {
                "curl": self._curl_command(method, path, requires_api_key),
                "powershell": self._powershell_command(method, path, requires_api_key),
            },
            "artifact_expectation": {
                "writes_artifact": writes_artifact,
                "path": artifact_path or "none",
            },
        }

    def _curl_command(self, method: str, path: str, requires_api_key: bool) -> str:
        headers = f' -H "x-api-key: {DEMO_KEY}"' if requires_api_key else ""
        return f"curl.exe -X {method} {LOCAL_API_BASE}{path}{headers}"

    def _powershell_command(self, method: str, path: str, requires_api_key: bool) -> str:
        headers = " -Headers @{'x-api-key'='demo-control-tower-key'}" if requires_api_key else ""
        return f"Invoke-RestMethod -Method {method.title()} -Uri {LOCAL_API_BASE}{path}{headers}"

    def _generated_artifacts(self) -> list[dict[str, Any]]:
        artifacts = []
        for item in EXPECTED_ARTIFACTS:
            directory = Path(item["directory"])
            latest_paths = self._latest_paths(directory)
            artifacts.append({**item, "latest_path": latest_paths[0] if latest_paths else "not generated yet"})
        return artifacts

    def _latest_paths(self, directory: Path) -> list[str]:
        if not directory.exists():
            return []
        files = [path for path in directory.iterdir() if path.suffix in {".md", ".json"}]
        files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
        return [str(path) for path in files[:2]]

    def _markdown(self, checklist: dict[str, Any]) -> str:
        summary = checklist["readiness_summary"]
        install_rows = [f"- `{command}`" for command in checklist["install_commands"]]
        run_rows = [f"- `{command}`" for command in checklist["run_commands"]]
        eval_rows = [f"- `{command}`" for command in checklist["eval_commands"]]
        smoke_rows = [
            (
                f"| `{row['endpoint']}` | {row['expected_status']} | "
                f"`{row['sample_commands']['curl']}` | {row['artifact_expectation']['path']} |"
            )
            for row in checklist["api_smoke_matrix"]
        ]
        artifact_rows = [
            (
                f"- {item['name']}: `{item['directory']}` via `{item['producer']}` "
                f"(latest: `{item['latest_path']}`)"
            )
            for item in checklist["generated_artifacts"]
        ]
        troubleshooting_rows = [f"- {note}" for note in checklist["troubleshooting_notes"]]
        skill_rows = [f"- {skill}" for skill in checklist["jd_skills_demonstrated"]]
        talking_rows = [f"- {point}" for point in checklist["interviewer_talking_points"]]
        return "\n".join(
            [
                f"# Launch Checklist: {checklist['checklist_id']}",
                "",
                "## Launch Readiness",
                f"- Status: **{summary['status']}**",
                f"- Total smoke checks: {summary['total_checks']}",
                f"- Protected checks: {summary['protected_checks']}",
                f"- Artifact-writing checks: {summary['artifact_writing_checks']}",
                f"- Local/mock only: {summary['local_mock_only']}",
                "",
                "## Install Commands",
                *install_rows,
                "",
                "## Run Commands",
                *run_rows,
                "",
                "## API Smoke Matrix",
                "| Endpoint | Expected Status | Sample curl | Artifact Expectation |",
                "| --- | ---: | --- | --- |",
                *smoke_rows,
                "",
                "## Demo Command",
                f"`{checklist['demo_command']}`",
                "",
                "## Eval Commands",
                *eval_rows,
                "",
                "## Generated Artifacts",
                *artifact_rows,
                "",
                "## Troubleshooting Notes",
                *troubleshooting_rows,
                "",
                "## JD Skills Demonstrated",
                *skill_rows,
                "",
                "## Interviewer Talking Points",
                *talking_rows,
                "",
            ]
        )
