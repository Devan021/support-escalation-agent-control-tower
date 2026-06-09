import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore
from app.services.artifacts import ArtifactInventoryService
from app.services.launch_checklist import EVAL_COMMANDS, EXPECTED_ARTIFACTS, INSTALL_COMMANDS, RUN_COMMANDS
from app.services.ui_verification import UIVerificationService


FINAL_HANDOFF_DIR = "data/final_handoff"

FINAL_HANDOFF_SEARCH_COMMAND = (
    r'rg "handoff/final-audit|handoff/final-pack|Final Handoff|final_handoff|'
    r'README Consistency|final audit" app dashboard docs README.md tests scripts'
)

FINAL_HANDOFF_ARTIFACT_COMMAND = (
    r"Get-ChildItem -Recurse -File data\final_handoff -ErrorAction SilentlyContinue "
    r"| Select-Object FullName,Length,LastWriteTime"
)

FINAL_VERIFICATION_COMMANDS = [
    *EVAL_COMMANDS[:3],
    r".\.venv\Scripts\python.exe scripts\dashboard_smoke.py",
    EVAL_COMMANDS[3],
    FINAL_HANDOFF_SEARCH_COMMAND,
    FINAL_HANDOFF_ARTIFACT_COMMAND,
]

FINAL_EXPECTED_OUTPUTS = [
    "pytest exits 0 with the final audit and Final Handoff Pack API tests passing.",
    "ruff exits 0 for app, tests, dashboard, and scripts.",
    "app.evals.run_eval prints deterministic local evaluation metrics and a passing summary.",
    "scripts/dashboard_smoke.py prints Dashboard Smoke: PASS with zero failed checks.",
    "scripts/demo_run.py prints final audit status/score and Final Handoff Pack Markdown/JSON paths.",
    "rg finds final handoff endpoints, README Consistency wording, final audit wording, and final_handoff artifact references.",
    "Get-ChildItem lists generated Markdown and JSON files under data\\final_handoff.",
]

DOC_FILES = ["README.md", "docs/api.md", "docs/architecture.md", "docs/evaluation.md", "docs/workflow.md"]

LOCAL_LIMITATION_TOKENS = ["local/mock", "Azure", "OpenAI", "Zendesk", "Jira", "Slack"]


class FinalHandoffService:
    def __init__(self, store: JsonStateStore, data_root: Path):
        self.store = store
        self.data_root = data_root
        self.final_handoff_dir = data_root / "final_handoff"
        self.repo_root = Path(__file__).resolve().parents[2]

    async def final_audit(self) -> dict[str, Any]:
        state = await self.store.load()
        route_inventory = self._route_inventory()
        readme_check = self._readme_endpoint_check(route_inventory)
        docs_api_check = self._docs_api_check(route_inventory)
        architecture_check = self._token_check(
            "architecture/evaluation/workflow coverage",
            ["docs/architecture.md", "docs/evaluation.md", "docs/workflow.md"],
            ["Final Handoff", "handoff/final-audit", "handoff/final-pack", "final_handoff"],
        )
        demo_check = self._demo_output_check()
        scripts_check = self._scripts_check()
        dashboard_smoke_script_check = self._dashboard_smoke_script_check()
        generated_artifact_docs_check = self._generated_artifact_docs_check()
        limitation_check = self._limitation_check()
        checks = {
            "readme_endpoint_mentions": readme_check,
            "docs_api_coverage": docs_api_check,
            "architecture_evaluation_workflow_coverage": architecture_check,
            "demo_output_claims": demo_check,
            "scripts_present": scripts_check,
            "dashboard_smoke_script_present": dashboard_smoke_script_check,
            "generated_artifact_directory_docs": generated_artifact_docs_check,
            "local_mock_azure_limitation_clarity": limitation_check,
        }
        blockers = [
            f"{name}: {check['label']}"
            for name, check in checks.items()
            if check["status"] == "fail"
        ]
        warnings = [
            f"{name}: {check['label']}"
            for name, check in checks.items()
            if check["status"] == "warn"
        ]
        score = self._score(checks)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "title": "README Consistency Final Audit",
            "mode": "local-deterministic-readme-consistency-audit",
            "status": "blocked" if blockers else "ready_with_warnings" if warnings else "ready",
            "score": score,
            "blockers": blockers,
            "warnings": warnings,
            "checks": checks,
            "endpoint_inventory_summary": self._endpoint_inventory_summary(route_inventory),
            "artifact_inventory_summary": self._artifact_inventory_summary(),
            "dashboard_smoke_summary": self._dashboard_smoke_summary(),
            "runtime_snapshot": self._runtime_snapshot(state),
            "local_only_notes": [
                "The final audit inspects local source files and generated artifact directories only.",
                "Default demo behavior remains local/mock and deterministic.",
                "No Azure, OpenAI, Zendesk, Jira, Slack, GitHub, or external SaaS credentials are required.",
            ],
        }

    async def export_final_pack(self) -> dict[str, Any]:
        audit = await self.final_audit()
        inventory = await ArtifactInventoryService(self.data_root).inventory()
        dashboard_smoke = UIVerificationService(self.data_root / "ui_verification").dashboard_smoke_sync()
        generated_at = datetime.now(timezone.utc)
        pack_id = f"final_handoff_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        json_path = self.final_handoff_dir / f"{pack_id}.json"
        markdown_path = self.final_handoff_dir / f"{pack_id}.md"
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "title": "Final Handoff Pack",
            "final_audit": audit,
            "exact_clone_run_commands": self._clone_run_commands(),
            "end_to_end_verification_order": self._verification_order(),
            "endpoint_inventory_summary": audit["endpoint_inventory_summary"],
            "artifact_inventory_summary": {
                "artifact_count": inventory["artifact_count"],
                "generated_artifact_directory_count": inventory["generated_artifact_directory_count"],
                "missing_artifact_directory_count": inventory["missing_artifact_directory_count"],
                "final_handoff_directory": FINAL_HANDOFF_DIR,
                "artifacts": inventory["artifacts"],
            },
            "dashboard_smoke_summary": dashboard_smoke["summary"],
            "recruiter_facing_final_readme_blurb": self._recruiter_blurb(audit),
            "limitations": audit["local_only_notes"],
            "artifact_paths": {
                "final_handoff_markdown": str(markdown_path),
                "final_handoff_json": str(json_path),
            },
        }
        markdown = self._markdown(pack)
        self.final_handoff_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "status": audit["status"],
            "score": audit["score"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "pack": pack,
            "markdown": markdown,
        }

    def _route_inventory(self) -> list[dict[str, Any]]:
        text = self._read("app/api/routes.py")
        rows = []
        for method, path, _decorator_tail in re.findall(r'@router\.(get|post)\("([^"]+)"([^\n]*)', text):
            endpoint = f"{method.upper()} {path}"
            writes_artifact = any(token in path for token in ["pack", "brief", "checklist", "report", "narrative", "review"])
            rows.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "endpoint": endpoint,
                    "requires_api_key": "dependencies=[Depends(require_api_key)]" in text[text.find(f'@router.{method}("{path}"') : text.find(f'@router.{method}("{path}"') + 220],
                    "writes_artifact": writes_artifact,
                }
            )
        return rows

    def _readme_endpoint_check(self, route_inventory: list[dict[str, Any]]) -> dict[str, Any]:
        readme = self._read("README.md")
        route_endpoints = {row["endpoint"] for row in route_inventory}
        mentioned = sorted(set(self._extract_endpoints(readme)))
        missing_routes = [endpoint for endpoint in mentioned if endpoint not in route_endpoints]
        missing_readme = [row["endpoint"] for row in route_inventory if row["endpoint"] not in readme]
        return self._check(
            "README endpoint mentions map to implemented FastAPI routes",
            not missing_routes and not missing_readme,
            {
                "mentioned_endpoint_count": len(mentioned),
                "implemented_endpoint_count": len(route_inventory),
                "mentioned_without_route": missing_routes,
                "implemented_without_readme_mention": missing_readme,
            },
        )

    def _docs_api_check(self, route_inventory: list[dict[str, Any]]) -> dict[str, Any]:
        api_doc = self._read("docs/api.md")
        route_endpoints = [row["endpoint"] for row in route_inventory]
        missing = [endpoint for endpoint in route_endpoints if endpoint not in api_doc]
        return self._check(
            "docs/api.md covers implemented endpoints",
            not missing,
            {
                "implemented_endpoint_count": len(route_endpoints),
                "missing_from_docs_api": missing,
                "final_audit_documented": "GET /handoff/final-audit" in api_doc,
                "final_pack_documented": "POST /handoff/final-pack" in api_doc,
            },
        )

    def _token_check(self, label: str, files: list[str], tokens: list[str]) -> dict[str, Any]:
        rows = []
        for file in files:
            text = self._read(file)
            rows.append(
                {
                    "file": file,
                    "exists": bool(text),
                    "missing_tokens": [token for token in tokens if token not in text],
                }
            )
        return self._check(label, all(row["exists"] and not row["missing_tokens"] for row in rows), {"files": rows})

    def _demo_output_check(self) -> dict[str, Any]:
        text = self._read("scripts/demo_run.py")
        tokens = [
            "/handoff/final-audit",
            "/handoff/final-pack",
            "Final audit:",
            "Final Handoff Pack:",
            "final_handoff",
        ]
        return self._check(
            "scripts/demo_run.py calls and prints final audit status/pack paths",
            all(token in text for token in tokens),
            {"file": "scripts/demo_run.py", "missing_tokens": [token for token in tokens if token not in text]},
        )

    def _scripts_check(self) -> dict[str, Any]:
        files = ["scripts/demo_run.py", "scripts/dashboard_smoke.py", "app/evals/run_eval.py"]
        return self._check(
            "required local demo, dashboard smoke, and eval scripts exist",
            all(self._repo_path(file).exists() for file in files),
            {"files": [{"file": file, "exists": self._repo_path(file).exists()} for file in files]},
        )

    def _dashboard_smoke_script_check(self) -> dict[str, Any]:
        script = self._read("scripts/dashboard_smoke.py")
        ui_service = self._read("app/services/ui_verification.py")
        return self._check(
            "dashboard smoke script is present and backed by UIVerificationService",
            self._repo_path("scripts/dashboard_smoke.py").exists()
            and "Dashboard Smoke:" in script
            and "UIVerificationService" in script
            and "DASHBOARD_SMOKE_COMMAND" in ui_service,
            {
                "script": "scripts/dashboard_smoke.py",
                "service": "app/services/ui_verification.py",
                "prints_dashboard_smoke": "Dashboard Smoke:" in script,
                "uses_ui_verification_service": "UIVerificationService" in script,
            },
        )

    def _generated_artifact_docs_check(self) -> dict[str, Any]:
        rows = []
        for file in DOC_FILES:
            text = self._read(file)
            rows.append({"file": file, "mentions_final_handoff": FINAL_HANDOFF_DIR in text or "data\\final_handoff" in text})
        artifact_defined = any(item["directory"] == FINAL_HANDOFF_DIR for item in EXPECTED_ARTIFACTS)
        return self._check(
            "generated final_handoff artifact directory is documented and ignored",
            all(row["mentions_final_handoff"] for row in rows) and artifact_defined and "data/" in self._read(".gitignore"),
            {
                "files": rows,
                "artifact_defined": artifact_defined,
                "data_ignored_by_git": "data/" in self._read(".gitignore"),
            },
        )

    def _limitation_check(self) -> dict[str, Any]:
        rows = []
        for file in DOC_FILES:
            text = self._read(file)
            rows.append(
                {
                    "file": file,
                    "has_local_mock": "local/mock" in text or "local-only" in text,
                    "mentions_azure": "Azure" in text,
                    "mentions_external_limits": all(token in text for token in ["OpenAI", "Zendesk", "Jira", "Slack"]),
                }
            )
        return self._check(
            "local/mock/Azure and external-service limitations are explicit",
            all(row["has_local_mock"] and row["mentions_azure"] and row["mentions_external_limits"] for row in rows),
            {"files": rows, "required_tokens": LOCAL_LIMITATION_TOKENS},
        )

    def _endpoint_inventory_summary(self, route_inventory: list[dict[str, Any]]) -> dict[str, Any]:
        protected = [row for row in route_inventory if row["requires_api_key"]]
        artifact_routes = [row for row in route_inventory if row["writes_artifact"]]
        return {
            "implemented_endpoint_count": len(route_inventory),
            "protected_endpoint_count": len(protected),
            "artifact_writing_endpoint_count": len(artifact_routes),
            "final_handoff_endpoints": [
                row["endpoint"] for row in route_inventory if row["path"].startswith("/handoff/")
            ],
            "endpoints": route_inventory,
        }

    def _artifact_inventory_summary(self) -> dict[str, Any]:
        directories = [item["directory"] for item in EXPECTED_ARTIFACTS]
        return {
            "expected_artifact_directory_count": len(directories),
            "final_handoff_directory": FINAL_HANDOFF_DIR,
            "final_handoff_defined": FINAL_HANDOFF_DIR in directories,
            "data_ignored_by_git": "data/" in self._read(".gitignore"),
        }

    def _dashboard_smoke_summary(self) -> dict[str, Any]:
        smoke = UIVerificationService(self.data_root / "ui_verification").dashboard_smoke_sync()
        return {
            "status": smoke["status"],
            "total_checks": smoke["summary"]["total_checks"],
            "failed_checks": smoke["summary"]["failed_checks"],
            "dashboard_smoke_script": r".\.venv\Scripts\python.exe scripts\dashboard_smoke.py",
        }

    def _runtime_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "tickets": len(state.get("tickets", {})),
            "runs": len(state.get("runs", {})),
            "traces": len(state.get("traces", {})),
            "approvals": len(state.get("approvals", {})),
            "outbox": len(state.get("outbox", {})),
            "ignored_runtime_root": "data/",
        }

    def _clone_run_commands(self) -> list[str]:
        repo_url = self._repo_remote_url()
        return [
            f"git clone {repo_url} agent-escalation-tower",
            "cd agent-escalation-tower",
            *INSTALL_COMMANDS,
            *RUN_COMMANDS,
            r".\.venv\Scripts\python.exe scripts\demo_run.py",
        ]

    def _verification_order(self) -> list[dict[str, str]]:
        return [
            {"step": str(index + 1), "command": command, "expected": FINAL_EXPECTED_OUTPUTS[index]}
            for index, command in enumerate(FINAL_VERIFICATION_COMMANDS)
        ]

    def _recruiter_blurb(self, audit: dict[str, Any]) -> str:
        return (
            "Final Handoff: the portfolio includes a README Consistency Final Audit at "
            "`GET /handoff/final-audit` and a Markdown/JSON Final Handoff Pack at "
            "`POST /handoff/final-pack` under ignored `data/final_handoff/`. "
            f"The current local audit reports `{audit['status']}` with score {audit['score']}, "
            "checking README/API/docs/demo/dashboard/artifact claims against implemented FastAPI routes and scripts."
        )

    def _repo_remote_url(self) -> str:
        config = self._read(".git/config")
        match = re.search(r'\[remote "origin"\][^\[]*url = ([^\n]+)', config)
        return match.group(1).strip() if match else "https://github.com/Devan021/support-escalation-agent-control-tower.git"

    def _extract_endpoints(self, text: str) -> list[str]:
        return [f"{method} {path}" for method, path in re.findall(r"\b(GET|POST) (/[-/{}/A-Za-z0-9_]+)", text)]

    def _score(self, checks: dict[str, dict[str, Any]]) -> int:
        values = [100 if check["status"] == "pass" else 85 if check["status"] == "warn" else 0 for check in checks.values()]
        return round(sum(values) / len(values))

    def _check(self, label: str, passed: bool, details: dict[str, Any]) -> dict[str, Any]:
        return {"label": label, "status": "pass" if passed else "fail", "details": details}

    def _read(self, relative_path: str) -> str:
        path = self._repo_path(relative_path)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _repo_path(self, relative_path: str) -> Path:
        return self.repo_root / relative_path

    def _markdown(self, pack: dict[str, Any]) -> str:
        audit = pack["final_audit"]
        check_rows = [
            f"| {name} | {check['status']} | {check['label']} |"
            for name, check in audit["checks"].items()
        ]
        command_rows = [
            f"- **{item['step']}** `{item['command']}` Expected: {item['expected']}"
            for item in pack["end_to_end_verification_order"]
        ]
        clone_rows = [f"- `{command}`" for command in pack["exact_clone_run_commands"]]
        endpoint_summary = pack["endpoint_inventory_summary"]
        artifact_summary = pack["artifact_inventory_summary"]
        limitation_rows = [f"- {item}" for item in pack["limitations"]]
        return "\n".join(
            [
                f"# Final Handoff Pack: {pack['pack_id']}",
                "",
                "## Final Audit",
                f"- Status: **{audit['status']}**",
                f"- Score: {audit['score']}",
                f"- Blockers: {len(audit['blockers'])}",
                f"- Warnings: {len(audit['warnings'])}",
                "",
                "## README Consistency Checks",
                "| Check | Status | Detail |",
                "| --- | --- | --- |",
                *check_rows,
                "",
                "## Exact Clone / Run Commands",
                *clone_rows,
                "",
                "## End-to-End Verification Order",
                *command_rows,
                "",
                "## Endpoint Inventory Summary",
                f"- Implemented endpoints: {endpoint_summary['implemented_endpoint_count']}",
                f"- Protected endpoints: {endpoint_summary['protected_endpoint_count']}",
                f"- Artifact-writing endpoints: {endpoint_summary['artifact_writing_endpoint_count']}",
                f"- Final handoff endpoints: {', '.join(endpoint_summary['final_handoff_endpoints'])}",
                "",
                "## Artifact Inventory Summary",
                f"- Artifact directories: {artifact_summary['artifact_count']}",
                f"- Generated directories: {artifact_summary['generated_artifact_directory_count']}",
                f"- Missing directories: {artifact_summary['missing_artifact_directory_count']}",
                f"- Final handoff directory: `{artifact_summary['final_handoff_directory']}`",
                "",
                "## Dashboard Smoke Summary",
                f"- Total checks: {pack['dashboard_smoke_summary']['total_checks']}",
                f"- Failed checks: {pack['dashboard_smoke_summary']['failed_checks']}",
                "",
                "## Recruiter-Facing README Blurb",
                pack["recruiter_facing_final_readme_blurb"],
                "",
                "## Limitations",
                *limitation_rows,
                "",
            ]
        )
