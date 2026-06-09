import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOCAL_API_BASE = "http://127.0.0.1:8000"
LOCAL_DASHBOARD_BASE = "http://127.0.0.1:8501"
DEMO_KEY = "demo-control-tower-key"

API_START_COMMAND = r".\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
DASHBOARD_START_COMMAND = r".\.venv\Scripts\streamlit.exe run dashboard\streamlit_app.py --server.port 8501"
START_SCRIPT_COMMAND = r".\scripts\start_demo.ps1"
RUNTIME_CHECK_COMMAND = r".\.venv\Scripts\python.exe scripts\runtime_check.py"
DEMO_RUN_COMMAND = r".\.venv\Scripts\python.exe scripts\demo_run.py"

INSTALL_COMMANDS = [
    r"python -m venv .venv",
    r".\.venv\Scripts\python.exe -m pip install -e "".[dev]""",
    r"copy .env.example .env",
]

START_COMMANDS = [
    API_START_COMMAND,
    DASHBOARD_START_COMMAND,
]

STOP_COMMANDS = [
    "Press Ctrl+C in the FastAPI terminal.",
    "Press Ctrl+C in the Streamlit terminal.",
    (
        "Optional manual PowerShell lookup only: "
        "Get-NetTCPConnection -LocalPort 8000,8501 -State Listen | Select-Object LocalPort,OwningProcess"
    ),
    "Do not kill processes unless you have confirmed they belong to this local demo.",
]

HEALTH_URLS = [
    f"{LOCAL_API_BASE}/health",
    f"{LOCAL_API_BASE}/runtime/demo-readiness",
    f"{LOCAL_API_BASE}/docs",
    LOCAL_DASHBOARD_BASE,
]

SMOKE_URLS = [
    f"{LOCAL_API_BASE}/ops/smoke-matrix",
    f"{LOCAL_API_BASE}/ui/dashboard-smoke",
    f"{LOCAL_API_BASE}/artifacts/inventory",
    f"{LOCAL_API_BASE}/api/contract-audit",
]

DEPENDENCY_REQUIREMENTS = [
    "fastapi",
    "uvicorn",
    "streamlit",
    "requests",
    "pytest",
    "ruff",
]

REQUIRED_FILES = [
    "app/main.py",
    "app/api/routes.py",
    "dashboard/streamlit_app.py",
    "scripts/demo_run.py",
    "scripts/dashboard_smoke.py",
    "pyproject.toml",
    ".env.example",
]

DEMO_FLOW_ORDER = [
    "Create and activate the virtual environment.",
    "Install editable dev dependencies.",
    "Run the source-only runtime check.",
    "Start FastAPI on port 8000.",
    "Open /health and /runtime/demo-readiness.",
    "Start Streamlit on port 8501.",
    "Open the Runtime Demo dashboard tab.",
    "Run dashboard smoke and demo_run.",
    "Export POST /runtime/demo-pack.",
    "Inspect generated Markdown/JSON under data/runtime_packs.",
]

KNOWN_LIMITATIONS = [
    "The readiness check is local and read-only; it reports busy ports but never stops processes.",
    "Azure, OpenAI, Zendesk, Jira, Slack, GitHub, and hosted Vercel services are not required.",
    "Streamlit browser rendering is verified by manual screenshot placeholders, not by this service.",
    "If another process owns port 8000 or 8501, choose a different port and update the dashboard API base URL.",
    "Generated runtime packs under data/runtime_packs are ignored local artifacts and should be regenerated.",
]

TROUBLESHOOTING = [
    "If protected endpoints return 401, call POST /auth/demo-token and pass x-api-key: demo-control-tower-key.",
    "If FastAPI will not start, run the runtime check and confirm uvicorn imports from the active .venv.",
    "If Streamlit cannot reach the API, set CONTROL_TOWER_API_BASE_URL to the FastAPI URL.",
    "If port checks show a listener, inspect the owning process manually before deciding what to stop.",
    "If generated artifacts are absent in a fresh clone, run scripts/demo_run.py or POST /runtime/demo-pack.",
]

SCREENSHOT_CHECKLIST = [
    {
        "view": "FastAPI health",
        "placeholder": "screenshots/runtime-fastapi-health.png",
        "what_to_capture": "GET /health returns status ok and service name.",
    },
    {
        "view": "Runtime readiness JSON",
        "placeholder": "screenshots/runtime-demo-readiness-json.png",
        "what_to_capture": "Commands, ports, dependency checks, and known limitations.",
    },
    {
        "view": "Streamlit Runtime Demo tab",
        "placeholder": "screenshots/runtime-demo-streamlit-tab.png",
        "what_to_capture": "Readiness status, port checks, command blocks, and pack export path.",
    },
    {
        "view": "Generated runtime pack",
        "placeholder": "screenshots/runtime-pack-files.png",
        "what_to_capture": "Markdown and JSON files under data/runtime_packs.",
    },
]

RECRUITER_EXPLANATION = (
    "The Runtime Demo Server Pack makes the project easy to review from a fresh clone: it lists "
    "the exact local commands, ports, health URLs, and artifacts without needing cloud accounts."
)

ENGINEER_EXPLANATION = (
    "The readiness endpoint performs source, dependency, file, and read-only port checks, then the "
    "pack endpoint writes reproducible Markdown/JSON so reviewers can audit local runtime setup."
)


class RuntimeDemoService:
    def __init__(self, runtime_packs_dir: Path):
        self.runtime_packs_dir = runtime_packs_dir
        self.data_root = runtime_packs_dir.parent
        self.repo_root = Path(__file__).resolve().parents[2]

    async def readiness(self) -> dict[str, Any]:
        return self.readiness_sync()

    async def export_pack(self) -> dict[str, Any]:
        readiness = self.readiness_sync()
        generated_at = datetime.now(timezone.utc)
        pack_id = f"runtime_demo_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        json_path = self.runtime_packs_dir / f"{pack_id}.json"
        markdown_path = self.runtime_packs_dir / f"{pack_id}.md"
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "title": "Runtime Demo Server Pack",
            "readiness": readiness,
            "install_commands": INSTALL_COMMANDS,
            "start_commands": START_COMMANDS,
            "start_script_command": START_SCRIPT_COMMAND,
            "stop_commands": STOP_COMMANDS,
            "health_checks": self._health_checks(),
            "demo_flow_order": DEMO_FLOW_ORDER,
            "screenshot_checklist": SCREENSHOT_CHECKLIST,
            "troubleshooting": TROUBLESHOOTING,
            "known_limitations": KNOWN_LIMITATIONS,
            "recruiter_explanation": RECRUITER_EXPLANATION,
            "engineer_explanation": ENGINEER_EXPLANATION,
            "artifact_paths": {
                "runtime_pack_markdown": str(markdown_path),
                "runtime_pack_json": str(json_path),
            },
        }
        markdown = self._markdown(pack)
        self.runtime_packs_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "status": readiness["status"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "pack": pack,
            "markdown": markdown,
        }

    def readiness_sync(self) -> dict[str, Any]:
        dependency_checks = self._dependency_checks()
        file_checks = self._file_checks()
        port_checks = self._port_checks()
        netstat_checks = self._netstat_checks()
        checks = [
            *dependency_checks,
            *file_checks,
            *port_checks,
            *netstat_checks,
            self._data_ignore_check(),
        ]
        failed = [check for check in checks if check["status"] == "fail"]
        warnings = [check for check in checks if check["status"] == "warn"]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "title": "Runtime Demo Readiness",
            "mode": "local-source-readiness-no-server-required",
            "status": "blocked" if failed else "ready_with_warnings" if warnings else "ready",
            "local_mock_only": True,
            "repo_root": str(self.repo_root),
            "runtime_pack_directory": "data/runtime_packs",
            "run_commands": {
                "install": INSTALL_COMMANDS,
                "start": START_COMMANDS,
                "start_script": START_SCRIPT_COMMAND,
                "runtime_check": RUNTIME_CHECK_COMMAND,
                "demo_run": DEMO_RUN_COMMAND,
            },
            "expected_ports": self._expected_ports(),
            "env_requirements": self._env_requirements(),
            "dependency_checks": dependency_checks,
            "file_checks": file_checks,
            "process_port_checks": {
                "socket_connect_checks": port_checks,
                "netstat_listener_checks": netstat_checks,
                "safe_read_only": True,
                "auto_kill_processes": False,
            },
            "health_urls": HEALTH_URLS,
            "smoke_urls": SMOKE_URLS,
            "health_checks": self._health_checks(),
            "known_limitations": KNOWN_LIMITATIONS,
            "troubleshooting": TROUBLESHOOTING,
            "checks": checks,
            "summary": {
                "total_checks": len(checks),
                "failed_checks": len(failed),
                "warning_checks": len(warnings),
                "passed_checks": len(checks) - len(failed) - len(warnings),
            },
        }

    def _dependency_checks(self) -> list[dict[str, Any]]:
        pyproject = self._read("pyproject.toml")
        checks = []
        for name in DEPENDENCY_REQUIREMENTS:
            source_present = name in pyproject
            import_present = self._import_available(name)
            checks.append(
                {
                    "name": name,
                    "kind": "python-package",
                    "status": "pass" if source_present and import_present else "warn",
                    "source_declared": source_present,
                    "import_available": import_present,
                    "note": (
                        "Declared in pyproject and importable."
                        if source_present and import_present
                        else "Install dev dependencies in the active .venv."
                    ),
                }
            )
        return checks

    def _file_checks(self) -> list[dict[str, Any]]:
        checks = []
        for path in REQUIRED_FILES:
            exists = self._repo_path(path).exists()
            checks.append(
                {
                    "name": path,
                    "kind": "required-file",
                    "status": "pass" if exists else "fail",
                    "exists": exists,
                    "note": "Required local runtime file is present." if exists else "Required file is missing.",
                }
            )
        return checks

    def _port_checks(self) -> list[dict[str, Any]]:
        return [
            self._socket_port_check("FastAPI", "127.0.0.1", 8000),
            self._socket_port_check("Streamlit", "127.0.0.1", 8501),
        ]

    def _socket_port_check(self, name: str, host: str, port: int) -> dict[str, Any]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            listening = sock.connect_ex((host, port)) == 0
        return {
            "name": name,
            "host": host,
            "port": port,
            "kind": "read-only-socket-connect",
            "status": "warn" if listening else "pass",
            "listening": listening,
            "note": (
                f"Port {port} is already accepting connections; inspect ownership before starting."
                if listening
                else f"Port {port} is currently free from this local check."
            ),
        }

    def _netstat_checks(self) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return [
                {
                    "name": "netstat-listeners",
                    "kind": "read-only-process-port-check",
                    "status": "warn",
                    "available": False,
                    "listeners": [],
                    "note": "netstat was unavailable; socket port checks still ran.",
                }
            ]
        listeners = self._parse_netstat_listeners(result.stdout)
        return [
            {
                "name": f"netstat-port-{port}",
                "kind": "read-only-process-port-check",
                "status": "warn" if listeners.get(port) else "pass",
                "available": True,
                "port": port,
                "listeners": listeners.get(port, []),
                "note": (
                    "Listener rows found. No action taken."
                    if listeners.get(port)
                    else "No listener row found in netstat output."
                ),
            }
            for port in [8000, 8501]
        ]

    def _parse_netstat_listeners(self, output: str) -> dict[int, list[dict[str, str]]]:
        listeners: dict[int, list[dict[str, str]]] = {8000: [], 8501: []}
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() not in {"TCP", "UDP"}:
                continue
            local_address = parts[1]
            state = parts[3] if parts[0].upper() == "TCP" and len(parts) >= 5 else ""
            pid = parts[-1]
            for port in listeners:
                if local_address.endswith(f":{port}") and (not state or state.upper() == "LISTENING"):
                    listeners[port].append(
                        {
                            "protocol": parts[0],
                            "local_address": local_address,
                            "state": state,
                            "pid": pid,
                        }
                    )
        return listeners

    def _data_ignore_check(self) -> dict[str, Any]:
        gitignore = self._read(".gitignore")
        data_ignored = any(line.strip().rstrip("/") == "data" for line in gitignore.splitlines())
        return {
            "name": "data-runtime-packs-ignored",
            "kind": "gitignore",
            "status": "pass" if data_ignored else "warn",
            "data_ignored": data_ignored,
            "runtime_pack_directory": "data/runtime_packs",
            "note": (
                "data/ is ignored; generated runtime packs stay local."
                if data_ignored
                else "Add data/ to .gitignore before committing generated runtime packs."
            ),
        }

    def _expected_ports(self) -> list[dict[str, Any]]:
        return [
            {
                "service": "FastAPI",
                "host": "127.0.0.1",
                "port": 8000,
                "base_url": LOCAL_API_BASE,
                "start_command": API_START_COMMAND,
            },
            {
                "service": "Streamlit",
                "host": "127.0.0.1",
                "port": 8501,
                "base_url": LOCAL_DASHBOARD_BASE,
                "start_command": DASHBOARD_START_COMMAND,
            },
        ]

    def _env_requirements(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "CONTROL_TOWER_API_BASE_URL",
                "required": False,
                "default": LOCAL_API_BASE,
                "used_by": "Streamlit dashboard",
            },
            {
                "name": "CONTROL_TOWER_API_KEY",
                "required": False,
                "default": DEMO_KEY,
                "used_by": "Streamlit dashboard and protected API calls",
            },
            {
                "name": "CONTROL_TOWER_STATE_FILE",
                "required": False,
                "default": "data/control_tower_state.json",
                "used_by": "local JSON state store",
            },
        ]

    def _health_checks(self) -> list[dict[str, str]]:
        return [
            {
                "label": "FastAPI health",
                "command": f"Invoke-RestMethod -Uri {LOCAL_API_BASE}/health",
                "expected": "JSON includes status=ok.",
            },
            {
                "label": "Runtime readiness",
                "command": f"Invoke-RestMethod -Uri {LOCAL_API_BASE}/runtime/demo-readiness",
                "expected": "JSON includes run_commands, expected_ports, dependency_checks, and health_urls.",
            },
            {
                "label": "Dashboard smoke",
                "command": RUNTIME_CHECK_COMMAND,
                "expected": "Console prints Runtime Demo Readiness and check counts without requiring a server.",
            },
            {
                "label": "Streamlit UI",
                "command": f"Start a browser at {LOCAL_DASHBOARD_BASE}",
                "expected": "Dashboard loads and includes a Runtime Demo tab.",
            },
        ]

    def _import_available(self, name: str) -> bool:
        try:
            __import__(name.replace("-", "_"))
        except ImportError:
            return False
        return True

    def _read(self, relative_path: str) -> str:
        path = self._repo_path(relative_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _repo_path(self, relative_path: str) -> Path:
        return self.repo_root / relative_path

    def _markdown(self, pack: dict[str, Any]) -> str:
        readiness = pack["readiness"]
        summary = readiness["summary"]
        install_rows = [f"- `{command}`" for command in pack["install_commands"]]
        start_rows = [f"- `{command}`" for command in pack["start_commands"]]
        stop_rows = [f"- {command}" for command in pack["stop_commands"]]
        health_rows = [
            f"- **{item['label']}**: `{item['command']}` Expected: {item['expected']}"
            for item in pack["health_checks"]
        ]
        flow_rows = [f"{index}. {step}" for index, step in enumerate(pack["demo_flow_order"], start=1)]
        screenshot_rows = [
            f"- **{item['view']}**: `{item['placeholder']}` - {item['what_to_capture']}"
            for item in pack["screenshot_checklist"]
        ]
        troubleshooting_rows = [f"- {item}" for item in pack["troubleshooting"]]
        limitation_rows = [f"- {item}" for item in pack["known_limitations"]]
        dependency_rows = [
            (
                f"| {item['name']} | {item['status']} | "
                f"{item['source_declared']} | {item['import_available']} |"
            )
            for item in readiness["dependency_checks"]
        ]
        port_rows = [
            f"| {item['name']} | {item['port']} | {item['status']} | {item['note']} |"
            for item in readiness["process_port_checks"]["socket_connect_checks"]
        ]
        return "\n".join(
            [
                f"# Runtime Demo Server Pack: {pack['pack_id']}",
                "",
                "## Readiness",
                f"- Status: **{readiness['status']}**",
                f"- Total checks: {summary['total_checks']}",
                f"- Failed checks: {summary['failed_checks']}",
                f"- Warning checks: {summary['warning_checks']}",
                f"- Local/mock only: {readiness['local_mock_only']}",
                "",
                "## Install Commands",
                *install_rows,
                "",
                "## Start Commands",
                *start_rows,
                f"- Optional script: `{pack['start_script_command']}`",
                "",
                "## Stop Commands",
                *stop_rows,
                "",
                "## Health Checks",
                *health_rows,
                "",
                "## Demo Flow Order",
                *flow_rows,
                "",
                "## Dependency Checks",
                "| Dependency | Status | Declared | Importable |",
                "| --- | --- | --- | --- |",
                *dependency_rows,
                "",
                "## Read-Only Port Checks",
                "| Service | Port | Status | Note |",
                "| --- | ---: | --- | --- |",
                *port_rows,
                "",
                "## Screenshot Checklist",
                *screenshot_rows,
                "",
                "## Troubleshooting",
                *troubleshooting_rows,
                "",
                "## Recruiter Explanation",
                pack["recruiter_explanation"],
                "",
                "## Engineer Explanation",
                pack["engineer_explanation"],
                "",
                "## Known Limitations",
                *limitation_rows,
                "",
            ]
        )


def build_runtime_readiness_for_cli() -> dict[str, Any]:
    service = RuntimeDemoService(Path("data/runtime_packs"))
    return service.readiness_sync()


def print_runtime_readiness(readiness: dict[str, Any]) -> int:
    summary = readiness["summary"]
    print("Runtime Demo Readiness:", readiness["status"].upper())
    print(
        "Checks:",
        f"total={summary['total_checks']}",
        f"passed={summary['passed_checks']}",
        f"warnings={summary['warning_checks']}",
        f"failed={summary['failed_checks']}",
    )
    print("Run commands:")
    print(f"- API: {API_START_COMMAND}")
    print(f"- Streamlit: {DASHBOARD_START_COMMAND}")
    print(f"- Runtime check: {RUNTIME_CHECK_COMMAND}")
    print(f"- Demo run: {DEMO_RUN_COMMAND}")
    print("Expected health URLs:")
    for url in readiness["health_urls"]:
        print(f"- {url}")
    print("Dependency checks:")
    for check in readiness["dependency_checks"]:
        print(
            f"- {check['status'].upper()} {check['name']} "
            f"(declared={check['source_declared']}, importable={check['import_available']})"
        )
    print("Port checks:")
    for check in readiness["process_port_checks"]["socket_connect_checks"]:
        print(f"- {check['status'].upper()} {check['name']} port {check['port']}: {check['note']}")
    return 1 if readiness["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(print_runtime_readiness(build_runtime_readiness_for_cli()))
