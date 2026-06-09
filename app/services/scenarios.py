import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import AuditEvent, TicketCreate
from app.services.audit import AuditService
from app.services.tickets import TicketService
from app.services.workflow import AgentWorkflowService


SCENARIO_VERIFY_COMMANDS = [
    r".\.venv\Scripts\python.exe -m pytest -q",
    r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
    r".\.venv\Scripts\python.exe -m app.evals.run_eval",
    r".\.venv\Scripts\python.exe scripts\dashboard_smoke.py",
    r".\.venv\Scripts\python.exe scripts\demo_run.py",
    (
        r'rg "scenarios/catalog|scenarios/eval-pack|Scenario Dataset|scenario_packs|'
        r'scenario coverage|scenario catalog" app dashboard docs README.md tests scripts sample_data'
    ),
    (
        r"Get-ChildItem -Recurse -File data\scenario_packs -ErrorAction SilentlyContinue "
        r"| Select-Object FullName,Length,LastWriteTime"
    ),
]


class ScenarioCatalogService:
    """Enterprise scenario catalog and deterministic local eval-pack exporter."""

    def __init__(
        self,
        tickets: TicketService,
        workflow: AgentWorkflowService,
        audit: AuditService,
        fixture_path: Path,
        scenario_packs_dir: Path,
    ):
        self.tickets = tickets
        self.workflow = workflow
        self.audit = audit
        self.fixture_path = fixture_path
        self.scenario_packs_dir = scenario_packs_dir

    async def catalog(self) -> dict[str, Any]:
        scenarios = self._load_scenarios()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "title": "Scenario Dataset Catalog",
            "mode": "local-deterministic-scenario-catalog",
            "local_mock_only": True,
            "fixture_path": str(self.fixture_path),
            "scenario_count": len(scenarios),
            "coverage_summary": self._coverage_summary(scenarios),
            "scenarios": [self._catalog_row(item) for item in scenarios],
            "local_commands": {
                "eval_pack_endpoint": "POST /scenarios/eval-pack",
                "list_generated_packs": SCENARIO_VERIFY_COMMANDS[-1],
                "verify": SCENARIO_VERIFY_COMMANDS,
            },
        }

    async def export_eval_pack(self) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc)
        scenarios = self._load_scenarios()
        eval_rows = []
        for scenario in scenarios:
            eval_rows.append(await self._evaluate_scenario(scenario))

        summary = self._eval_summary(eval_rows)
        pack_id = f"scenario_eval_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        json_path = self.scenario_packs_dir / f"{pack_id}.json"
        markdown_path = self.scenario_packs_dir / f"{pack_id}.md"
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "title": "Scenario Dataset Eval Coverage Pack",
            "mode": "local-deterministic-scenario-eval-pack",
            "fixture_path": str(self.fixture_path),
            "scenario_count": len(scenarios),
            "status": summary["status"],
            "coverage_summary": self._coverage_summary(scenarios),
            "eval_summary": summary,
            "scenario_results": eval_rows,
            "gaps_and_warnings": self._gaps_and_warnings(scenarios, eval_rows, summary),
            "local_commands": SCENARIO_VERIFY_COMMANDS,
            "artifact_paths": {
                "scenario_eval_pack_markdown": str(markdown_path),
                "scenario_eval_pack_json": str(json_path),
            },
        }
        markdown = self._markdown(pack)
        self.scenario_packs_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        await self.audit.record(
            AuditEvent(
                actor="scenario-eval",
                action="scenarios.eval_pack_exported",
                resource_type="scenario_eval_pack",
                resource_id=pack_id,
                metadata={"markdown_path": str(markdown_path), "json_path": str(json_path)},
            )
        )
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "status": summary["status"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "eval_summary": summary,
            "pack": pack,
            "markdown": markdown,
        }

    def _load_scenarios(self) -> list[dict[str, Any]]:
        return json.loads(self.fixture_path.read_text(encoding="utf-8"))

    def _catalog_row(self, scenario: dict[str, Any]) -> dict[str, Any]:
        expected = scenario["expected"]
        ticket = scenario["ticket"]
        return {
            "scenario_id": scenario["scenario_id"],
            "title": scenario["title"],
            "domain": scenario["domain"],
            "persona": scenario["persona"],
            "customer": ticket.get("customer"),
            "customer_tier": ticket.get("customer_tier"),
            "priority": ticket.get("priority"),
            "tags": ticket.get("tags", []),
            "expected_outcomes": {
                "classification_category": expected["classification_category"],
                "sla_level": expected["sla_level"],
                "engineering_escalation": expected["should_escalate"],
                "approval_pause": expected["approval_pause"],
                "low_confidence_review": expected["low_confidence_review"],
                "failure_state": expected["failure_state"],
                "tool_retry": expected["tool_retry"],
            },
        }

    def _coverage_summary(self, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
        domains = Counter(item["domain"] for item in scenarios)
        expected_categories = Counter(
            item["expected"]["classification_category"] for item in scenarios
        )
        expected_sla = Counter(item["expected"]["sla_level"] for item in scenarios)
        return {
            "scenario coverage": "enterprise support portfolio scenario coverage",
            "domain_count": len(domains),
            "domains": dict(sorted(domains.items())),
            "required_domains_present": self._required_domain_presence(domains),
            "expected_classifications": dict(sorted(expected_categories.items())),
            "expected_sla_levels": dict(sorted(expected_sla.items())),
            "approval_pause_expected_count": sum(
                1 for item in scenarios if item["expected"]["approval_pause"]
            ),
            "escalation_expected_count": sum(
                1 for item in scenarios if item["expected"]["should_escalate"]
            ),
            "low_confidence_review_expected_count": sum(
                1 for item in scenarios if item["expected"]["low_confidence_review"]
            ),
            "failure_state_expected_count": sum(
                1 for item in scenarios if item["expected"]["failure_state"]
            ),
            "tool_retry_expected_count": sum(
                1 for item in scenarios if item["expected"]["tool_retry"]
            ),
        }

    def _required_domain_presence(self, domains: Counter) -> dict[str, bool]:
        required = [
            "security",
            "billing",
            "data_export_privacy",
            "outage",
            "webhook_api",
            "enterprise_onboarding",
            "renewal_risk",
            "low_confidence_ambiguity",
        ]
        return {domain: domain in domains for domain in required}

    async def _evaluate_scenario(self, scenario: dict[str, Any]) -> dict[str, Any]:
        expected = scenario["expected"]
        ticket_payload = TicketCreate(**scenario["ticket"])
        ticket = await self.tickets.ingest(ticket_payload)
        run = await self.workflow.analyze_ticket(ticket.ticket_id)
        state = run.state
        actual = {
            "classification_category": state["classification"]["category"],
            "classification_confidence": state["classification"]["confidence"],
            "sla_level": state["sla_risk"]["level"],
            "sla_score": state["sla_risk"]["score"],
            "engineering_escalation": bool(
                state.get("drafts", {}).get("engineering_escalation")
            ),
            "approval_pause": str(run.status) == "awaiting_approval",
            "low_confidence_review": bool(
                state.get("qa", {}).get("requires_human_review")
                and state.get("qa", {}).get("confidence", 1.0) < self.workflow.low_confidence_threshold
            ),
            "failure_state": bool(run.failure_state),
            "tool_retry": self._tool_error_count(state) > 0,
            "tool_error_count": self._tool_error_count(state),
            "tool_call_count": len(state.get("tool_calls", [])),
            "qa_findings": state.get("qa", {}).get("findings", []),
            "run_id": run.run_id,
            "ticket_id": ticket.ticket_id,
            "final_action": run.final_action,
        }
        checks = {
            "classification": actual["classification_category"]
            == expected["classification_category"],
            "sla_routing": actual["sla_level"] == expected["sla_level"],
            "approval_pause": actual["approval_pause"] == expected["approval_pause"],
            "engineering_escalation": actual["engineering_escalation"]
            == expected["should_escalate"],
            "low_confidence_review": actual["low_confidence_review"]
            == expected["low_confidence_review"],
            "failure_state": actual["failure_state"] == expected["failure_state"],
            "tool_retry": actual["tool_retry"] == expected["tool_retry"],
        }
        return {
            "scenario_id": scenario["scenario_id"],
            "title": scenario["title"],
            "domain": scenario["domain"],
            "expected": self._catalog_row(scenario)["expected_outcomes"],
            "actual": actual,
            "checks": checks,
            "passed": all(checks.values()),
        }

    def _tool_error_count(self, state: dict[str, Any]) -> int:
        return len(
            [
                call
                for call in state.get("tool_calls", [])
                if call.get("status") == "error"
            ]
        )

    def _eval_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(rows) or 1
        check_names = [
            "classification",
            "sla_routing",
            "approval_pause",
            "engineering_escalation",
            "low_confidence_review",
            "failure_state",
            "tool_retry",
        ]
        coverage = {
            name: {
                "correct": sum(1 for row in rows if row["checks"][name]),
                "total": len(rows),
                "accuracy_percent": round(
                    (sum(1 for row in rows if row["checks"][name]) / total) * 100,
                    2,
                ),
            }
            for name in check_names
        }
        represented = {
            "approval_pause_actual_count": sum(
                1 for row in rows if row["actual"]["approval_pause"]
            ),
            "engineering_escalation_actual_count": sum(
                1 for row in rows if row["actual"]["engineering_escalation"]
            ),
            "low_confidence_review_actual_count": sum(
                1 for row in rows if row["actual"]["low_confidence_review"]
            ),
            "failure_state_actual_count": sum(
                1 for row in rows if row["actual"]["failure_state"]
            ),
            "tool_retry_actual_count": sum(1 for row in rows if row["actual"]["tool_retry"]),
            "tool_error_count": sum(row["actual"]["tool_error_count"] for row in rows),
        }
        failed = [row for row in rows if not row["passed"]]
        return {
            "status": "pass" if not failed else "fail",
            "scenario_count": len(rows),
            "passed_scenario_count": len(rows) - len(failed),
            "failed_scenario_count": len(failed),
            "classification_accuracy": coverage["classification"],
            "sla_routing": coverage["sla_routing"],
            "approval_pause_coverage": coverage["approval_pause"],
            "escalation_coverage": coverage["engineering_escalation"],
            "low_confidence_review_coverage": coverage["low_confidence_review"],
            "failure_state_coverage": coverage["failure_state"],
            "tool_retry_coverage": coverage["tool_retry"],
            "represented_outcome_counts": represented,
        }

    def _gaps_and_warnings(
        self,
        scenarios: list[dict[str, Any]],
        rows: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> list[str]:
        warnings = []
        missing_domains = [
            domain
            for domain, present in self._coverage_summary(scenarios)[
                "required_domains_present"
            ].items()
            if not present
        ]
        if missing_domains:
            warnings.append(f"Missing required scenario domains: {', '.join(missing_domains)}.")
        for row in rows:
            if not row["passed"]:
                failed_checks = [
                    name for name, passed in row["checks"].items() if not passed
                ]
                warnings.append(
                    f"{row['scenario_id']} mismatched checks: {', '.join(failed_checks)}."
                )
        counts = summary["represented_outcome_counts"]
        if counts["low_confidence_review_actual_count"] == 0:
            warnings.append("No low-confidence human-review path was represented.")
        if counts["failure_state_actual_count"] == 0 and counts["tool_retry_actual_count"] == 0:
            warnings.append("No failure or tool-retry path was represented.")
        if not warnings:
            warnings.append("No coverage gaps detected in the local deterministic scenario pack.")
        return warnings

    def _markdown(self, pack: dict[str, Any]) -> str:
        summary = pack["eval_summary"]
        coverage = pack["coverage_summary"]
        commands = [f"- `{command}`" for command in pack["local_commands"]]
        warnings = [f"- {item}" for item in pack["gaps_and_warnings"]]
        domain_rows = [
            f"| {domain} | {count} |"
            for domain, count in coverage["domains"].items()
        ]
        result_rows = [
            (
                f"| {row['scenario_id']} | {row['domain']} | "
                f"{row['actual']['classification_category']} | {row['actual']['sla_level']} | "
                f"{row['actual']['engineering_escalation']} | "
                f"{row['actual']['low_confidence_review']} | "
                f"{row['actual']['failure_state']} | {row['passed']} |"
            )
            for row in pack["scenario_results"]
        ]
        return "\n".join(
            [
                f"# Scenario Dataset Eval Coverage Pack: {pack['pack_id']}",
                "",
                "## Summary",
                f"- Status: **{summary['status']}**",
                f"- Scenarios: {summary['scenario_count']}",
                f"- Passed scenarios: {summary['passed_scenario_count']}",
                f"- Failed scenarios: {summary['failed_scenario_count']}",
                (
                    "- Classification accuracy: "
                    f"{summary['classification_accuracy']['correct']}/"
                    f"{summary['classification_accuracy']['total']}"
                ),
                (
                    "- SLA routing: "
                    f"{summary['sla_routing']['correct']}/"
                    f"{summary['sla_routing']['total']}"
                ),
                (
                    "- Approval pause coverage: "
                    f"{summary['approval_pause_coverage']['correct']}/"
                    f"{summary['approval_pause_coverage']['total']}"
                ),
                (
                    "- Escalation coverage: "
                    f"{summary['escalation_coverage']['correct']}/"
                    f"{summary['escalation_coverage']['total']}"
                ),
                (
                    "- Low-confidence review coverage: "
                    f"{summary['low_confidence_review_coverage']['correct']}/"
                    f"{summary['low_confidence_review_coverage']['total']}"
                ),
                (
                    "- Failure/tool-retry coverage: "
                    f"{summary['failure_state_coverage']['correct']}/"
                    f"{summary['failure_state_coverage']['total']} failure, "
                    f"{summary['tool_retry_coverage']['correct']}/"
                    f"{summary['tool_retry_coverage']['total']} retry"
                ),
                "",
                "## Scenario Coverage",
                "| Domain | Count |",
                "| --- | ---: |",
                *domain_rows,
                "",
                "## Scenario Results",
                (
                    "| Scenario | Domain | Classification | SLA | Escalation | "
                    "Low Confidence | Failure | Passed |"
                ),
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
                *result_rows,
                "",
                "## Gaps and Warnings",
                *warnings,
                "",
                "## Local Commands",
                *commands,
                "",
            ]
        )
