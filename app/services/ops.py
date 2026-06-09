import json
import re
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore
from app.services.launch_checklist import EVAL_COMMANDS


CI_DOCTOR_VERIFICATION_COMMANDS = [
    *EVAL_COMMANDS,
    (
        r'rg "ops/ci-doctor|ops/audit-pack|CI Doctor|Audit Pack|'
        r'audit_packs|secret scan" app dashboard docs README.md tests scripts'
    ),
    (
        r"Get-ChildItem -Recurse -File data\audit_packs -ErrorAction SilentlyContinue "
        r"| Select-Object FullName,Length,LastWriteTime"
    ),
]

README_REQUIRED_SECTIONS = [
    "# Support Escalation Agent Control Tower",
    "## Quick Start",
    "## Demo Flow",
    "## Configuration",
    "## Reliability Surfaces",
    "## Repository Layout",
]

DOC_REQUIRED_FILES = [
    "docs/api.md",
    "docs/architecture.md",
    "docs/evaluation.md",
    "docs/workflow.md",
]

SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(password|secret|token|api[_-]?key)\b\s*[:=]\s*"
            r"[\"']([A-Za-z0-9_./+\-]{16,})[\"']"
        ),
    ),
]

SECRET_SCAN_ALLOWLIST = [
    "demo-control-tower-key",
    "test-key",
    "example",
    "placeholder",
    "fake",
    "mock",
    "not-a-secret",
    "your-",
    "CONTROL_TOWER_DEMO_API_KEY",
]

SECRET_SCAN_ROOT_FILES = [
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "docker-compose.yml",
    "Makefile",
    "pyproject.toml",
    "README.md",
    "requirements-dev.txt",
    "requirements.txt",
]

SECRET_SCAN_DIRS = ["app", "dashboard", "docs", "sample_data", "scripts", "tests"]


SLO_THRESHOLDS = {
    "agent_workflow_latency_ms": {
        "pass_at_or_below": 3000.0,
        "warn_at_or_below": 8000.0,
        "unit": "ms/run",
        "label": "Agent workflow latency",
    },
    "token_usage_per_run": {
        "pass_at_or_below": 1000.0,
        "warn_at_or_below": 2000.0,
        "unit": "tokens/run",
        "label": "Token usage",
    },
    "cost_usd_per_run": {
        "pass_at_or_below": 0.05,
        "warn_at_or_below": 0.25,
        "unit": "USD/run",
        "label": "Estimated cost",
    },
    "failure_count": {
        "pass_at_or_below": 0,
        "warn_at_or_below": 2,
        "unit": "failures",
        "label": "Workflow failures",
    },
    "pending_approvals": {
        "pass_at_or_below": 3,
        "warn_at_or_below": 8,
        "unit": "approvals",
        "label": "Pending approvals",
    },
    "outbox_dispatch_delay_minutes": {
        "pass_at_or_below": 5.0,
        "warn_at_or_below": 30.0,
        "unit": "minutes",
        "label": "Outbox dispatch delay",
    },
}


class OpsService:
    def __init__(self, store: JsonStateStore, optimization_reports_dir: Path):
        self.store = store
        self.optimization_reports_dir = optimization_reports_dir
        self.audit_packs_dir = optimization_reports_dir.parent / "audit_packs"
        self.repo_root = Path(__file__).resolve().parents[2]

    async def ci_doctor(self) -> dict[str, Any]:
        checks = self._ci_doctor_checks()
        score = self._ci_doctor_score(checks)
        blockers = [
            f"{check['label']} failed"
            for check in checks.values()
            if check["status"] == "fail"
        ]
        warnings = [
            f"{check['label']} should be reviewed"
            for check in checks.values()
            if check["status"] == "warn"
        ]
        status = "blocked" if blockers else "ready_with_warnings" if warnings else "ready"
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "local-deterministic-ci-doctor",
            "title": "CI Doctor",
            "status": status,
            "score": score,
            "blockers": blockers,
            "warnings": warnings,
            "checks": checks,
            "dependency_inventory": self._dependency_inventory(),
            "secret_scan_summary": checks["secret_scan"]["details"]["summary"],
            "local_verification_commands": CI_DOCTOR_VERIFICATION_COMMANDS,
            "publish_safety_checklist": self._publish_safety_checklist(checks),
            "local_mock_provider_notes": self._local_mock_provider_notes(),
        }

    async def export_audit_pack(self) -> dict[str, Any]:
        doctor = await self.ci_doctor()
        generated_at = datetime.now(timezone.utc)
        pack_id = f"audit_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        json_path = self.audit_packs_dir / f"{pack_id}.json"
        markdown_path = self.audit_packs_dir / f"{pack_id}.md"
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "title": "Local CI Doctor + Dependency/Secrets Audit Pack",
            "ci_doctor": doctor,
            "dependency_inventory": doctor["dependency_inventory"],
            "secret_scan_summary": doctor["secret_scan_summary"],
            "local_verification_commands": CI_DOCTOR_VERIFICATION_COMMANDS,
            "publish_safety_checklist": doctor["publish_safety_checklist"],
            "remediation_notes": self._audit_remediation_notes(doctor),
            "recruiter_interviewer_explanation": self._audit_interviewer_explanation(doctor),
            "artifact_paths": {
                "audit_pack_markdown": str(markdown_path),
                "audit_pack_json": str(json_path),
            },
        }
        markdown = self._audit_markdown(pack)
        self.audit_packs_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "doctor_status": doctor["status"],
            "doctor_score": doctor["score"],
            "pack": pack,
            "markdown": markdown,
        }

    async def slo_budget(self) -> dict[str, Any]:
        state = await self.store.load()
        metrics = self._metric_values(state)
        statuses = {
            metric: self._status(metric, current_value)
            for metric, current_value in metrics.items()
        }
        overall_status = self._overall_status([item["status"] for item in statuses.values()])
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall_status": overall_status,
            "metrics": statuses,
        }

    def _ci_doctor_checks(self) -> dict[str, Any]:
        workflow_files = self._workflow_files()
        workflow_text = "\n".join(self._read(path) for path in workflow_files)
        readme_text = self._read("README.md")
        docs = [
            {
                "path": path,
                "exists": self._repo_path(path).exists(),
                "mentions_ci_doctor": "CI Doctor" in self._read(path) or "Audit Pack" in self._read(path),
            }
            for path in DOC_REQUIRED_FILES
        ]
        dependency_inventory = self._dependency_inventory()
        secret_scan = self._secret_scan()
        checks = {
            "pytest_command": self._check(
                "Pytest command",
                "pass" if self._repo_path("tests").exists() else "fail",
                {"command": CI_DOCTOR_VERIFICATION_COMMANDS[0], "test_dir": "tests"},
            ),
            "ruff_command": self._check(
                "Ruff command",
                "pass" if "[tool.ruff]" in self._read("pyproject.toml") else "fail",
                {"command": CI_DOCTOR_VERIFICATION_COMMANDS[1], "config_file": "pyproject.toml"},
            ),
            "eval_command": self._check(
                "Eval command",
                "pass" if self._repo_path("app/evals/run_eval.py").exists() else "fail",
                {"command": CI_DOCTOR_VERIFICATION_COMMANDS[2], "file": "app/evals/run_eval.py"},
            ),
            "demo_command": self._check(
                "Demo command",
                "pass" if self._repo_path("scripts/demo_run.py").exists() else "fail",
                {"command": CI_DOCTOR_VERIFICATION_COMMANDS[3], "file": "scripts/demo_run.py"},
            ),
            "github_actions_workflow": self._check(
                "GitHub Actions workflow",
                "pass" if workflow_files and "pytest" in workflow_text and "ruff" in workflow_text else "fail",
                {
                    "workflow_files": workflow_files,
                    "pytest_in_ci": "pytest" in workflow_text,
                    "ruff_in_ci": "ruff" in workflow_text,
                },
            ),
            "docker_compose": self._check(
                "Docker Compose",
                "pass" if self._repo_path("docker-compose.yml").exists() else "warn",
                {"file": "docker-compose.yml", "exists": self._repo_path("docker-compose.yml").exists()},
            ),
            "env_example": self._check(
                ".env.example",
                "pass" if self._repo_path(".env.example").exists() else "fail",
                {
                    "file": ".env.example",
                    "contains_demo_key": "CONTROL_TOWER_DEMO_API_KEY" in self._read(".env.example"),
                },
            ),
            "readme_required_sections": self._check(
                "README required sections",
                "pass" if all(section in readme_text for section in README_REQUIRED_SECTIONS) else "warn",
                {
                    "required_sections": README_REQUIRED_SECTIONS,
                    "missing_sections": [
                        section for section in README_REQUIRED_SECTIONS if section not in readme_text
                    ],
                },
            ),
            "docs_presence": self._check(
                "Docs presence",
                "pass" if all(item["exists"] for item in docs) else "fail",
                {"files": docs},
            ),
            "generated_artifact_ignores": self._check(
                "Generated artifact ignores",
                "pass" if "data/" in self._read(".gitignore") and ".env" in self._read(".gitignore") else "fail",
                {"file": ".gitignore", "data_ignored": "data/" in self._read(".gitignore"), "env_ignored": ".env" in self._read(".gitignore")},
            ),
            "dependency_files": self._check(
                "Dependency files",
                "pass" if dependency_inventory["required_files_present"] else "fail",
                dependency_inventory,
            ),
            "local_mock_provider_notes": self._check(
                "Local/mock provider notes",
                "pass" if self._local_mock_notes_present() else "warn",
                self._local_mock_provider_notes(),
            ),
            "secret_scan": self._check(
                "Suspicious secret-pattern scan",
                "warn" if secret_scan["finding_count"] else "pass",
                {"summary": secret_scan},
            ),
        }
        return checks

    def _check(self, label: str, status: str, details: dict[str, Any]) -> dict[str, Any]:
        return {
            "label": label,
            "status": status,
            "details": details,
        }

    def _ci_doctor_score(self, checks: dict[str, Any]) -> int:
        values = [100 if check["status"] == "pass" else 75 if check["status"] == "warn" else 0 for check in checks.values()]
        return round(sum(values) / len(values)) if values else 0

    def _workflow_files(self) -> list[str]:
        workflow_dir = self.repo_root / ".github" / "workflows"
        if not workflow_dir.exists():
            return []
        files = [*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")]
        return sorted(str(path.relative_to(self.repo_root)).replace("\\", "/") for path in files)

    def _dependency_inventory(self) -> dict[str, Any]:
        pyproject = self._pyproject_dependencies()
        requirement_files = []
        for relative_path in ["requirements.txt", "requirements-dev.txt"]:
            path = self._repo_path(relative_path)
            requirement_files.append(
                {
                    "path": relative_path,
                    "exists": path.exists(),
                    "dependencies": self._requirements(relative_path),
                }
            )
        return {
            "required_files_present": self._repo_path("pyproject.toml").exists()
            and self._repo_path("requirements.txt").exists()
            and self._repo_path("requirements-dev.txt").exists(),
            "pyproject": pyproject,
            "requirement_files": requirement_files,
            "notes": [
                "Inventory is local and file-based; it does not query PyPI, GitHub, or vulnerability databases.",
                "Use this as a deterministic dependency manifest before running external SCA tooling in production.",
            ],
        }

    def _pyproject_dependencies(self) -> dict[str, Any]:
        path = self._repo_path("pyproject.toml")
        if not path.exists():
            return {"path": "pyproject.toml", "exists": False, "dependencies": [], "optional_dependencies": {}}
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        return {
            "path": "pyproject.toml",
            "exists": True,
            "dependencies": project.get("dependencies", []),
            "optional_dependencies": project.get("optional-dependencies", {}),
        }

    def _requirements(self, relative_path: str) -> list[str]:
        text = self._read(relative_path)
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def _secret_scan(self) -> dict[str, Any]:
        files = self._secret_scan_files()
        findings = []
        for path in files:
            text = path.read_text(encoding="utf-8", errors="ignore")
            relative = str(path.relative_to(self.repo_root)).replace("\\", "/")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if self._secret_line_allowed(line):
                    continue
                for pattern_name, pattern in SECRET_PATTERNS:
                    if pattern.search(line):
                        findings.append(
                            {
                                "file": relative,
                                "line": line_number,
                                "pattern": pattern_name,
                                "redacted_snippet": self._redact_secret_line(line),
                            }
                        )
        return {
            "label": "secret scan",
            "status": "warn" if findings else "pass",
            "scanned_file_count": len(files),
            "finding_count": len(findings),
            "findings": findings[:25],
            "truncated": len(findings) > 25,
            "skipped_directories": [".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__", "data"],
            "notes": [
                "The secret scan is a deterministic local pattern scan, not a substitute for dedicated secret scanning in CI.",
                "Findings intentionally redact matched values and do not call external services.",
            ],
        }

    def _secret_scan_files(self) -> list[Path]:
        files = []
        for relative_path in SECRET_SCAN_ROOT_FILES:
            path = self._repo_path(relative_path)
            if path.exists() and path.is_file():
                files.append(path)
        for relative_dir in SECRET_SCAN_DIRS:
            root = self._repo_path(relative_dir)
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".py", ".md", ".json", ".txt", ".toml", ".yml", ".yaml"}:
                    files.append(path)
        return sorted(set(files), key=lambda item: str(item).lower())

    def _secret_line_allowed(self, line: str) -> bool:
        lowered = line.lower()
        return any(token.lower() in lowered for token in SECRET_SCAN_ALLOWLIST)

    def _redact_secret_line(self, line: str) -> str:
        redacted = re.sub(r"([:=]\s*[\"']?)[^\"'\s]+", r"\1<redacted>", line.strip())
        return redacted[:160]

    def _local_mock_notes_present(self) -> bool:
        combined = "\n".join(
            [
                self._read("README.md"),
                self._read("docs/architecture.md"),
                self._read("docs/api.md"),
                self._read("docs/evaluation.md"),
            ]
        ).lower()
        return all(token in combined for token in ["local", "mock"]) and "fake" in combined

    def _local_mock_provider_notes(self) -> dict[str, Any]:
        return {
            "default_runtime": "local/mock deterministic providers",
            "external_services_required": False,
            "fake_adapters": ["Zendesk", "Jira", "Slack", "internal KB", "local mock LLM"],
            "notes": [
                "Default demo behavior does not require Azure, OpenAI, Zendesk, Jira, Slack, GitHub, or external CI access.",
                "The API key is a local demo gate, not a production credential.",
                "Production provider adapters should be added behind existing interfaces with separate credential review.",
            ],
        }

    def _publish_safety_checklist(self, checks: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"item": "Run pytest locally", "status": checks["pytest_command"]["status"], "command": CI_DOCTOR_VERIFICATION_COMMANDS[0]},
            {"item": "Run ruff locally", "status": checks["ruff_command"]["status"], "command": CI_DOCTOR_VERIFICATION_COMMANDS[1]},
            {"item": "Run deterministic eval", "status": checks["eval_command"]["status"], "command": CI_DOCTOR_VERIFICATION_COMMANDS[2]},
            {"item": "Run one-command demo", "status": checks["demo_command"]["status"], "command": CI_DOCTOR_VERIFICATION_COMMANDS[3]},
            {"item": "Confirm CI workflow and Docker Compose are present", "status": self._combined_status([checks["github_actions_workflow"]["status"], checks["docker_compose"]["status"]])},
            {"item": "Confirm generated artifacts and .env are ignored", "status": checks["generated_artifact_ignores"]["status"]},
            {"item": "Review dependency inventory", "status": checks["dependency_files"]["status"]},
            {"item": "Review suspicious secret-pattern scan", "status": checks["secret_scan"]["status"]},
        ]

    def _combined_status(self, statuses: list[str]) -> str:
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

    def _audit_remediation_notes(self, doctor: dict[str, Any]) -> list[str]:
        notes = []
        for key, check in doctor["checks"].items():
            if check["status"] == "pass":
                continue
            if key == "secret_scan":
                notes.append("Review secret scan findings, remove real credentials, and replace committed values with placeholders.")
            elif key == "github_actions_workflow":
                notes.append("Add or update .github/workflows CI so fresh clones run pytest and ruff.")
            elif key == "generated_artifact_ignores":
                notes.append("Keep generated Markdown/JSON packs and local .env files out of git via .gitignore.")
            elif key == "dependency_files":
                notes.append("Keep pyproject.toml plus requirements files aligned so local install paths stay predictable.")
            else:
                notes.append(f"Review {check['label']} because it returned {check['status']}.")
        if not notes:
            notes.append("No immediate remediation is required; rerun the doctor after any dependency, CI, or docs change.")
        return notes

    def _audit_interviewer_explanation(self, doctor: dict[str, Any]) -> list[str]:
        return [
            f"The CI Doctor reports {doctor['status']} with score {doctor['score']} from deterministic local file checks.",
            "It proves the repo has local commands for tests, linting, evals, and the demo before a reviewer spends time running it.",
            "The dependency inventory is read from committed files and avoids network calls, so results are stable in a fresh clone.",
            "The secret scan is intentionally local and redacted; it catches suspicious patterns without exposing values or calling external scanners.",
            "The Audit Pack gives recruiters and interviewers a publish-safety narrative in Markdown plus a machine-readable JSON copy.",
        ]

    def _audit_markdown(self, pack: dict[str, Any]) -> str:
        doctor = pack["ci_doctor"]
        check_rows = [
            f"| {check['label']} | {check['status']} |"
            for check in doctor["checks"].values()
        ]
        dependency_rows = [
            f"- pyproject dependency: `{item}`"
            for item in pack["dependency_inventory"]["pyproject"]["dependencies"]
        ]
        for req_file in pack["dependency_inventory"]["requirement_files"]:
            dependency_rows.append(
                f"- {req_file['path']}: {len(req_file['dependencies'])} dependencies"
            )
        secret_scan = pack["secret_scan_summary"]
        secret_rows = [
            f"- {item['file']}:{item['line']} `{item['pattern']}` {item['redacted_snippet']}"
            for item in secret_scan["findings"]
        ] or ["- No suspicious secret-pattern findings."]
        command_rows = [f"- `{command}`" for command in pack["local_verification_commands"]]
        checklist_rows = [
            f"- {item['item']}: {item['status']}" + (f" (`{item['command']}`)" if item.get("command") else "")
            for item in pack["publish_safety_checklist"]
        ]
        remediation_rows = [f"- {item}" for item in pack["remediation_notes"]]
        explanation_rows = [f"- {item}" for item in pack["recruiter_interviewer_explanation"]]
        return "\n".join(
            [
                f"# Audit Pack: {pack['pack_id']}",
                "",
                "## CI Doctor",
                f"- Status: **{doctor['status']}**",
                f"- Score: {doctor['score']}",
                "- Mode: local-deterministic-ci-doctor",
                "",
                "| Check | Status |",
                "| --- | --- |",
                *check_rows,
                "",
                "## Dependency Inventory",
                *dependency_rows,
                "",
                "## Secret Scan Summary",
                f"- Status: {secret_scan['status']}",
                f"- Scanned files: {secret_scan['scanned_file_count']}",
                f"- Findings: {secret_scan['finding_count']}",
                *secret_rows,
                "",
                "## Local Verification Commands",
                *command_rows,
                "",
                "## Publish-Safety Checklist",
                *checklist_rows,
                "",
                "## Remediation Notes",
                *remediation_rows,
                "",
                "## Recruiter / Interviewer Explanation",
                *explanation_rows,
                "",
            ]
        )

    async def export_optimization_report(self) -> dict[str, Any]:
        state = await self.store.load()
        slo = await self.slo_budget()
        generated_at = datetime.now(timezone.utc)
        report_id = f"optimization_report_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        report = {
            "report_id": report_id,
            "generated_at": generated_at.isoformat(),
            "overall_slo_status": slo["overall_status"],
            "slo_statuses": slo["metrics"],
            "top_slow_nodes": self._top_slow_nodes(state),
            "high_token_nodes": self._high_token_nodes(state),
            "failure_hotspots": self._failure_hotspots(state),
            "approval_bottlenecks": self._approval_bottlenecks(state),
        }
        report["recommended_fixes"] = self._recommended_fixes(report)
        markdown = self._markdown(report)
        json_path, markdown_path = self._write_report(report_id, report, markdown)
        return {
            "report_id": report_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "report": report,
            "markdown": markdown,
        }

    def _metric_values(self, state: dict[str, Any]) -> dict[str, float]:
        runs = list(state["runs"].values())
        approvals = list(state["approvals"].values())
        node_metrics = state["metrics"].get("node_metrics", {})
        run_count = len(runs)
        total_latency_ms = sum(item.get("latency_ms", 0.0) for item in node_metrics.values())
        total_tokens = sum(item.get("tokens", 0) for item in node_metrics.values())
        total_cost_usd = state["metrics"].get("cost_usd", 0.0)
        failure_count = len([run for run in runs if run.get("failure_state")])
        pending_approvals = len([item for item in approvals if item.get("status") == "pending"])
        return {
            "agent_workflow_latency_ms": round(total_latency_ms / run_count, 2) if run_count else 0.0,
            "token_usage_per_run": round(total_tokens / run_count, 2) if run_count else 0.0,
            "cost_usd_per_run": round(total_cost_usd / run_count, 6) if run_count else 0.0,
            "failure_count": float(failure_count),
            "pending_approvals": float(pending_approvals),
            "outbox_dispatch_delay_minutes": self._outbox_dispatch_delay_minutes(state),
        }

    def _status(self, metric: str, current_value: float) -> dict[str, Any]:
        threshold = SLO_THRESHOLDS[metric]
        pass_threshold = threshold["pass_at_or_below"]
        warn_threshold = threshold["warn_at_or_below"]
        if current_value <= pass_threshold:
            status = "pass"
        elif current_value <= warn_threshold:
            status = "warn"
        else:
            status = "fail"
        return {
            "label": threshold["label"],
            "unit": threshold["unit"],
            "thresholds": {
                "pass_at_or_below": pass_threshold,
                "warn_at_or_below": warn_threshold,
            },
            "current_value": current_value,
            "status": status,
            "recommendation": self._recommendation(metric, status),
        }

    def _recommendation(self, metric: str, status: str) -> str:
        if status == "pass":
            return "SLO is within budget; keep monitoring the local trend."
        recommendations = {
            "agent_workflow_latency_ms": "Profile the slowest workflow nodes and cache deterministic context where possible.",
            "token_usage_per_run": "Reduce prompt payload size, trim retrieved context, and reuse playbook summaries.",
            "cost_usd_per_run": "Shift low-risk drafts to cheaper models or shorten generation context.",
            "failure_count": "Review retry-exhausted nodes and add sharper fallback runbooks.",
            "pending_approvals": "Clear high-SLA pending approvals first and assign explicit reviewer ownership.",
            "outbox_dispatch_delay_minutes": "Inspect delayed dispatches and confirm approvals are not blocking handoff.",
        }
        return recommendations[metric]

    def _overall_status(self, statuses: list[str]) -> str:
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

    def _top_slow_nodes(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for node, data in state["metrics"].get("node_metrics", {}).items():
            count = data.get("count") or 1
            avg_latency_ms = round(data.get("latency_ms", 0.0) / count, 2)
            rows.append(
                {
                    "node": node,
                    "count": data.get("count", 0),
                    "avg_latency_ms": avg_latency_ms,
                    "total_latency_ms": round(data.get("latency_ms", 0.0), 2),
                    "recommendation": "Profile this node and remove repeated local work if it remains near the top.",
                }
            )
        return sorted(rows, key=lambda item: item["avg_latency_ms"], reverse=True)[:5]

    def _high_token_nodes(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for node, data in state["metrics"].get("node_metrics", {}).items():
            count = data.get("count") or 1
            tokens = data.get("tokens", 0)
            if not tokens:
                continue
            rows.append(
                {
                    "node": node,
                    "count": data.get("count", 0),
                    "total_tokens": tokens,
                    "avg_tokens": round(tokens / count, 2),
                    "total_cost_usd": round(data.get("cost_usd", 0.0), 6),
                    "recommendation": "Trim prompt context or route routine drafts to a lower-cost generation path.",
                }
            )
        return sorted(rows, key=lambda item: item["total_tokens"], reverse=True)[:5]

    def _failure_hotspots(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        failures = Counter()
        for run in state["runs"].values():
            failure = run.get("failure_state") or {}
            if failure:
                failures[failure.get("node", "unknown")] += 1
        for events in state["traces"].values():
            for event in events:
                if event.get("event_type") == "tool_call" and event.get("status") == "error":
                    failures[event.get("node") or "unknown"] += 1
        return [
            {
                "node": node,
                "failure_count": count,
                "recommendation": "Add a fallback path, better retry classification, or operator runbook for this node.",
            }
            for node, count in failures.most_common(5)
        ]

    def _approval_bottlenecks(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        rows = []
        for approval in state["approvals"].values():
            if approval.get("status") != "pending":
                continue
            created_at = self._parse_datetime(approval.get("created_at"))
            age_minutes = round((now - created_at).total_seconds() / 60, 2) if created_at else 0.0
            rows.append(
                {
                    "approval_id": approval["approval_id"],
                    "run_id": approval["run_id"],
                    "ticket_id": approval["ticket_id"],
                    "age_minutes": age_minutes,
                    "reason": approval.get("reason", ""),
                    "recommendation": "Assign a reviewer and clear this approval before lower-risk queue work.",
                }
            )
        return sorted(rows, key=lambda item: item["age_minutes"], reverse=True)[:10]

    def _recommended_fixes(self, report: dict[str, Any]) -> list[str]:
        fixes = []
        for metric, status in report["slo_statuses"].items():
            if status["status"] in {"warn", "fail"}:
                fixes.append(f"{status['label']}: {status['recommendation']}")
        if report["top_slow_nodes"]:
            node = report["top_slow_nodes"][0]["node"]
            fixes.append(f"Start latency tuning with `{node}`, the current slowest node.")
        if report["high_token_nodes"]:
            node = report["high_token_nodes"][0]["node"]
            fixes.append(f"Review prompt and retrieval payloads for `{node}`, the highest-token node.")
        if report["failure_hotspots"]:
            node = report["failure_hotspots"][0]["node"]
            fixes.append(f"Prioritize failure handling for `{node}` because it has the most local errors.")
        if report["approval_bottlenecks"]:
            fixes.append("Work pending approvals oldest-first, starting with high-SLA-risk tickets.")
        if not fixes:
            fixes.append("All SLOs are within budget; keep the current monitoring cadence.")
        return fixes

    def _outbox_dispatch_delay_minutes(self, state: dict[str, Any]) -> float:
        runs_by_id = state["runs"]
        delays = []
        for event in state["outbox"].values():
            run = runs_by_id.get(event.get("run_id"))
            if not run:
                continue
            started_at = self._parse_datetime(run.get("started_at"))
            created_at = self._parse_datetime(event.get("created_at"))
            if started_at and created_at:
                delays.append(max(0.0, (created_at - started_at).total_seconds() / 60))
        return round(max(delays), 2) if delays else 0.0

    def _parse_datetime(self, raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _read(self, relative_path: str) -> str:
        path = self._repo_path(relative_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _repo_path(self, relative_path: str) -> Path:
        return self.repo_root / relative_path

    def _write_report(
        self,
        report_id: str,
        report: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.optimization_reports_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.optimization_reports_dir / f"{report_id}.json"
        markdown_path = self.optimization_reports_dir / f"{report_id}.md"
        json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _markdown(self, report: dict[str, Any]) -> str:
        slo_rows = [
            (
                f"- {item['label']}: {item['status']} "
                f"({item['current_value']} {item['unit']}, pass <= "
                f"{item['thresholds']['pass_at_or_below']}) - {item['recommendation']}"
            )
            for item in report["slo_statuses"].values()
        ]
        slow_rows = [
            f"- {item['node']}: avg {item['avg_latency_ms']} ms over {item['count']} calls"
            for item in report["top_slow_nodes"]
        ] or ["- No node latency has been recorded yet."]
        token_rows = [
            f"- {item['node']}: {item['total_tokens']} tokens (${item['total_cost_usd']:.6f})"
            for item in report["high_token_nodes"]
        ] or ["- No token usage has been recorded yet."]
        failure_rows = [
            f"- {item['node']}: {item['failure_count']} failures - {item['recommendation']}"
            for item in report["failure_hotspots"]
        ] or ["- No failure hotspots detected."]
        approval_rows = [
            (
                f"- {item['approval_id']} for {item['ticket_id']}: "
                f"{item['age_minutes']} minutes pending - {item['reason']}"
            )
            for item in report["approval_bottlenecks"]
        ] or ["- No pending approval bottlenecks."]
        fix_rows = [f"- {item}" for item in report["recommended_fixes"]]
        return "\n".join(
            [
                f"# Optimization Report: {report['report_id']}",
                "",
                f"Overall SLO status: **{report['overall_slo_status']}**",
                "",
                "## SLO Statuses",
                *slo_rows,
                "",
                "## Top Slow Nodes",
                *slow_rows,
                "",
                "## High-Token Nodes",
                *token_rows,
                "",
                "## Failure Hotspots",
                *failure_rows,
                "",
                "## Approval Bottlenecks",
                *approval_rows,
                "",
                "## Recommended Fixes",
                *fix_rows,
                "",
            ]
        )
