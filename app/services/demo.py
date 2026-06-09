import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import AuditEvent, ReplayModifiers, TicketCreate
from app.services.analytics import AnalyticsService
from app.services.approvals import ApprovalService
from app.services.audit import AuditService
from app.services.briefs import IncidentBriefService
from app.services.customers import CustomerHealthService
from app.services.drills import DrillService
from app.services.incident_narrative import IncidentNarrativeService
from app.services.ops import OpsService
from app.services.outbox import OutboxService
from app.services.playbooks import PlaybookService
from app.services.replay_lab import ReplayLabService
from app.services.tickets import TicketService
from app.services.trace import TraceService
from app.services.workflow import AgentWorkflowService


DEMO_TICKET = TicketCreate(
    external_id="demo-scenario-enterprise-sso-outage",
    subject="Demo scenario: enterprise SSO outage blocking all agents",
    body=(
        "Northstar Health cannot log in with SAML SSO. Production agents are blocked, "
        "the customer reports an active outage, and SLA breach risk is high."
    ),
    customer="Northstar Health",
    customer_email="ops@northstar.example",
    priority="urgent",
    customer_tier="enterprise",
    tags=["demo", "auth", "sso", "outage", "sla"],
)


SCENARIO_ENDPOINTS = [
    "POST /tickets/ingest",
    "POST /tickets/{ticket_id}/analyze",
    "GET /runs/{run_id}/trace",
    "POST /runs/{run_id}/approve",
    "GET /integrations/outbox",
    "POST /playbooks/recommend",
    "POST /runs/{run_id}/remediation-checklist",
    "POST /drills/tool-failure",
    "POST /drills/sla-breach-simulation",
    "POST /runs/{run_id}/incident-brief",
    "GET /analytics/ops-snapshot",
    "POST /analytics/weekly-review",
    "GET /customers/health",
    "POST /customers/{customer_id_or_name}/account-brief",
    "GET /ops/slo-budget",
    "POST /ops/optimization-report",
    "POST /ops/runbook-qa",
    "POST /ops/operator-readiness-pack",
    "POST /runs/{run_id}/replay-lab",
    "POST /replay-lab/run",
    "POST /replay-lab/report",
    "POST /incidents/timeline",
    "POST /incidents/executive-narrative",
    "GET /handoff/on-call-summary",
    "POST /handoff/customer-comms-pack",
    "GET /metrics/agent-performance",
    "GET /audit/events",
]


class DemoService:
    def __init__(
        self,
        tickets: TicketService,
        workflow: AgentWorkflowService,
        trace: TraceService,
        approvals: ApprovalService,
        outbox: OutboxService,
        playbooks: PlaybookService,
        drills: DrillService,
        briefs: IncidentBriefService,
        analytics: AnalyticsService,
        customers: CustomerHealthService,
        ops: OpsService,
        replay_lab: ReplayLabService,
        incident_narratives: IncidentNarrativeService,
        audit: AuditService,
        demo_packs_dir: Path,
    ):
        self.tickets = tickets
        self.workflow = workflow
        self.trace = trace
        self.approvals = approvals
        self.outbox = outbox
        self.playbooks = playbooks
        self.drills = drills
        self.briefs = briefs
        self.analytics = analytics
        self.customers = customers
        self.ops = ops
        self.replay_lab = replay_lab
        self.incident_narratives = incident_narratives
        self.audit = audit
        self.demo_packs_dir = demo_packs_dir

    async def run_scenario(self) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc)
        scenario_id = f"demo_scenario_{generated_at.strftime('%Y%m%d_%H%M%S')}"

        ticket = await self.tickets.ingest(
            DEMO_TICKET.model_copy(update={"external_id": f"{DEMO_TICKET.external_id}-{scenario_id}"})
        )

        run = await self.workflow.analyze_ticket(ticket.ticket_id)
        approved_run = await self.workflow.approve(
            run.run_id,
            "demo-interviewer",
            "Approved for local interview scenario evidence.",
        )
        trace = await self.trace.list_events(approved_run.run_id)
        outbox = [
            event
            for event in await self.outbox.list_events()
            if event.run_id == approved_run.run_id
        ]
        recommendations = await self.playbooks.recommend(ticket_id=ticket.ticket_id, top_n=3)
        checklist = await self.playbooks.export_remediation_checklist(approved_run.run_id)
        failure_drill = await self.drills.tool_failure()
        sla_simulation = await self.drills.sla_breach_simulation()
        incident_brief = await self.briefs.export(approved_run.run_id)
        ops_snapshot = await self.analytics.ops_snapshot()
        weekly_review = await self.analytics.export_weekly_review()
        customer_health = await self.customers.health()
        account_brief = await self.customers.export_account_brief("northstar-health")
        slo_budget = await self.ops.slo_budget()
        optimization_report = await self.ops.export_optimization_report()
        replay_report = await self.replay_lab.export_report(
            approved_run.run_id,
            modifiers=ReplayModifiers(
                sla_pressure="critical",
                kb_context="missing",
                adapter_health="degraded",
                confidence_override=0.48,
                approval_policy="strict",
            ),
        )
        executive_narrative = await self.incident_narratives.export_executive_narrative(
            approved_run.run_id
        )

        await self.audit.record(
            AuditEvent(
                actor="demo",
                action="demo.scenario_run",
                resource_type="run",
                resource_id=approved_run.run_id,
                trace_id=approved_run.trace_id,
                metadata={"scenario_id": scenario_id},
            )
        )

        artifact_paths = {
            "remediation_checklist_markdown": checklist["markdown_path"],
            "remediation_checklist_json": checklist["json_path"],
            "incident_brief_markdown": incident_brief["markdown_path"],
            "incident_brief_json": incident_brief["json_path"],
            "weekly_review_markdown": weekly_review["markdown_path"],
            "weekly_review_json": weekly_review["json_path"],
            "account_brief_markdown": account_brief["markdown_path"],
            "account_brief_json": account_brief["json_path"],
            "optimization_report_markdown": optimization_report["markdown_path"],
            "optimization_report_json": optimization_report["json_path"],
            "replay_report_markdown": replay_report["markdown_path"],
            "replay_report_json": replay_report["json_path"],
            "incident_narrative_markdown": executive_narrative["markdown_path"],
            "incident_narrative_json": executive_narrative["json_path"],
        }
        summary_metrics = {
            "ticket_id": ticket.ticket_id,
            "run_id": approved_run.run_id,
            "trace_id": approved_run.trace_id,
            "run_status": approved_run.status,
            "final_action": approved_run.final_action,
            "classification": approved_run.state.get("classification", {}).get("category"),
            "sla_risk_level": approved_run.state.get("sla_risk", {}).get("level"),
            "approval_id": approved_run.state.get("approval_id"),
            "approval_status": approved_run.state.get("approval_status"),
            "trace_event_count": len(trace),
            "outbox_dispatch_count": len(outbox),
            "playbook_count": len(recommendations["recommendations"]),
            "failure_drill_failed_attempts": len(failure_drill["failure_timeline"]),
            "sla_simulation_ticket_count": len(sla_simulation["queue"]),
            "weekly_review_run_count": weekly_review["review"]["summary_metrics"]["run_count"],
            "customer_health_accounts": len(customer_health["customers"]),
            "slo_overall_status": slo_budget["overall_status"],
            "optimization_recommended_fix_count": len(
                optimization_report["report"]["recommended_fixes"]
            ),
            "replay_risk_score": replay_report["report"]["comparison"]["comparison"]["risk_score"],
            "replay_recommended_action": replay_report["report"]["comparison"]["comparison"][
                "recommended_operator_action"
            ],
            "incident_impact_status": executive_narrative["impact_status"],
            "incident_narrative_path": executive_narrative["markdown_path"],
        }
        key_metrics = {
            "ops_summary": ops_snapshot["summary_metrics"],
            "ops_averages": ops_snapshot["averages"],
            "slo": slo_budget,
            "top_customer": customer_health["customers"][0] if customer_health["customers"] else None,
        }

        return {
            "scenario_id": scenario_id,
            "generated_at": generated_at.isoformat(),
            "mode": "local-deterministic",
            "ticket": ticket.model_dump(mode="json"),
            "run": approved_run.model_dump(mode="json"),
            "artifact_paths": artifact_paths,
            "endpoints_exercised": SCENARIO_ENDPOINTS,
            "summary_metrics": summary_metrics,
            "key_metrics": key_metrics,
            "links": {
                "run": f"/runs/{approved_run.run_id}",
                "trace": f"/runs/{approved_run.run_id}/trace",
                "approval_queue": "/approvals",
                "outbox": "/integrations/outbox",
                "ops_snapshot": "/analytics/ops-snapshot",
                "customer_health": "/customers/health",
                "slo_budget": "/ops/slo-budget",
            },
            "evidence": {
                "recommendations": recommendations["recommendations"],
                "outbox": [event.model_dump(mode="json") for event in outbox],
                "failure_drill": failure_drill["drill"],
                "sla_simulation_queue": sla_simulation["queue"],
                "replay_lab": replay_report["report"]["comparison"],
                "incident_narrative": {
                    "narrative_id": executive_narrative["narrative_id"],
                    "impact_status": executive_narrative["impact_status"],
                    "markdown_path": executive_narrative["markdown_path"],
                },
            },
        }

    async def export_evidence_pack(self) -> dict[str, Any]:
        scenario = await self.run_scenario()
        generated_at = datetime.now(timezone.utc)
        pack_id = f"evidence_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        talking_points = self._talking_points(scenario)
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "scenario_id": scenario["scenario_id"],
            "summary": self._summary(scenario),
            "artifact_paths": scenario["artifact_paths"],
            "api_endpoints_exercised": scenario["endpoints_exercised"],
            "key_metrics": scenario["key_metrics"],
            "summary_metrics": scenario["summary_metrics"],
            "interview_talking_points": talking_points,
            "links": scenario["links"],
        }
        markdown = self._markdown(pack)
        json_path, markdown_path = self._write_pack(pack_id, pack, markdown)
        pack["artifact_paths"] = {
            **pack["artifact_paths"],
            "evidence_pack_markdown": str(markdown_path),
            "evidence_pack_json": str(json_path),
        }
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        await self.audit.record(
            AuditEvent(
                actor="demo",
                action="demo.evidence_pack_exported",
                resource_type="demo_pack",
                resource_id=pack_id,
                trace_id=scenario["summary_metrics"]["trace_id"],
                metadata={
                    "scenario_id": scenario["scenario_id"],
                    "markdown_path": str(markdown_path),
                    "json_path": str(json_path),
                },
            )
        )
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "pack": pack,
            "markdown": markdown,
            "scenario": scenario,
        }

    def _summary(self, scenario: dict[str, Any]) -> str:
        metrics = scenario["summary_metrics"]
        return (
            "Ran the complete local support escalation scenario from ticket analysis through "
            f"approval, outbox dispatch, drills, reports, account health, and SLO review. "
            f"The primary run `{metrics['run_id']}` finished as `{metrics['run_status']}` "
            f"with `{metrics['final_action']}`."
        )

    def _talking_points(self, scenario: dict[str, Any]) -> list[str]:
        metrics = scenario["summary_metrics"]
        return [
            "Shows an end-to-end agent workflow with human approval before external actions.",
            (
                f"Connects trace evidence ({metrics['trace_event_count']} events) to the "
                f"approved run and {metrics['outbox_dispatch_count']} local outbox dispatches."
            ),
            "Demonstrates production readiness with a forced tool-failure drill and SLA queue simulation.",
            "Exports manager-ready Markdown and JSON artifacts for incident, weekly review, checklist, account brief, and optimization review.",
            (
            f"Uses Replay Lab to compare changed conditions with risk score "
            f"{metrics['replay_risk_score']} before approving automation changes."
        ),
        (
            f"Adds an executive incident narrative with customer impact status "
            f"`{metrics['incident_impact_status']}`."
        ),
        f"Frames operational maturity with SLO status `{metrics['slo_overall_status']}` and concrete optimization recommendations.",
    ]

    def _write_pack(
        self,
        pack_id: str,
        pack: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.demo_packs_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.demo_packs_dir / f"{pack_id}.json"
        markdown_path = self.demo_packs_dir / f"{pack_id}.md"
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _markdown(self, pack: dict[str, Any]) -> str:
        metrics = pack["summary_metrics"]
        artifact_rows = [
            f"- {name}: `{path}`" for name, path in sorted(pack["artifact_paths"].items())
        ]
        endpoint_rows = [f"- `{endpoint}`" for endpoint in pack["api_endpoints_exercised"]]
        talking_points = [f"- {point}" for point in pack["interview_talking_points"]]
        ops = pack["key_metrics"]["ops_summary"]
        return "\n".join(
            [
                f"# Demo Evidence Pack: {pack['pack_id']}",
                "",
                "## Summary",
                pack["summary"],
                "",
                "## Primary Scenario",
                f"- Ticket: {metrics['ticket_id']}",
                f"- Run: {metrics['run_id']}",
                f"- Trace: {metrics['trace_id']}",
                f"- Classification: {metrics['classification']}",
                f"- SLA risk: {metrics['sla_risk_level']}",
                f"- Approval: {metrics['approval_id']} ({metrics['approval_status']})",
                f"- Final action: {metrics['final_action']}",
                f"- Outbox dispatches: {metrics['outbox_dispatch_count']}",
                "",
                "## Generated Artifacts",
                *artifact_rows,
                "",
                "## API Endpoints Exercised",
                *endpoint_rows,
                "",
                "## Key Metrics",
                f"- Tickets: {ops['ticket_count']}",
                f"- Runs: {ops['run_count']}",
                f"- Pending approvals: {ops['pending_approval_count']}",
                f"- Failures: {ops['failure_count']}",
                f"- SLO status: {metrics['slo_overall_status']}",
                f"- Optimization fixes: {metrics['optimization_recommended_fix_count']}",
                f"- Replay risk score: {metrics['replay_risk_score']}",
                f"- Replay recommendation: {metrics['replay_recommended_action']}",
                f"- Incident impact status: {metrics['incident_impact_status']}",
                "",
                "## Interview Talking Points",
                *talking_points,
                "",
            ]
        )
