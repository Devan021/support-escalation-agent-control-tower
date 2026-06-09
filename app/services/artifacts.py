import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.launch_checklist import EVAL_COMMANDS, EXPECTED_ARTIFACTS, INSTALL_COMMANDS, RUN_COMMANDS


ARTIFACT_INDEX_SEARCH_COMMAND = (
    r'rg "artifacts/inventory|artifacts/readme-checklist|Artifact Inventory|'
    r'README Checklist|artifact_indexes|reviewer proof checklist" '
    r"app dashboard docs README.md tests scripts"
)

ARTIFACT_INDEX_LIST_COMMAND = (
    r"Get-ChildItem -Recurse -File data\artifact_indexes -ErrorAction SilentlyContinue "
    r"| Select-Object FullName,Length,LastWriteTime"
)

ARTIFACT_INDEX_COMMANDS = [
    *EVAL_COMMANDS,
    ARTIFACT_INDEX_SEARCH_COMMAND,
    ARTIFACT_INDEX_LIST_COMMAND,
]


EXTRA_ARTIFACTS = [
    {
        "name": "CI Doctor / Audit Pack",
        "directory": "data/audit_packs",
        "producer": "POST /ops/audit-pack",
        "formats": ["markdown", "json"],
        "reviewer_purpose": "Shows dependency, docs, generated-artifact ignore, and redacted secret-pattern checks before GitHub publish.",
    },
    {
        "name": "Artifact Inventory + README Checklist Pack",
        "directory": "data/artifact_indexes",
        "producer": "POST /artifacts/readme-checklist",
        "formats": ["markdown", "json"],
        "reviewer_purpose": "Gives reviewers a deterministic table of contents for generated artifacts and README proof suggestions.",
    },
    {
        "name": "Dashboard Smoke + UI Verification Pack",
        "directory": "data/ui_verification",
        "producer": "POST /ui/verification-pack",
        "formats": ["markdown", "json"],
        "reviewer_purpose": "Verifies Streamlit dashboard source wiring, expected tabs, endpoint references, and screenshot placeholders.",
    },
]

REVIEWER_PURPOSES = {
    "data/demo_packs": "End-to-end demo proof linking the scenario, metrics, endpoints, and generated evidence files.",
    "data/operator_packs": "Operator handoff proof for runbook QA, critical metrics, endpoint coverage, and readiness.",
    "data/launch_checklists": "Fresh-clone smoke matrix, setup commands, evals, troubleshooting, and launch-readiness evidence.",
    "data/portfolio_packs": "Recruiter/interviewer evidence that maps job-relevant skills to code, endpoints, tests, and artifacts.",
    "data/release_packs": "GitHub publish-readiness packet with gate status, coverage, commands, and repo checklist.",
    "data/reviewer_packs": "Reviewer walkthrough with command checklist, proof tour, role-specific notes, and README blurb.",
    "data/replay_reports": "Counterfactual safety proof for changed SLA, KB, adapter, confidence, and approval conditions.",
    "data/policy_packs": "Policy guardrail proof for blocked/gated actions, approvals, and risk reasoning.",
    "data/leadership_reviews": "Leadership-ready KPI and automation-readiness evidence.",
    "data/kb_refresh_plans": "Knowledge quality audit findings turned into owner-ready refresh work.",
    "data/incident_narratives": "Executive incident narrative and customer-impact timeline evidence.",
    "data/rca_packs": "Postmortem RCA, root cause, corrective action owners, due dates, recurrence risk, and customer follow-up evidence.",
    "data/briefs": "Incident handoff briefs with customer impact, drafts, trace summary, and next steps.",
    "data/checklists": "Remediation checklist proof tied to the selected playbook and run state.",
    "data/reports": "Weekly operations review evidence for local run, approval, outbox, and failure trends.",
    "data/account_briefs": "Customer/account health briefing evidence.",
    "data/optimization_reports": "SLO, latency, token, failure, and approval bottleneck recommendations.",
    "data/audit_packs": EXTRA_ARTIFACTS[0]["reviewer_purpose"],
    "data/artifact_indexes": EXTRA_ARTIFACTS[1]["reviewer_purpose"],
    "data/ui_verification": EXTRA_ARTIFACTS[2]["reviewer_purpose"],
    "data/final_handoff": "Final README/docs/API/demo consistency proof and reviewer handoff pack.",
    "data/customer_comms_packs": "On-call handoff and customer communications proof with SLA timeline, approval gates, scenario coverage, and trace IDs.",
    "data/git_packs": "GitHub Push Readiness + Branch Hygiene proof with local git status, ignored artifact, commit grouping, and pre-push checklist evidence.",
    "data/api_contracts": "OpenAPI-derived API Contract Audit and runnable Reviewer Collection proof for fresh-clone endpoint review.",
    "data/runtime_packs": "Runtime Demo Server Pack proof with exact local FastAPI and Streamlit commands, health checks, port checks, troubleshooting, and screenshot placeholders.",
    "data/scenario_packs": "Scenario Dataset Eval Coverage Pack proof for classification, SLA, approval, escalation, low-confidence, and failure coverage.",
}


class ArtifactInventoryService:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.artifact_indexes_dir = data_root / "artifact_indexes"
        self.repo_root = Path(__file__).resolve().parents[2]

    async def inventory(self) -> dict[str, Any]:
        artifacts = [self._artifact_row(item) for item in self._artifact_definitions()]
        generated = [item for item in artifacts if item["file_count"] > 0]
        stale = [item for item in artifacts if item["freshness"]["status"] == "missing"]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "title": "Artifact Inventory",
            "mode": "local-deterministic-artifact-inventory",
            "local_mock_only": True,
            "artifact_count": len(artifacts),
            "generated_artifact_directory_count": len(generated),
            "missing_artifact_directory_count": len(stale),
            "ignored_root": "data/",
            "artifact_index_directory": self._canonical_path(self.artifact_indexes_dir),
            "freshness_notes": self._freshness_notes(generated, stale),
            "local_commands": self._local_commands(),
            "artifacts": artifacts,
        }

    async def export_readme_checklist(self) -> dict[str, Any]:
        inventory = await self.inventory()
        generated_at = datetime.now(timezone.utc)
        checklist_id = f"readme_checklist_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        json_path = self.artifact_indexes_dir / f"{checklist_id}.json"
        markdown_path = self.artifact_indexes_dir / f"{checklist_id}.md"
        pack = {
            "checklist_id": checklist_id,
            "generated_at": generated_at.isoformat(),
            "title": "README Checklist Pack",
            "inventory_summary": {
                "artifact_count": inventory["artifact_count"],
                "generated_artifact_directory_count": inventory["generated_artifact_directory_count"],
                "missing_artifact_directory_count": inventory["missing_artifact_directory_count"],
                "artifact_index_directory": inventory["artifact_index_directory"],
            },
            "readme_badge_suggestions": self._badge_suggestions(inventory),
            "readme_checklist_suggestions": self._readme_checklist(inventory),
            "local_commands": inventory["local_commands"],
            "reviewer_proof_checklist": self._reviewer_proof_checklist(inventory),
            "cleanup_and_regeneration_notes": self._cleanup_notes(),
            "artifact_inventory": inventory["artifacts"],
            "inventory_freshness_notes": inventory["freshness_notes"],
            "artifact_paths": {
                "readme_checklist_markdown": str(markdown_path),
                "readme_checklist_json": str(json_path),
            },
        }
        markdown = self._markdown(pack)
        self.artifact_indexes_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return {
            "checklist_id": checklist_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "artifact_count": inventory["artifact_count"],
            "generated_artifact_directory_count": inventory["generated_artifact_directory_count"],
            "pack": pack,
            "markdown": markdown,
        }

    def _artifact_definitions(self) -> list[dict[str, Any]]:
        seen = set()
        rows = []
        for item in [*EXPECTED_ARTIFACTS, *EXTRA_ARTIFACTS]:
            directory = item["directory"]
            if directory in seen:
                continue
            seen.add(directory)
            rows.append(item)
        return rows

    def _artifact_row(self, item: dict[str, Any]) -> dict[str, Any]:
        directory = item["directory"]
        resolved_dir = self._resolve_directory(directory)
        latest_files = self._latest_files(resolved_dir)
        return {
            "name": item["name"],
            "directory": directory,
            "resolved_directory": str(resolved_dir),
            "producer": item["producer"],
            "producer_endpoint": item["producer"] if item["producer"].startswith(("GET ", "POST ")) else "",
            "producer_command": self._producer_command(item["producer"]),
            "formats": item["formats"],
            "ignored_status": self._ignored_status(directory),
            "reviewer_purpose": item.get("reviewer_purpose") or REVIEWER_PURPOSES.get(directory, "Reviewer proof artifact for local demo evidence."),
            "file_count": self._file_count(resolved_dir),
            "latest_files": latest_files,
            "latest_path": latest_files[0]["path"] if latest_files else "not generated yet",
            "freshness": self._freshness(resolved_dir, latest_files),
        }

    def _resolve_directory(self, canonical_directory: str) -> Path:
        path = Path(canonical_directory)
        if path.parts and path.parts[0] == "data":
            return self.data_root.joinpath(*path.parts[1:])
        return self.repo_root / path

    def _canonical_path(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.data_root)
            return str(Path("data") / relative).replace("/", "\\")
        except ValueError:
            return str(path)

    def _latest_files(self, directory: Path) -> list[dict[str, Any]]:
        if not directory.exists():
            return []
        files = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in {".md", ".json"}
        ]
        files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
        return [
            {
                "path": str(path),
                "name": path.name,
                "format": path.suffix.lstrip("."),
                "size_bytes": path.stat().st_size,
                "last_write_time": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            }
            for path in files[:4]
        ]

    def _file_count(self, directory: Path) -> int:
        if not directory.exists():
            return 0
        return len(
            [
                path
                for path in directory.iterdir()
                if path.is_file() and path.suffix.lower() in {".md", ".json"}
            ]
        )

    def _ignored_status(self, canonical_directory: str) -> dict[str, Any]:
        gitignore = self.repo_root / ".gitignore"
        patterns = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
        data_ignored = any(pattern.strip().rstrip("/") == "data" for pattern in patterns)
        return {
            "ignored_by_default": canonical_directory.startswith("data/") and data_ignored,
            "source": ".gitignore",
            "matched_pattern": "data/" if canonical_directory.startswith("data/") and data_ignored else "",
            "note": "Generated local proof; regenerate instead of committing." if canonical_directory.startswith("data/") else "Tracked or repo-local path.",
        }

    def _producer_command(self, producer: str) -> str:
        if producer.startswith(("GET ", "POST ")):
            method, path = producer.split(" ", 1)
            return (
                "Invoke-RestMethod "
                f"-Method {method.title()} "
                f"-Uri http://127.0.0.1:8000{path} "
                "-Headers @{'x-api-key'='demo-control-tower-key'}"
            )
        return producer

    def _freshness(self, directory: Path, latest_files: list[dict[str, Any]]) -> dict[str, str]:
        if not directory.exists():
            return {
                "status": "missing",
                "note": "Directory has not been generated yet; run the listed producer endpoint or demo command.",
            }
        if not latest_files:
            return {
                "status": "empty",
                "note": "Directory exists but has no Markdown or JSON reviewer artifact files yet.",
            }
        return {
            "status": "generated",
            "note": f"Latest reviewer artifact is {latest_files[0]['name']} at {latest_files[0]['last_write_time']}.",
        }

    def _freshness_notes(self, generated: list[dict[str, Any]], missing: list[dict[str, Any]]) -> list[str]:
        notes = [
            f"{len(generated)} of {len(generated) + len(missing)} artifact directories currently contain Markdown/JSON files.",
            "Freshness is based on local filesystem modification time, not a remote CI or GitHub timestamp.",
            "Ignored generated files are expected to be absent in a fresh clone until the demo or producer endpoints run.",
        ]
        if missing:
            notes.append(
                "Missing directories can be regenerated with `scripts\\demo_run.py` or the producer commands listed per artifact."
            )
        return notes

    def _local_commands(self) -> dict[str, list[str] | str]:
        return {
            "install": INSTALL_COMMANDS,
            "run": RUN_COMMANDS,
            "demo": r".\.venv\Scripts\python.exe scripts\demo_run.py",
            "verify": ARTIFACT_INDEX_COMMANDS,
            "cleanup": r"Remove-Item -Recurse -Force data\artifact_indexes",
        }

    def _badge_suggestions(self, inventory: dict[str, Any]) -> list[dict[str, str]]:
        count = inventory["artifact_count"]
        generated = inventory["generated_artifact_directory_count"]
        return [
            {
                "label": "Local demo",
                "markdown": "![local demo](https://img.shields.io/badge/local_demo-deterministic-brightgreen)",
                "purpose": "Signals the project can be reviewed without hosted services or credentials.",
            },
            {
                "label": "Artifacts",
                "markdown": f"![artifacts](https://img.shields.io/badge/artifacts-{generated}%2F{count}_generated-blue)",
                "purpose": "Shows how many local artifact directories currently contain reviewer files.",
            },
            {
                "label": "Reviewer checklist",
                "markdown": "![reviewer checklist](https://img.shields.io/badge/reviewer_checklist-README_pack-informational)",
                "purpose": "Points reviewers to the README Checklist Pack and Artifact Inventory endpoints.",
            },
        ]

    def _readme_checklist(self, inventory: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "item": "Run the one-command demo",
                "command": r".\.venv\Scripts\python.exe scripts\demo_run.py",
                "expected": "Console prints artifact inventory count and README Checklist Pack path.",
            },
            {
                "item": "Inspect generated artifact directories",
                "command": "GET /artifacts/inventory",
                "expected": f"{inventory['artifact_count']} artifact directories with latest-file and ignored-status metadata.",
            },
            {
                "item": "Export README Checklist Pack",
                "command": "POST /artifacts/readme-checklist",
                "expected": "Markdown and JSON are written under ignored `data/artifact_indexes/`.",
            },
            {
                "item": "Verify reviewer proof checklist",
                "command": ARTIFACT_INDEX_SEARCH_COMMAND,
                "expected": "Search finds API, dashboard, docs, README, tests, and script wiring.",
            },
        ]

    def _reviewer_proof_checklist(self, inventory: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {
                "proof": "Artifact Inventory endpoint",
                "how_to_check": "Call `GET /artifacts/inventory` and confirm every row has producer, latest_files, ignored_status, reviewer_purpose, and freshness.",
            },
            {
                "proof": "README Checklist export",
                "how_to_check": "Call `POST /artifacts/readme-checklist` and inspect the Markdown/JSON paths under `data/artifact_indexes/`.",
            },
            {
                "proof": "Generated evidence is local and ignored",
                "how_to_check": f"Confirm `ignored_root` is `{inventory['ignored_root']}` and rows report `.gitignore` pattern `data/`.",
            },
            {
                "proof": "Freshness is reviewable",
                "how_to_check": "Compare `latest_files[].last_write_time` with the demo run output and local file listing.",
            },
        ]

    def _cleanup_notes(self) -> list[str]:
        return [
            "Generated artifacts under `data/` are intentionally ignored by Git.",
            r"To regenerate the README Checklist Pack, run `.\.venv\Scripts\python.exe scripts\demo_run.py` or call `POST /artifacts/readme-checklist`.",
            r"To clean only this pack, remove `data\artifact_indexes\` and rerun the producer.",
            "Do not commit generated Markdown/JSON from `data/`; commit the service, tests, dashboard, docs, and README wiring instead.",
        ]

    def _markdown(self, pack: dict[str, Any]) -> str:
        summary = pack["inventory_summary"]
        badge_rows = [
            f"- **{item['label']}**: {item['markdown']} - {item['purpose']}"
            for item in pack["readme_badge_suggestions"]
        ]
        checklist_rows = [
            f"- [ ] **{item['item']}**: `{item['command']}` Expected: {item['expected']}"
            for item in pack["readme_checklist_suggestions"]
        ]
        command_rows = [f"- `{command}`" for command in pack["local_commands"]["verify"]]
        proof_rows = [
            f"- **{item['proof']}**: {item['how_to_check']}"
            for item in pack["reviewer_proof_checklist"]
        ]
        cleanup_rows = [f"- {item}" for item in pack["cleanup_and_regeneration_notes"]]
        artifact_rows = [
            (
                f"| {item['name']} | `{item['directory']}` | `{item['producer']}` | "
                f"`{item['latest_path']}` | {item['freshness']['status']} |"
            )
            for item in pack["artifact_inventory"]
        ]
        return "\n".join(
            [
                f"# README Checklist Pack: {pack['checklist_id']}",
                "",
                "## Artifact Inventory Summary",
                f"- Artifact directories: {summary['artifact_count']}",
                f"- Generated directories: {summary['generated_artifact_directory_count']}",
                f"- Missing directories: {summary['missing_artifact_directory_count']}",
                f"- Index directory: `{summary['artifact_index_directory']}`",
                "",
                "## README Badge Suggestions",
                *badge_rows,
                "",
                "## README Checklist Suggestions",
                *checklist_rows,
                "",
                "## Local Commands",
                f"- Demo: `{pack['local_commands']['demo']}`",
                *command_rows,
                "",
                "## Reviewer Proof Checklist",
                *proof_rows,
                "",
                "## Artifact Inventory",
                "| Artifact | Directory | Producer | Latest | Freshness |",
                "| --- | --- | --- | --- | --- |",
                *artifact_rows,
                "",
                "## Cleanup and Regeneration Notes",
                *cleanup_rows,
                "",
            ]
        )
