import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore
from app.models import Approval, OutboxEvent, RunRecord, Ticket
from app.services.analytics import AnalyticsService
from app.services.approvals import ApprovalService
from app.services.briefs import IncidentBriefService
from app.services.customers import CustomerHealthService
from app.services.drills import DrillService
from app.services.ops import OpsService
from app.services.outbox import OutboxService
from app.services.playbooks import PlaybookService
from app.services.tickets import TicketService
from app.services.trace import TraceService
from app.services.workflow import AgentWorkflowService


REQUIRED_SECTIONS = {
    "ticket_summary": "Ticket summary",
    "classification": "Classification",
    "sla_risk": "SLA risk",
    "customer_impact": "Customer impact",
    "knowledge_citations_context": "Knowledge citations/context",
    "drafted_reply": "Drafted reply",
    "engineering_escalation": "Engineering escalation",
    "approval_state": "Approval state",
    "trace_id": "Trace ID",
    "outbox_dispatches": "Outbox dispatches",
    "failure_drill_result": "Failure drill result",
    "remediation_owners": "Remediation owners",
    "slo_budget": "SLO budget",
    "optimization_recommendations": "Optimization recommendations",
    "customer_account_health": "Customer/account health",
}


RUNBOOK_QA_ENDPOINTS = [
    "POST /ops/runbook-qa",
    "POST /ops/operator-readiness-pack",
    "POST /runs/{run_id}/incident-brief",
    "POST /runs/{run_id}/remediation-checklist",
    "POST /analytics/weekly-review",
    "GET /ops/slo-budget",
    "POST /ops/optimization-report",
    "GET /customers/health",
    "POST /customers/{customer_id_or_name}/account-brief",
    "POST /demo/evidence-pack",
]


JD_SKILLS_DEMONSTRATED = [
    "FastAPI service design with authenticated operational endpoints.",
    "LangGraph-compatible workflow orchestration with deterministic fallback behavior.",
    "Human-in-the-loop approval controls before local mock dispatches.",
    "Traceability, SLO budgeting, failure drills, and dashboard-ready metrics.",
    "Artifact export discipline for Markdown and JSON operator handoff packs.",
]


class RunbookQaService:
    def __init__(
        self,
        store: JsonStateStore,
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
        operator_packs_dir: Path,
    ):
        self.store = store
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
        self.operator_packs_dir = operator_packs_dir

    async def evaluate(self, run_id: str | None = None) -> dict[str, Any]:
        run = await self._resolve_run(run_id)
        ticket = await self._ticket_for_run(run)
        artifacts = await self._export_artifacts(run, ticket)
        state = await self.store.load()
        approvals = self._approvals_for_run(state, run.run_id)
        outbox = self._outbox_for_run(state, run.run_id)
        trace_events = await self.trace.list_events(run.run_id)
        failure_drill = self._latest_failure_drill(state)
        sections = self._sections(
            run=run,
            ticket=ticket,
            artifacts=artifacts,
            approvals=approvals,
            outbox=outbox,
            trace_count=len(trace_events),
            failure_drill=failure_drill,
        )
        missing_sections = [
            section_id for section_id, section in sections.items() if not section["present"]
        ]
        score = self._score(sections)
        warnings = self._warnings(
            run=run,
            artifacts=artifacts,
            approvals=approvals,
            outbox=outbox,
            failure_drill=failure_drill,
        )
        status = "pass" if score >= 85 and not missing_sections else "fail"
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run.run_id,
            "ticket_id": ticket.ticket_id,
            "trace_id": run.trace_id,
            "score": score,
            "status": status,
            "pass": status == "pass",
            "missing_sections": missing_sections,
            "warnings": warnings,
            "linked_artifact_paths": self._artifact_paths(artifacts),
            "recommended_fixes": self._recommended_fixes(missing_sections, warnings),
            "sections": sections,
        }
        return result

    async def export_operator_readiness_pack(self, run_id: str | None = None) -> dict[str, Any]:
        qa = await self.evaluate(run_id)
        metrics = await self._critical_metrics(qa["run_id"])
        generated_at = datetime.now(timezone.utc)
        pack_id = f"operator_readiness_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "readiness_status": qa["status"],
            "readiness_score": qa["score"],
            "runbook_qa": qa,
            "critical_metrics": metrics,
            "endpoint_list": RUNBOOK_QA_ENDPOINTS,
            "local_demo_command": r".\.venv\Scripts\python.exe scripts\demo_run.py",
            "jd_skills_demonstrated": JD_SKILLS_DEMONSTRATED,
            "interviewer_talking_points": self._talking_points(qa, metrics),
        }
        markdown = self._pack_markdown(pack)
        json_path, markdown_path = self._write_pack(pack_id, pack, markdown)
        pack["artifact_paths"] = {
            "operator_pack_json": str(json_path),
            "operator_pack_markdown": str(markdown_path),
        }
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "readiness_score": qa["score"],
            "readiness_status": qa["status"],
            "pack": pack,
            "markdown": markdown,
        }

    async def _resolve_run(self, run_id: str | None) -> RunRecord:
        if run_id:
            return await self.workflow.get_run(run_id)
        latest = await self._latest_run()
        if latest:
            return latest
        return await self._run_sample_scenario()

    async def _latest_run(self) -> RunRecord | None:
        state = await self.store.load()
        runs = list(state["runs"].values())
        if not runs:
            return None
        latest = sorted(runs, key=lambda item: item.get("started_at", ""))[-1]
        return RunRecord(**latest)

    async def _run_sample_scenario(self) -> RunRecord:
        tickets = await self.tickets.list()
        ticket = next(
            (
                item
                for item in tickets
                if item.priority == "urgent" or "outage" in item.subject.lower()
            ),
            tickets[0],
        )
        run = await self.workflow.analyze_ticket(ticket.ticket_id)
        run = await self.workflow.approve(
            run.run_id,
            "operator-readiness-bootstrap",
            "Approved deterministic local sample for runbook QA fallback.",
        )
        await self.drills.tool_failure()
        return run

    async def _ticket_for_run(self, run: RunRecord) -> Ticket:
        ticket = await self.tickets.get(run.ticket_id)
        if ticket is None:
            raise KeyError(run.ticket_id)
        return ticket

    async def _export_artifacts(self, run: RunRecord, ticket: Ticket) -> dict[str, Any]:
        artifacts: dict[str, Any] = {}
        artifacts["incident_brief"] = await self.briefs.export(run.run_id)
        artifacts["remediation_checklist"] = await self.playbooks.export_remediation_checklist(
            run.run_id
        )
        artifacts["weekly_review"] = await self.analytics.export_weekly_review()
        artifacts["slo_budget"] = await self.ops.slo_budget()
        artifacts["optimization_report"] = await self.ops.export_optimization_report()
        health = await self.customers.health()
        artifacts["customer_health"] = health
        account_key = ticket.customer or ticket.account or ticket.customer_email.split("@")[0]
        artifacts["account_brief"] = await self.customers.export_account_brief(account_key)
        return artifacts

    def _sections(
        self,
        *,
        run: RunRecord,
        ticket: Ticket,
        artifacts: dict[str, Any],
        approvals: list[Approval],
        outbox: list[OutboxEvent],
        trace_count: int,
        failure_drill: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        state = run.state
        incident = artifacts["incident_brief"]["brief"]
        checklist = artifacts["remediation_checklist"]["checklist"]
        optimization = artifacts["optimization_report"]["report"]
        health = artifacts["customer_health"]["customers"]
        sections = {
            "ticket_summary": self._section(
                bool(ticket.subject and ticket.body),
                f"{ticket.ticket_id}: {ticket.subject}",
            ),
            "classification": self._section(
                bool(state.get("classification", {}).get("category")),
                state.get("classification", {}).get("category", ""),
            ),
            "sla_risk": self._section(
                bool(state.get("sla_risk", {}).get("level")),
                state.get("sla_risk", {}).get("level", ""),
            ),
            "customer_impact": self._section(
                bool(incident.get("customer_impact", {}).get("summary")),
                incident.get("customer_impact", {}).get("subject", ""),
            ),
            "knowledge_citations_context": self._section(
                bool(state.get("kb_results") or incident.get("kb_citations")),
                f"{len(state.get('kb_results', []))} citations",
            ),
            "drafted_reply": self._section(
                bool(state.get("drafts", {}).get("customer_reply")),
                "Customer reply draft present",
            ),
            "engineering_escalation": self._section(
                bool(state.get("drafts", {}).get("engineering_escalation")),
                "Engineering escalation draft present",
            ),
            "approval_state": self._section(
                bool(approvals or state.get("approval_status")),
                state.get("approval_status", "none"),
            ),
            "trace_id": self._section(bool(run.trace_id and trace_count), f"{run.trace_id}"),
            "outbox_dispatches": self._section(
                bool(outbox),
                f"{len(outbox)} dispatches",
            ),
            "failure_drill_result": self._section(
                bool(failure_drill and failure_drill.get("failure_count", 0) > 0),
                f"{failure_drill.get('failure_count', 0) if failure_drill else 0} failed attempts",
            ),
            "remediation_owners": self._section(
                bool(checklist.get("owners")),
                ", ".join(checklist.get("owners", [])),
            ),
            "slo_budget": self._section(
                bool(artifacts["slo_budget"].get("metrics")),
                artifacts["slo_budget"].get("overall_status", ""),
            ),
            "optimization_recommendations": self._section(
                bool(optimization.get("recommended_fixes")),
                f"{len(optimization.get('recommended_fixes', []))} fixes",
            ),
            "customer_account_health": self._section(
                bool(health and artifacts["account_brief"]["brief"].get("customer_health")),
                artifacts["account_brief"]["brief"].get("customer_health", {}).get(
                    "risk_level",
                    "",
                ),
            ),
        }
        return {
            section_id: {"label": REQUIRED_SECTIONS[section_id], **value}
            for section_id, value in sections.items()
        }

    def _section(self, present: bool, evidence: str) -> dict[str, Any]:
        return {"present": present, "evidence": evidence}

    def _score(self, sections: dict[str, dict[str, Any]]) -> int:
        present = sum(1 for section in sections.values() if section["present"])
        return round((present / len(REQUIRED_SECTIONS)) * 100)

    def _warnings(
        self,
        *,
        run: RunRecord,
        artifacts: dict[str, Any],
        approvals: list[Approval],
        outbox: list[OutboxEvent],
        failure_drill: dict[str, Any] | None,
    ) -> list[str]:
        warnings = []
        if run.status == "awaiting_approval":
            warnings.append("Run is still awaiting approval, so operator dispatch evidence is incomplete.")
        if approvals and approvals[-1].status == "pending":
            warnings.append("Latest approval is pending; assign a reviewer before handoff.")
        if not outbox:
            warnings.append("No outbox dispatches are linked to this run.")
        if not failure_drill:
            warnings.append("No tool-failure drill has been recorded in local state.")
        if artifacts["slo_budget"].get("overall_status") == "fail":
            warnings.append("SLO budget is currently failing; review optimization recommendations.")
        return warnings

    def _recommended_fixes(self, missing_sections: list[str], warnings: list[str]) -> list[str]:
        fixes = [self._fix_for_section(section_id) for section_id in missing_sections]
        if any("SLO budget" in warning for warning in warnings):
            fixes.append("Review SLO failures and assign owners for the optimization report fixes.")
        if not fixes:
            fixes.append("Runbook handoff is complete; keep exporting QA before operator review.")
        return list(dict.fromkeys(fixes))

    def _fix_for_section(self, section_id: str) -> str:
        fixes = {
            "ticket_summary": "Attach ticket subject, body, customer, priority, and tier to the handoff.",
            "classification": "Re-run ticket analysis so the classification node records category evidence.",
            "sla_risk": "Re-run SLA scoring and include level, score, and reasons.",
            "customer_impact": "Export the incident brief and include customer impact.",
            "knowledge_citations_context": "Add KB citations or failure-context notes before handoff.",
            "drafted_reply": "Generate a customer reply draft for operator review.",
            "engineering_escalation": "Generate an engineering escalation draft for high-risk handoff.",
            "approval_state": "Create or decide the human approval before dispatch.",
            "trace_id": "Attach trace events for the run.",
            "outbox_dispatches": "Approve the run so local mock Zendesk/Jira/Slack outbox dispatches are recorded.",
            "failure_drill_result": "Run POST /drills/tool-failure and link the drill result.",
            "remediation_owners": "Export a remediation checklist with owner roles.",
            "slo_budget": "Generate the SLO budget snapshot.",
            "optimization_recommendations": "Export the optimization report with recommended fixes.",
            "customer_account_health": "Export customer health and the account brief.",
        }
        return fixes[section_id]

    def _artifact_paths(self, artifacts: dict[str, Any]) -> dict[str, str]:
        paths = {}
        for name, artifact in artifacts.items():
            if isinstance(artifact, dict):
                if artifact.get("markdown_path"):
                    paths[f"{name}_markdown"] = artifact["markdown_path"]
                if artifact.get("json_path"):
                    paths[f"{name}_json"] = artifact["json_path"]
        return paths

    def _approvals_for_run(self, state: dict[str, Any], run_id: str) -> list[Approval]:
        return [
            Approval(**raw)
            for raw in state["approvals"].values()
            if raw.get("run_id") == run_id
        ]

    def _outbox_for_run(self, state: dict[str, Any], run_id: str) -> list[OutboxEvent]:
        return [
            OutboxEvent(**raw)
            for raw in state["outbox"].values()
            if raw.get("run_id") == run_id
        ]

    def _latest_failure_drill(self, state: dict[str, Any]) -> dict[str, Any] | None:
        drills = [
            item for item in state["drills"].values() if item.get("drill_type") == "tool_failure"
        ]
        if not drills:
            return None
        return sorted(drills, key=lambda item: item.get("created_at", ""))[-1]

    async def _critical_metrics(self, run_id: str) -> dict[str, Any]:
        performance = await self.workflow.get_run(run_id)
        ops_snapshot = await self.analytics.ops_snapshot()
        slo = await self.ops.slo_budget()
        agent_metrics = await self.store.load()
        return {
            "run_status": performance.status,
            "final_action": performance.final_action,
            "ops_summary": ops_snapshot["summary_metrics"],
            "ops_averages": ops_snapshot["averages"],
            "slo_overall_status": slo["overall_status"],
            "node_metric_count": len(agent_metrics["metrics"].get("node_metrics", {})),
        }

    def _talking_points(self, qa: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
        return [
            f"Runbook QA scored {qa['score']} with status {qa['status']} for run {qa['run_id']}.",
            "The handoff links incident, remediation, weekly review, account, SLO, and optimization artifacts.",
            (
                "Operators can inspect approval state, trace ID, and local outbox dispatches without "
                "calling real Zendesk, Jira, Slack, or Azure services."
            ),
            (
                f"Critical metrics show {metrics['ops_summary']['run_count']} runs, "
                f"{metrics['ops_summary']['outbox_dispatch_count']} dispatches, and SLO "
                f"status {metrics['slo_overall_status']}."
            ),
            "The failure drill proves degraded-tool behavior is visible before an operator handoff.",
        ]

    def _write_pack(
        self,
        pack_id: str,
        pack: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.operator_packs_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.operator_packs_dir / f"{pack_id}.json"
        markdown_path = self.operator_packs_dir / f"{pack_id}.md"
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _pack_markdown(self, pack: dict[str, Any]) -> str:
        qa = pack["runbook_qa"]
        metrics = pack["critical_metrics"]
        missing = [f"- {section}" for section in qa["missing_sections"]] or ["- None"]
        warnings = [f"- {warning}" for warning in qa["warnings"]] or ["- None"]
        artifacts = [
            f"- {name}: `{path}`" for name, path in sorted(qa["linked_artifact_paths"].items())
        ]
        endpoints = [f"- `{endpoint}`" for endpoint in pack["endpoint_list"]]
        skills = [f"- {skill}" for skill in pack["jd_skills_demonstrated"]]
        talking_points = [f"- {point}" for point in pack["interviewer_talking_points"]]
        fixes = [f"- {fix}" for fix in qa["recommended_fixes"]]
        return "\n".join(
            [
                f"# Operator Readiness Pack: {pack['pack_id']}",
                "",
                "## Readiness Summary",
                f"- Status: {pack['readiness_status']}",
                f"- Score: {pack['readiness_score']}",
                f"- Run: {qa['run_id']}",
                f"- Trace: {qa['trace_id']}",
                f"- Final action: {metrics['final_action']}",
                f"- SLO status: {metrics['slo_overall_status']}",
                "",
                "## Missing Sections",
                *missing,
                "",
                "## Warnings",
                *warnings,
                "",
                "## Recommended Fixes",
                *fixes,
                "",
                "## Linked Artifacts",
                *artifacts,
                "",
                "## Endpoint List",
                *endpoints,
                "",
                "## Local Demo Command",
                f"`{pack['local_demo_command']}`",
                "",
                "## JD Skills Demonstrated",
                *skills,
                "",
                "## Interviewer Talking Points",
                *talking_points,
                "",
            ]
        )
