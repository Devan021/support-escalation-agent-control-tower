import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from app.core.security import require_api_key
from app.services.artifacts import EXTRA_ARTIFACTS
from app.services.demo import SCENARIO_ENDPOINTS
from app.services.launch_checklist import DEMO_KEY, EXPECTED_ARTIFACTS, LOCAL_API_BASE
from app.services.ui_verification import UIVerificationService


VERIFY_COMMANDS = [
    r".\.venv\Scripts\python.exe -m pytest -q",
    r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
    r".\.venv\Scripts\python.exe -m app.evals.run_eval",
    r".\.venv\Scripts\python.exe scripts\dashboard_smoke.py",
    r".\.venv\Scripts\python.exe scripts\demo_run.py",
    (
        r'rg "api/contract-audit|api/reviewer-collection|API Contract|api_contracts|'
        r'Reviewer Collection|OpenAPI|runtime/demo-readiness|runtime/demo-pack" app dashboard docs README.md tests scripts'
    ),
    (
        r'rg "handoff/on-call-summary|handoff/customer-comms-pack|On-Call Handoff|'
        r'Customer Communications|customer_comms_packs|communication readiness" '
        r"app dashboard docs README.md tests scripts sample_data"
    ),
    (
        r'rg "scenarios/catalog|scenarios/eval-pack|Scenario Dataset|scenario_packs|'
        r'scenario coverage|scenario catalog" app dashboard docs README.md tests scripts sample_data'
    ),
    (
        r'rg "incidents/postmortem-summary|incidents/rca-pack|Postmortem RCA|'
        r'Corrective Action|rca_packs|root cause" app dashboard docs README.md tests scripts sample_data'
    ),
    (
        r"Get-ChildItem -Recurse -File data\api_contracts -ErrorAction SilentlyContinue "
        r"| Select-Object FullName,Length,LastWriteTime"
    ),
]

IMPORTANT_ENDPOINTS = [
    "GET /health",
    "POST /auth/demo-token",
    "GET /tickets",
    "POST /tickets/{ticket_id}/analyze",
    "GET /runs/{run_id}/trace",
    "POST /runs/{run_id}/approve",
    "GET /integrations/outbox",
    "GET /ops/smoke-matrix",
    "POST /ops/launch-checklist",
    "GET /reviewer/quickstart",
    "POST /reviewer/walkthrough-pack",
    "GET /artifacts/inventory",
    "POST /artifacts/readme-checklist",
    "GET /ui/dashboard-smoke",
    "POST /ui/verification-pack",
    "GET /handoff/final-audit",
    "POST /handoff/final-pack",
    "GET /handoff/on-call-summary",
    "POST /handoff/customer-comms-pack",
    "GET /incidents/postmortem-summary",
    "POST /incidents/rca-pack",
    "GET /git/readiness",
    "POST /git/push-plan",
    "GET /api/contract-audit",
    "POST /api/reviewer-collection",
    "GET /runtime/demo-readiness",
    "POST /runtime/demo-pack",
    "GET /scenarios/catalog",
    "POST /scenarios/eval-pack",
]

LOCAL_ONLY_LIMITATIONS = [
    "Contract checks inspect the local FastAPI app, source files, docs, and generated artifact directories.",
    "Auth protection is inferred from FastAPI route dependencies, not from a deployed gateway or WAF.",
    "Generated reviewer collection files under data/api_contracts are ignored local proof and should be regenerated.",
    "The collection uses local mock integrations and does not call Azure, OpenAI, Zendesk, Jira, Slack, GitHub, or SaaS APIs.",
    "Parameterized endpoint commands require replacing path placeholders such as {run_id} and {ticket_id}.",
]


class ApiContractService:
    def __init__(self, api_contracts_dir: Path):
        self.api_contracts_dir = api_contracts_dir
        self.data_root = api_contracts_dir.parent
        self.repo_root = Path(__file__).resolve().parents[2]

    async def audit(self, app: Any) -> dict[str, Any]:
        return self.audit_sync(app)

    async def export_reviewer_collection(self, app: Any) -> dict[str, Any]:
        audit = self.audit_sync(app)
        generated_at = datetime.now(timezone.utc)
        collection_id = f"api_reviewer_collection_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        json_path = self.api_contracts_dir / f"{collection_id}.json"
        markdown_path = self.api_contracts_dir / f"{collection_id}.md"
        collection = {
            "collection_id": collection_id,
            "generated_at": generated_at.isoformat(),
            "title": "API Contract Reviewer Collection",
            "api_base": LOCAL_API_BASE,
            "auth": self._auth_notes(),
            "contract_audit": audit,
            "endpoint_inventory_by_domain": audit["endpoint_inventory_by_domain"],
            "sample_commands_by_domain": self._sample_commands_by_domain(audit["endpoint_inventory"]),
            "demo_token_flow": self._demo_token_flow(),
            "expected_status_codes": self._expected_status_codes(audit["endpoint_inventory"]),
            "generated_artifact_endpoints": audit["generated_artifact_endpoint_coverage"],
            "one_command_verification_order": VERIFY_COMMANDS,
            "recruiter_explanation": self._recruiter_explanation(audit),
            "engineer_explanation": self._engineer_explanation(audit),
            "limitations": LOCAL_ONLY_LIMITATIONS,
            "artifact_paths": {
                "reviewer_collection_markdown": str(markdown_path),
                "reviewer_collection_json": str(json_path),
            },
        }
        markdown = self._markdown(collection)
        self.api_contracts_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(collection, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return {
            "collection_id": collection_id,
            "format": "markdown+json",
            "status": audit["status"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "contract_summary": audit["summary"],
            "collection": collection,
            "markdown": markdown,
        }

    def audit_sync(self, app: Any) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc)
        openapi = app.openapi()
        route_rows = self._route_inventory(app, openapi)
        endpoint_set = {row["endpoint"] for row in route_rows}
        dashboard_smoke = UIVerificationService(self.data_root / "ui_verification").dashboard_smoke_sync()
        docs_coverage = self._important_docs_coverage(endpoint_set)
        artifact_coverage = self._generated_artifact_endpoint_coverage(endpoint_set)
        demo_coverage = self._demo_flow_endpoint_coverage(endpoint_set)
        duplicate_warnings = self._duplicate_route_warnings(route_rows, openapi)
        deprecated_warnings = self._deprecated_route_warnings(route_rows)
        missing_docs_warnings = [
            f"{item['endpoint']} is missing from {item['source']}"
            for item in docs_coverage["important_endpoint_coverage"]
            if not item["present"]
        ]
        dashboard_failures = [
            check["name"]
            for check in dashboard_smoke["checks"]
            if check["status"] == "fail"
            and (
                "/api/contract-audit" in check["name"]
                or "/api/reviewer-collection" in check["name"]
                or "API Contract" in check["name"]
            )
        ]
        warnings = [
            *missing_docs_warnings,
            *deprecated_warnings,
            *duplicate_warnings,
            *dashboard_failures,
        ]
        status = "ready" if not warnings else "ready_with_warnings"
        auth_protected_count = len([row for row in route_rows if row["requires_api_key"]])
        return {
            "generated_at": generated_at.isoformat(),
            "title": "API Contract Audit",
            "status": status,
            "mode": "local-openapi-source-contract-audit",
            "local_mock_only": True,
            "summary": {
                "openapi_route_count": len(route_rows),
                "openapi_path_count": len(openapi.get("paths", {})),
                "auth_protected_endpoint_count": auth_protected_count,
                "important_endpoint_count": len(IMPORTANT_ENDPOINTS),
                "missing_docs_warning_count": len(missing_docs_warnings),
                "deprecated_route_warning_count": len(deprecated_warnings),
                "duplicate_route_warning_count": len(duplicate_warnings),
                "generated_artifact_endpoint_count": len(artifact_coverage),
                "demo_flow_endpoint_count": len(demo_coverage["endpoints"]),
                "dashboard_smoke_status": dashboard_smoke["status"],
            },
            "openapi": {
                "title": openapi.get("info", {}).get("title"),
                "version": openapi.get("info", {}).get("version"),
                "route_count": len(route_rows),
                "path_count": len(openapi.get("paths", {})),
                "methods": dict(Counter(row["method"] for row in route_rows)),
            },
            "auth_protection": {
                "protected_endpoint_count": auth_protected_count,
                "public_endpoint_count": len(route_rows) - auth_protected_count,
                "protected_endpoints": [row["endpoint"] for row in route_rows if row["requires_api_key"]],
                "public_endpoints": [row["endpoint"] for row in route_rows if not row["requires_api_key"]],
                "auth_notes": self._auth_notes(),
            },
            "docs_api_coverage": docs_coverage,
            "dashboard_smoke_alignment": {
                "status": dashboard_smoke["status"],
                "summary": dashboard_smoke["summary"],
                "api_contract_view_present": any(
                    item["label"] == "API Contract" and item["present"]
                    for item in dashboard_smoke["expected_views"]
                ),
                "api_contract_endpoint_checks": [
                    item
                    for item in dashboard_smoke["endpoint_references"]
                    if item["path"] in {"/api/contract-audit", "/api/reviewer-collection"}
                ],
            },
            "generated_artifact_endpoint_coverage": artifact_coverage,
            "demo_flow_endpoint_coverage": demo_coverage,
            "missing_docs_warnings": missing_docs_warnings,
            "deprecated_route_warnings": deprecated_warnings,
            "duplicate_route_warnings": duplicate_warnings,
            "local_only_limitations": LOCAL_ONLY_LIMITATIONS,
            "endpoint_inventory": route_rows,
            "endpoint_inventory_by_domain": self._group_by_domain(route_rows),
            "reviewer_collection_endpoint": "POST /api/reviewer-collection",
            "reviewer_collection_directory": self._canonical_data_dir(),
            "verification_commands": VERIFY_COMMANDS,
        }

    def _route_inventory(self, app: Any, openapi: dict[str, Any]) -> list[dict[str, Any]]:
        protected = self._protected_route_keys(app)
        rows = []
        for path, operations in openapi.get("paths", {}).items():
            for method, operation in operations.items():
                if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    continue
                endpoint = f"{method.upper()} {path}"
                rows.append(
                    {
                        "method": method.upper(),
                        "path": path,
                        "endpoint": endpoint,
                        "domain": self._domain(path),
                        "operation_id": operation.get("operationId", ""),
                        "summary": operation.get("summary") or operation.get("description") or "",
                        "requires_api_key": (method.upper(), path) in protected,
                        "expected_status": 200,
                        "auth_note": "Requires X-API-Key or Bearer demo token."
                        if (method.upper(), path) in protected
                        else "Public local endpoint.",
                        "deprecated": bool(operation.get("deprecated", False)),
                        "curl": self._curl_command(method.upper(), path, True),
                        "powershell": self._powershell_command(method.upper(), path, True),
                    }
                )
        rows.sort(key=lambda row: (row["domain"], row["path"], row["method"]))
        return rows

    def _protected_route_keys(self, app: Any) -> set[tuple[str, str]]:
        keys = set()
        for route in getattr(app, "routes", []):
            if not isinstance(route, APIRoute):
                continue
            if not self._route_requires_api_key(route):
                continue
            for method in route.methods or set():
                if method in {"HEAD", "OPTIONS"}:
                    continue
                keys.add((method, route.path))
        return keys

    def _route_requires_api_key(self, route: APIRoute) -> bool:
        dependency_calls = [dependency.call for dependency in route.dependant.dependencies]
        return require_api_key in dependency_calls or any(
            getattr(call, "__name__", "") == "require_api_key" for call in dependency_calls
        )

    def _important_docs_coverage(self, endpoint_set: set[str]) -> dict[str, Any]:
        sources = {
            "docs/api.md": self._read_repo_file("docs/api.md"),
            "README.md": self._read_repo_file("README.md"),
        }
        rows = []
        for endpoint in IMPORTANT_ENDPOINTS:
            method, path = endpoint.split(" ", 1)
            route_present = endpoint in endpoint_set
            for source, text in sources.items():
                rows.append(
                    {
                        "endpoint": endpoint,
                        "method": method,
                        "path": path,
                        "source": source,
                        "route_present": route_present,
                        "present": path in text or endpoint in text,
                    }
                )
        missing = [row for row in rows if not row["present"]]
        return {
            "important_endpoint_coverage": rows,
            "important_endpoint_count": len(IMPORTANT_ENDPOINTS),
            "covered_check_count": len(rows) - len(missing),
            "missing_check_count": len(missing),
            "sources_checked": list(sources),
        }

    def _generated_artifact_endpoint_coverage(self, endpoint_set: set[str]) -> list[dict[str, Any]]:
        dashboard_text = self._read_repo_file("dashboard/streamlit_app.py")
        docs_text = self._read_repo_file("docs/api.md")
        artifact_rows = []
        seen = set()
        for item in [*EXPECTED_ARTIFACTS, *EXTRA_ARTIFACTS]:
            producer = item["producer"]
            if not producer.startswith(("GET ", "POST ")):
                continue
            if producer in seen:
                continue
            seen.add(producer)
            method, path = producer.split(" ", 1)
            artifact_rows.append(
                {
                    "name": item["name"],
                    "producer": producer,
                    "method": method,
                    "path": path,
                    "artifact_directory": item["directory"],
                    "route_present": producer in endpoint_set,
                    "docs_api_present": path in docs_text,
                    "dashboard_reference_present": path in dashboard_text,
                }
            )
        return artifact_rows

    def _demo_flow_endpoint_coverage(self, endpoint_set: set[str]) -> dict[str, Any]:
        endpoints = [
            *SCENARIO_ENDPOINTS,
            "GET /api/contract-audit",
            "POST /api/reviewer-collection",
            "GET /runtime/demo-readiness",
            "POST /runtime/demo-pack",
            "GET /scenarios/catalog",
            "POST /scenarios/eval-pack",
            "GET /handoff/on-call-summary",
            "POST /handoff/customer-comms-pack",
            "GET /incidents/postmortem-summary",
            "POST /incidents/rca-pack",
        ]
        rows = [
            {
                "endpoint": endpoint,
                "route_present": endpoint in endpoint_set,
                "covered_by_demo_output": endpoint in {"GET /api/contract-audit", "POST /api/reviewer-collection"}
                or endpoint in SCENARIO_ENDPOINTS,
            }
            for endpoint in endpoints
        ]
        return {
            "endpoints": rows,
            "route_coverage_count": len([row for row in rows if row["route_present"]]),
            "missing_routes": [row["endpoint"] for row in rows if not row["route_present"]],
            "demo_output_notes": [
                "scripts/demo_run.py prints the API Contract Audit status and Reviewer Collection path.",
                "scripts/demo_run.py prints the Runtime Demo readiness status and Runtime Demo Pack path.",
                "scripts/demo_run.py prints scenario catalog coverage and Scenario Dataset Eval Coverage Pack paths.",
                "The deterministic scenario still covers the ticket-to-approval-to-artifact workflow endpoints.",
                "The RCA flow covers root cause, corrective actions, customer follow-up state, and scenario coverage.",
            ],
        }

    def _duplicate_route_warnings(self, rows: list[dict[str, Any]], openapi: dict[str, Any]) -> list[str]:
        endpoint_counts = Counter(row["endpoint"] for row in rows)
        operation_counts = Counter(row["operation_id"] for row in rows if row["operation_id"])
        warnings = [
            f"Duplicate route registered: {endpoint}"
            for endpoint, count in endpoint_counts.items()
            if count > 1
        ]
        warnings.extend(
            f"Duplicate OpenAPI operationId registered: {operation_id}"
            for operation_id, count in operation_counts.items()
            if count > 1
        )
        if not openapi.get("paths"):
            warnings.append("OpenAPI schema has no paths.")
        return warnings

    def _deprecated_route_warnings(self, rows: list[dict[str, Any]]) -> list[str]:
        return [
            f"Deprecated route present in OpenAPI: {row['endpoint']}"
            for row in rows
            if row["deprecated"]
        ]

    def _group_by_domain(self, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["domain"]].append(row)
        return dict(sorted(grouped.items()))

    def _sample_commands_by_domain(self, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[row["domain"]].append(
                {
                    "endpoint": row["endpoint"],
                    "curl": row["curl"],
                    "powershell": row["powershell"],
                }
            )
        return dict(sorted(grouped.items()))

    def _expected_status_codes(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "endpoint": row["endpoint"],
                "authenticated_status": 200,
                "unauthenticated_status": 401 if row["requires_api_key"] else 200,
                "notes": "Use valid path parameters and JSON body where required.",
            }
            for row in rows
        ]

    def _auth_notes(self) -> dict[str, Any]:
        return {
            "demo_token_endpoint": "POST /auth/demo-token",
            "header": "X-API-Key",
            "default_key": DEMO_KEY,
            "bearer_alternative": f"Authorization: Bearer {DEMO_KEY}",
        }

    def _demo_token_flow(self) -> list[dict[str, str]]:
        return [
            {
                "step": "Fetch demo token",
                "curl": f"curl.exe -X POST {LOCAL_API_BASE}/auth/demo-token",
                "powershell": (
                    "$token = (Invoke-RestMethod -Method Post "
                    f"-Uri {LOCAL_API_BASE}/auth/demo-token).token"
                ),
            },
            {
                "step": "Call protected audit",
                "curl": self._curl_command("GET", "/api/contract-audit", True),
                "powershell": self._powershell_command("GET", "/api/contract-audit", True),
            },
            {
                "step": "Export reviewer collection",
                "curl": self._curl_command("POST", "/api/reviewer-collection", True),
                "powershell": self._powershell_command("POST", "/api/reviewer-collection", True),
            },
        ]

    def _recruiter_explanation(self, audit: dict[str, Any]) -> list[str]:
        return [
            "The API Contract Audit turns the local OpenAPI surface into a reviewer-ready checklist.",
            (
                f"It currently sees {audit['summary']['openapi_route_count']} routes and "
                f"{audit['summary']['auth_protected_endpoint_count']} API-key protected endpoints."
            ),
            "The Reviewer Collection writes Markdown and JSON that a fresh-clone reviewer can run without cloud credentials.",
            "Dashboard, docs, demo, and generated artifact coverage are checked from source so the proof is repeatable.",
        ]

    def _engineer_explanation(self, audit: dict[str, Any]) -> list[str]:
        return [
            "Route inventory is derived from FastAPI OpenAPI output and APIRoute dependency metadata.",
            "Docs coverage checks important endpoints in README.md and docs/api.md.",
            "Dashboard alignment reuses the deterministic dashboard smoke service.",
            (
                "Generated artifact coverage compares producer endpoints against routes, docs, and dashboard source; "
                f"{audit['summary']['generated_artifact_endpoint_count']} producers are tracked."
            ),
            "The feature is local-only and deterministic, with no destructive git or external API operations.",
        ]

    def _domain(self, path: str) -> str:
        parts = [part for part in path.split("/") if part and not part.startswith("{")]
        return parts[0] if parts else "root"

    def _curl_command(self, method: str, path: str, include_key: bool) -> str:
        headers = f' -H "X-API-Key: {DEMO_KEY}"' if include_key else ""
        return f"curl.exe -X {method} {LOCAL_API_BASE}{path}{headers}"

    def _powershell_command(self, method: str, path: str, include_key: bool) -> str:
        headers = f" -Headers @{{'X-API-Key'='{DEMO_KEY}'}}" if include_key else ""
        return f"Invoke-RestMethod -Method {method.title()} -Uri {LOCAL_API_BASE}{path}{headers}"

    def _read_repo_file(self, relative_path: str) -> str:
        path = self.repo_root / relative_path
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _canonical_data_dir(self) -> str:
        try:
            relative = self.api_contracts_dir.relative_to(self.data_root)
            return str(Path("data") / relative).replace("/", "\\")
        except ValueError:
            return str(self.api_contracts_dir)

    def _markdown(self, collection: dict[str, Any]) -> str:
        audit = collection["contract_audit"]
        summary = audit["summary"]
        command_rows = [f"- `{command}`" for command in collection["one_command_verification_order"]]
        auth_rows = [f"- **{key}**: `{value}`" for key, value in collection["auth"].items()]
        domain_rows = [
            f"- **{domain}**: {len(rows)} endpoints"
            for domain, rows in collection["endpoint_inventory_by_domain"].items()
        ]
        artifact_rows = [
            (
                f"| {item['name']} | `{item['producer']}` | `{item['artifact_directory']}` | "
                f"{item['route_present']} | {item['docs_api_present']} | {item['dashboard_reference_present']} |"
            )
            for item in collection["generated_artifact_endpoints"]
        ]
        demo_rows = [
            f"- `{item['endpoint']}` route_present={item['route_present']}"
            for item in audit["demo_flow_endpoint_coverage"]["endpoints"]
        ]
        limitation_rows = [f"- {item}" for item in collection["limitations"]]
        recruiter_rows = [f"- {item}" for item in collection["recruiter_explanation"]]
        engineer_rows = [f"- {item}" for item in collection["engineer_explanation"]]
        command_examples = []
        for domain, rows in collection["sample_commands_by_domain"].items():
            command_examples.append(f"### {domain}")
            for row in rows[:4]:
                command_examples.append(f"- `{row['endpoint']}`")
                command_examples.append(f"  - curl: `{row['curl']}`")
                command_examples.append(f"  - PowerShell: `{row['powershell']}`")
        return "\n".join(
            [
                f"# API Contract Reviewer Collection: {collection['collection_id']}",
                "",
                "## OpenAPI Contract Summary",
                f"- Status: **{audit['status']}**",
                f"- OpenAPI routes: {summary['openapi_route_count']}",
                f"- Auth-protected endpoints: {summary['auth_protected_endpoint_count']}",
                f"- Dashboard smoke: {summary['dashboard_smoke_status']}",
                f"- Missing docs warnings: {summary['missing_docs_warning_count']}",
                "",
                "## Auth Notes",
                *auth_rows,
                "",
                "## Endpoint Inventory by Domain",
                *domain_rows,
                "",
                "## Sample Commands",
                *command_examples,
                "",
                "## Demo Token Flow",
                "- Fetch `POST /auth/demo-token`, then pass `X-API-Key` to protected endpoints.",
                "",
                "## Generated Artifact Endpoints",
                "| Artifact | Producer | Directory | Route | docs/api | Dashboard |",
                "| --- | --- | --- | --- | --- | --- |",
                *artifact_rows,
                "",
                "## Demo Flow Endpoint Coverage",
                *demo_rows,
                "",
                "## One-Command Verification Order",
                *command_rows,
                "",
                "## Recruiter Explanation",
                *recruiter_rows,
                "",
                "## Engineer Explanation",
                *engineer_rows,
                "",
                "## Limitations",
                *limitation_rows,
                "",
            ]
        )
