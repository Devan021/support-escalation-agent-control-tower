import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.launch_checklist import EVAL_COMMANDS, EXPECTED_ARTIFACTS


GIT_PACK_DIR = "data/git_packs"

GIT_READINESS_SEARCH_COMMAND = (
    r'rg "git/readiness|git/push-plan|GitHub Push Readiness|git_packs|'
    r'Branch Hygiene|Git Readiness" app dashboard docs README.md tests scripts'
)

GIT_PACK_LIST_COMMAND = (
    r"Get-ChildItem -Recurse -File data\git_packs -ErrorAction SilentlyContinue "
    r"| Select-Object FullName,Length,LastWriteTime"
)

GIT_READINESS_VERIFICATION_COMMANDS = [
    *EVAL_COMMANDS[:3],
    r".\.venv\Scripts\python.exe scripts\dashboard_smoke.py",
    EVAL_COMMANDS[3],
    GIT_READINESS_SEARCH_COMMAND,
    GIT_PACK_LIST_COMMAND,
]

NON_DESTRUCTIVE_REVIEW_COMMANDS = [
    "git status --porcelain=v1 -uall",
    "git branch --show-current",
    "git rev-parse --is-inside-work-tree",
    "git ls-files",
    "git check-ignore -v data/git_packs",
    r".\.venv\Scripts\python.exe -m pytest -q",
    r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
    r".\.venv\Scripts\python.exe -m app.evals.run_eval",
    r".\.venv\Scripts\python.exe scripts\dashboard_smoke.py",
    r".\.venv\Scripts\python.exe scripts\demo_run.py",
]

PUBLISH_BLURB = (
    "GitHub Push Readiness + Branch Hygiene: this repo includes local-only git readiness "
    "checks at `GET /git/readiness` and a Markdown/JSON push plan at `POST /git/push-plan`. "
    "The pack uses read-only git inspection, keeps generated artifacts under ignored "
    "`data/git_packs/`, and gives reviewers exact verification commands before any manual "
    "stage, commit, or push."
)

LARGE_FILE_BYTES = 1_000_000

GENERATED_DIRS = [
    *(item["directory"] for item in EXPECTED_ARTIFACTS),
    GIT_PACK_DIR,
    "data/audit_packs",
    "data/artifact_indexes",
    "data/ui_verification",
    "data/final_handoff",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
]

GENERATED_PATH_TOKENS = [
    "/__pycache__/",
    "/.pytest_cache/",
    "/.ruff_cache/",
    "/data/",
]


class GitReadinessService:
    def __init__(self, git_packs_dir: Path):
        self.git_packs_dir = git_packs_dir
        self.data_root = git_packs_dir.parent
        self.repo_root = Path(__file__).resolve().parents[2]

    async def readiness(self) -> dict[str, Any]:
        return self.readiness_sync()

    async def export_push_plan(self) -> dict[str, Any]:
        readiness = self.readiness_sync()
        generated_at = datetime.now(timezone.utc)
        pack_id = f"git_push_plan_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        json_path = self.git_packs_dir / f"{pack_id}.json"
        markdown_path = self.git_packs_dir / f"{pack_id}.md"
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "title": "GitHub Push Readiness + Branch Hygiene Pack",
            "readiness": readiness,
            "non_destructive_review_commands": NON_DESTRUCTIVE_REVIEW_COMMANDS,
            "suggested_commit_grouping": readiness["recommended_commit_groups"],
            "do_not_commit_generated_artifact_notes": self._generated_artifact_notes(readiness),
            "pre_push_verification_checklist": self._pre_push_checklist(),
            "repo_limitations": self._repo_limitations(readiness),
            "recruiter_github_readme_publish_blurb": PUBLISH_BLURB,
            "manual_publish_sequence": self._manual_publish_sequence(),
            "artifact_paths": {
                "git_push_plan_markdown": str(markdown_path),
                "git_push_plan_json": str(json_path),
            },
        }
        markdown = self._markdown(pack)
        self.git_packs_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "status": readiness["status"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "readiness_summary": readiness["summary"],
            "pack": pack,
            "markdown": markdown,
        }

    def readiness_sync(self) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).isoformat()
        git_repo = self._git_repo_summary()
        status_rows = self._status_rows() if git_repo["detected"] else []
        tracked_files = self._tracked_files() if git_repo["detected"] else []
        ignored_rows = self._ignored_rows() if git_repo["detected"] else []
        changed_files = self._changed_files(status_rows)
        changed_groups = self._changed_groups(changed_files)
        generated_dirs = self._generated_artifact_directories()
        workflow = self._workflow_presence()
        readme = self._readme_handoff_check()
        env_example = self._env_example_check()
        suspicious = self._suspicious_files(changed_files)
        summary = self._status_summary(status_rows, ignored_rows, tracked_files)
        blockers = self._blockers(git_repo, workflow, env_example)
        warnings = self._warnings(summary, generated_dirs, readme, suspicious)
        status = "blocked" if blockers else "review_required" if summary["dirty"] or warnings else "ready"
        return {
            "generated_at": generated_at,
            "title": "GitHub Push Readiness + Branch Hygiene",
            "mode": "local-read-only-git-inspection",
            "status": status,
            "summary": summary,
            "git": git_repo,
            "current_branch": git_repo["current_branch"],
            "tracked_untracked_modified_ignored_summary": summary,
            "generated_artifact_directories": generated_dirs,
            "changed_files": changed_files,
            "changed_file_groups": changed_groups,
            "source_doc_test_dashboard_files_changed": {
                "source": changed_groups["source"],
                "docs": changed_groups["docs"],
                "tests": changed_groups["tests"],
                "dashboard": changed_groups["dashboard"],
            },
            "suspicious_large_or_generated_files": suspicious,
            "github_actions_workflow": workflow,
            "readme_final_handoff_mention": readme,
            "env_example": env_example,
            "dirty_worktree_guidance": self._dirty_worktree_guidance(summary, suspicious),
            "recommended_commit_groups": self._recommended_commit_groups(changed_groups, suspicious),
            "local_only_notes": [
                "Uses read-only local git commands and filesystem checks.",
                "Does not stage, commit, push, reset, checkout, clean, delete files, or call GitHub APIs.",
                "Generated Markdown/JSON push plans are written under ignored data/git_packs.",
            ],
            "verification_commands": GIT_READINESS_VERIFICATION_COMMANDS,
            "blockers": blockers,
            "warnings": warnings,
        }

    def _git_repo_summary(self) -> dict[str, Any]:
        inside = self._git(["rev-parse", "--is-inside-work-tree"])
        detected = inside["ok"] and inside["stdout"].strip().lower() == "true"
        branch = self._git(["branch", "--show-current"]) if detected else self._empty_git_result()
        root = self._git(["rev-parse", "--show-toplevel"]) if detected else self._empty_git_result()
        return {
            "detected": detected,
            "repo_root": root["stdout"].strip() if root["ok"] else str(self.repo_root),
            "current_branch": branch["stdout"].strip() if branch["ok"] else "",
            "commands": {
                "repo_detected": inside,
                "current_branch": branch,
                "top_level": root,
            },
        }

    def _status_rows(self) -> list[dict[str, Any]]:
        result = self._git(["status", "--porcelain=v1", "-uall"])
        return [self._parse_status_line(line) for line in result["stdout"].splitlines() if line]

    def _ignored_rows(self) -> list[dict[str, Any]]:
        result = self._git(["status", "--porcelain=v1", "--ignored=matching", "-uall"])
        rows = [self._parse_status_line(line) for line in result["stdout"].splitlines() if line]
        return [row for row in rows if row["code"] == "!!"]

    def _tracked_files(self) -> list[str]:
        result = self._git(["ls-files"])
        if not result["ok"]:
            return []
        return [line.strip() for line in result["stdout"].splitlines() if line.strip()]

    def _parse_status_line(self, line: str) -> dict[str, Any]:
        code = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        return {
            "code": code,
            "path": path,
            "category": self._path_category(path),
            "size_bytes": self._file_size(path),
            "is_generated_path": self._is_generated_path(path),
        }

    def _changed_files(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        changed = []
        for row in rows:
            if row["code"] == "!!":
                continue
            state = "untracked" if row["code"] == "??" else "modified"
            if row["code"][0] == "A" or row["code"][1] == "A":
                state = "added"
            elif row["code"][0] == "D" or row["code"][1] == "D":
                state = "deleted"
            elif row["code"][0] == "R" or row["code"][0] == "C":
                state = "renamed_or_copied"
            changed.append({**row, "state": state})
        return sorted(changed, key=lambda item: item["path"].lower())

    def _changed_groups(self, changed_files: list[dict[str, Any]]) -> dict[str, list[str]]:
        groups = {
            "source": [],
            "docs": [],
            "tests": [],
            "dashboard": [],
            "scripts": [],
            "sample_data": [],
            "config": [],
            "generated_or_runtime": [],
            "other": [],
        }
        for item in changed_files:
            groups[item["category"]].append(item["path"])
        return groups

    def _status_summary(
        self,
        rows: list[dict[str, Any]],
        ignored_rows: list[dict[str, Any]],
        tracked_files: list[str],
    ) -> dict[str, Any]:
        untracked = [row for row in rows if row["code"] == "??"]
        modified = [row for row in rows if row["code"] not in {"??", "!!"}]
        return {
            "tracked_count": len(tracked_files),
            "changed_count": len(untracked) + len(modified),
            "untracked_count": len(untracked),
            "modified_count": len(modified),
            "ignored_count": len(ignored_rows),
            "ignored_sample": [row["path"] for row in ignored_rows[:20]],
            "dirty": bool(untracked or modified),
            "untracked_paths": [row["path"] for row in untracked],
            "modified_paths": [row["path"] for row in modified],
        }

    def _generated_artifact_directories(self) -> list[dict[str, Any]]:
        rows = []
        for directory in sorted(set(GENERATED_DIRS)):
            canonical = directory.replace("\\", "/").rstrip("/")
            check = self._git(["check-ignore", "-v", canonical])
            resolved = self.repo_root / canonical
            rows.append(
                {
                    "directory": canonical,
                    "exists": resolved.exists(),
                    "ignored": check["ok"],
                    "ignore_rule": check["stdout"].strip(),
                    "file_count": self._directory_file_count(resolved),
                    "note": "Generated local artifact/cache; regenerate instead of committing.",
                }
            )
        return rows

    def _workflow_presence(self) -> dict[str, Any]:
        workflow_dir = self.repo_root / ".github" / "workflows"
        files = []
        if workflow_dir.exists():
            files = sorted(
                str(path.relative_to(self.repo_root)).replace("\\", "/")
                for path in [*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")]
            )
        text = "\n".join(self._read(path) for path in files)
        return {
            "present": bool(files),
            "workflow_files": files,
            "pytest_present": "pytest" in text,
            "ruff_present": "ruff" in text,
            "required": ["pytest", "ruff"],
            "status": "pass" if files and "pytest" in text and "ruff" in text else "fail",
        }

    def _readme_handoff_check(self) -> dict[str, Any]:
        text = self._read("README.md")
        required = ["Final Handoff", "handoff/final-audit", "handoff/final-pack"]
        return {
            "present": bool(text),
            "mentions_final_handoff": all(token in text for token in required),
            "required_tokens": required,
            "missing_tokens": [token for token in required if token not in text],
        }

    def _env_example_check(self) -> dict[str, Any]:
        path = self.repo_root / ".env.example"
        text = self._read(".env.example")
        return {
            "present": path.exists(),
            "path": ".env.example",
            "contains_demo_key": "CONTROL_TOWER_DEMO_API_KEY" in text,
            "status": "pass" if path.exists() else "fail",
        }

    def _suspicious_files(self, changed_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        suspicious = []
        for item in changed_files:
            reasons = []
            if item["size_bytes"] >= LARGE_FILE_BYTES:
                reasons.append(f"large_file_over_{LARGE_FILE_BYTES}_bytes")
            if item["is_generated_path"]:
                reasons.append("generated_or_runtime_path")
            if Path(item["path"]).suffix.lower() in {".pyc", ".db", ".sqlite", ".tmp", ".log"}:
                reasons.append("runtime_file_extension")
            if reasons:
                suspicious.append({**item, "reasons": reasons})
        return suspicious

    def _dirty_worktree_guidance(
        self,
        summary: dict[str, Any],
        suspicious: list[dict[str, Any]],
    ) -> list[str]:
        guidance = [
            "Review `git status --porcelain=v1 -uall` before any manual staging.",
            "Coordinate with other agents before including modified files you did not personally change.",
            "Use narrow pathspecs when manually staging after review; do not stage generated data/ artifacts.",
        ]
        if summary["dirty"]:
            guidance.append(
                f"Worktree has {summary['changed_count']} changed files "
                f"({summary['modified_count']} modified, {summary['untracked_count']} untracked)."
            )
        else:
            guidance.append("Worktree is clean according to local git porcelain status.")
        if suspicious:
            guidance.append("Inspect suspicious large/generated files before any manual commit grouping.")
        return guidance

    def _recommended_commit_groups(
        self,
        groups: dict[str, list[str]],
        suspicious: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        suspicious_paths = {item["path"] for item in suspicious}
        specs = [
            ("api-service", "Add GitHub Push Readiness service and API endpoints", groups["source"]),
            ("dashboard", "Add Git Readiness dashboard tab", groups["dashboard"]),
            ("tests-demo", "Add git readiness tests and demo output", [*groups["tests"], *groups["scripts"]]),
            ("docs", "Document GitHub Push Readiness and Branch Hygiene", groups["docs"]),
            ("fixtures-config", "Update supporting fixtures and config", [*groups["sample_data"], *groups["config"]]),
        ]
        commit_groups = []
        for name, message, paths in specs:
            filtered = sorted(path for path in paths if path not in suspicious_paths)
            if filtered:
                commit_groups.append(
                    {
                        "group": name,
                        "suggested_commit_message": message,
                        "paths": filtered,
                        "review_note": "Review these paths manually before staging.",
                    }
                )
        generated = sorted(set(groups["generated_or_runtime"]) | suspicious_paths)
        if generated:
            commit_groups.append(
                {
                    "group": "do-not-commit-generated",
                    "suggested_commit_message": "",
                    "paths": generated,
                    "review_note": "Keep these out of commits unless a human explicitly decides otherwise.",
                }
            )
        if groups["other"]:
            commit_groups.append(
                {
                    "group": "manual-review-other",
                    "suggested_commit_message": "Review miscellaneous local changes",
                    "paths": sorted(groups["other"]),
                    "review_note": "These do not fit the source/docs/tests/dashboard buckets.",
                }
            )
        return commit_groups

    def _generated_artifact_notes(self, readiness: dict[str, Any]) -> list[str]:
        dirs = [
            row["directory"]
            for row in readiness["generated_artifact_directories"]
            if row["directory"].startswith("data/")
        ]
        return [
            "Do not commit generated Markdown/JSON artifacts from data/; regenerate them locally.",
            f"Git push plans are written to ignored `{GIT_PACK_DIR}/`.",
            "Generated artifact directories to leave ignored: " + ", ".join(f"`{item}`" for item in dirs),
        ]

    def _pre_push_checklist(self) -> list[dict[str, str]]:
        return [
            {"item": "Run pytest", "command": GIT_READINESS_VERIFICATION_COMMANDS[0], "expected": "exit 0"},
            {"item": "Run ruff", "command": GIT_READINESS_VERIFICATION_COMMANDS[1], "expected": "exit 0"},
            {"item": "Run deterministic eval", "command": GIT_READINESS_VERIFICATION_COMMANDS[2], "expected": "passing summary"},
            {"item": "Run dashboard smoke", "command": GIT_READINESS_VERIFICATION_COMMANDS[3], "expected": "Dashboard Smoke: PASS"},
            {"item": "Run demo", "command": GIT_READINESS_VERIFICATION_COMMANDS[4], "expected": "prints Git readiness status and Push Plan paths"},
            {"item": "Search feature wiring", "command": GIT_READINESS_VERIFICATION_COMMANDS[5], "expected": "matches in app, dashboard, docs, README, tests, and scripts"},
            {"item": "List generated push plans", "command": GIT_READINESS_VERIFICATION_COMMANDS[6], "expected": "Markdown and JSON under data\\git_packs"},
        ]

    def _repo_limitations(self, readiness: dict[str, Any]) -> list[str]:
        return [
            "This pack does not call GitHub APIs or inspect remote pull requests, branch protection, or CI run status.",
            "It does not stage, commit, push, reset, checkout, clean, or delete files.",
            "Readiness is based on the current local working tree and read-only git commands.",
            f"Current local branch reported by git: `{readiness['current_branch'] or 'unknown'}`.",
            "Ignored generated files are summarized locally; a fresh clone will need to regenerate data/ artifacts.",
        ]

    def _manual_publish_sequence(self) -> list[str]:
        return [
            "Review this pack and `git status --porcelain=v1 -uall`.",
            "Run the pre-push verification checklist.",
            "Manually stage only reviewed source, docs, dashboard, scripts, and tests.",
            "Commit in the suggested groups if that matches the collaborator-owned changes in the tree.",
            "Push only after a human confirms the branch and included paths.",
        ]

    def _blockers(
        self,
        git_repo: dict[str, Any],
        workflow: dict[str, Any],
        env_example: dict[str, Any],
    ) -> list[str]:
        blockers = []
        if not git_repo["detected"]:
            blockers.append("Git repository was not detected.")
        if workflow["status"] == "fail":
            blockers.append("Required GitHub Actions workflow with pytest and ruff was not found.")
        if env_example["status"] == "fail":
            blockers.append(".env.example is missing.")
        return blockers

    def _warnings(
        self,
        summary: dict[str, Any],
        generated_dirs: list[dict[str, Any]],
        readme: dict[str, Any],
        suspicious: list[dict[str, Any]],
    ) -> list[str]:
        warnings = []
        if summary["dirty"]:
            warnings.append("Working tree is dirty; coordinate before manual staging.")
        not_ignored = [
            row["directory"]
            for row in generated_dirs
            if row["directory"].startswith("data/") and not row["ignored"]
        ]
        if not_ignored:
            warnings.append("Generated artifact directories are not ignored: " + ", ".join(not_ignored))
        if not readme["mentions_final_handoff"]:
            warnings.append("README final handoff mention is incomplete.")
        if suspicious:
            warnings.append(f"{len(suspicious)} suspicious large/generated changed files need review.")
        return warnings

    def _path_category(self, path: str) -> str:
        normalized = path.replace("\\", "/")
        if normalized.startswith("app/"):
            return "source"
        if normalized.startswith("dashboard/"):
            return "dashboard"
        if normalized.startswith("tests/"):
            return "tests"
        if normalized.startswith("scripts/"):
            return "scripts"
        if normalized.startswith("docs/") or normalized == "README.md":
            return "docs"
        if normalized.startswith("sample_data/"):
            return "sample_data"
        if normalized.startswith("data/") or self._is_generated_path(normalized):
            return "generated_or_runtime"
        if normalized in {
            ".env.example",
            ".gitignore",
            "pyproject.toml",
            "requirements.txt",
            "requirements-dev.txt",
            "Dockerfile",
            "docker-compose.yml",
            "Makefile",
        } or normalized.startswith(".github/"):
            return "config"
        return "other"

    def _is_generated_path(self, path: str) -> bool:
        normalized = "/" + path.replace("\\", "/").strip("/")
        return any(token in normalized for token in GENERATED_PATH_TOKENS)

    def _directory_file_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        if path.is_file():
            return 1
        return sum(1 for item in path.rglob("*") if item.is_file())

    def _file_size(self, relative_path: str) -> int:
        path = self.repo_root / relative_path
        if not path.exists() or not path.is_file():
            return 0
        return path.stat().st_size

    def _git(self, args: list[str]) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "ok": False,
                "command": "git " + " ".join(args),
                "stdout": "",
                "stderr": str(exc),
                "returncode": -1,
            }
        return {
            "ok": completed.returncode == 0,
            "command": "git " + " ".join(args),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "returncode": completed.returncode,
        }

    def _empty_git_result(self) -> dict[str, Any]:
        return {"ok": False, "command": "", "stdout": "", "stderr": "", "returncode": -1}

    def _read(self, relative_path: str) -> str:
        path = self.repo_root / relative_path
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _markdown(self, pack: dict[str, Any]) -> str:
        readiness = pack["readiness"]
        summary = readiness["summary"]
        command_rows = [f"- `{command}`" for command in pack["non_destructive_review_commands"]]
        group_rows = [
            f"- **{group['group']}**: {group['suggested_commit_message'] or 'do not commit'} "
            f"({len(group['paths'])} paths)"
            for group in pack["suggested_commit_grouping"]
        ]
        generated_rows = [f"- {note}" for note in pack["do_not_commit_generated_artifact_notes"]]
        checklist_rows = [
            f"- [ ] **{item['item']}**: `{item['command']}` Expected: {item['expected']}"
            for item in pack["pre_push_verification_checklist"]
        ]
        limitation_rows = [f"- {item}" for item in pack["repo_limitations"]]
        guidance_rows = [f"- {item}" for item in readiness["dirty_worktree_guidance"]]
        suspicious_rows = [
            f"- `{item['path']}` ({item['size_bytes']} bytes): {', '.join(item['reasons'])}"
            for item in readiness["suspicious_large_or_generated_files"]
        ] or ["- none"]
        return "\n".join(
            [
                f"# GitHub Push Readiness + Branch Hygiene Pack: {pack['pack_id']}",
                "",
                "## Readiness Summary",
                f"- Status: **{readiness['status']}**",
                f"- Git repo detected: {readiness['git']['detected']}",
                f"- Current branch: `{readiness['current_branch'] or 'unknown'}`",
                f"- Changed files: {summary['changed_count']}",
                f"- Modified: {summary['modified_count']}",
                f"- Untracked: {summary['untracked_count']}",
                f"- Ignored count: {summary['ignored_count']}",
                "",
                "## Non-Destructive Review Commands",
                *command_rows,
                "",
                "## Suggested Commit Grouping",
                *group_rows,
                "",
                "## Dirty Worktree Guidance",
                *guidance_rows,
                "",
                "## Suspicious Large / Generated Files",
                *suspicious_rows,
                "",
                "## Do-Not-Commit Generated Artifact Notes",
                *generated_rows,
                "",
                "## Pre-Push Verification Checklist",
                *checklist_rows,
                "",
                "## Repo Limitations",
                *limitation_rows,
                "",
                "## Recruiter / GitHub README Publish Blurb",
                pack["recruiter_github_readme_publish_blurb"],
                "",
                "## Manual Publish Sequence",
                *[f"- {item}" for item in pack["manual_publish_sequence"]],
                "",
            ]
        )
