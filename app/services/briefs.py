import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore
from app.models import Approval, OutboxEvent
from app.services.tickets import TicketService
from app.services.trace import TraceService
from app.services.workflow import AgentWorkflowService


class IncidentBriefService:
    def __init__(
        self,
        store: JsonStateStore,
        ticket_service: TicketService,
        workflow_service: AgentWorkflowService,
        trace_service: TraceService,
        briefs_dir: Path,
    ):
        self.store = store
        self.ticket_service = ticket_service
        self.workflow_service = workflow_service
        self.trace_service = trace_service
        self.briefs_dir = briefs_dir

    async def export(self, run_id: str) -> dict[str, Any]:
        run = await self.workflow_service.get_run(run_id)
        ticket = await self.ticket_service.get(run.ticket_id)
        if ticket is None:
            raise KeyError(run.ticket_id)

        state = run.state
        trace = await self.trace_service.list_events(run_id)
        raw_state = await self.store.load()
        approvals = [
            Approval(**raw)
            for raw in raw_state["approvals"].values()
            if raw.get("run_id") == run_id
        ]
        outbox = [
            OutboxEvent(**raw)
            for raw in raw_state["outbox"].values()
            if raw.get("run_id") == run_id
        ]
        approval = approvals[-1] if approvals else None
        errors = [event for event in trace if event.status == "error"]
        nodes = list(dict.fromkeys(event.node for event in trace if event.node))
        kb_citations = [
            {
                "article_id": item.get("article_id"),
                "title": item.get("title"),
                "score": item.get("score", 0.0),
            }
            for item in state.get("kb_results", [])
        ]

        brief_json = {
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "ticket_id": ticket.ticket_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "customer_impact": {
                "customer_tier": ticket.customer_tier,
                "priority": ticket.priority,
                "subject": ticket.subject,
                "summary": ticket.body,
            },
            "classification": state.get("classification", {}),
            "sla_risk": state.get("sla_risk", {}),
            "kb_citations": kb_citations,
            "customer_reply_draft": state.get("drafts", {}).get("customer_reply", ""),
            "engineering_escalation_draft": state.get("drafts", {}).get(
                "engineering_escalation",
                "",
            ),
            "approval_status": {
                "approval_id": approval.approval_id if approval else state.get("approval_id"),
                "status": approval.status if approval else state.get("approval_status", "none"),
                "decided_by": approval.decided_by if approval else None,
                "decision_note": approval.decision_note if approval else None,
            },
            "trace_summary": {
                "event_count": len(trace),
                "nodes": nodes,
                "error_count": len(errors),
                "errors": [
                    {
                        "node": event.node,
                        "event_type": event.event_type,
                        "message": event.message,
                    }
                    for event in errors
                ],
            },
            "outbox_status": {
                "status": self._outbox_status(state, outbox),
                "dispatch_count": len(outbox),
                "events": [
                    {
                        "outbox_id": event.outbox_id,
                        "action_type": event.action_type,
                        "destination": event.destination,
                        "status": event.status,
                    }
                    for event in outbox
                ],
            },
            "recommended_next_steps": self._next_steps(state, approval, outbox),
        }
        markdown = self._markdown(brief_json)
        json_path, markdown_path = self._write_files(run_id, brief_json, markdown)
        return {
            "run_id": run_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "brief": brief_json,
            "markdown": markdown,
        }

    def _write_files(
        self,
        run_id: str,
        brief_json: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.briefs_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.briefs_dir / f"{run_id}.json"
        markdown_path = self.briefs_dir / f"{run_id}.md"
        json_path.write_text(json.dumps(brief_json, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _outbox_status(self, state: dict[str, Any], outbox: list[OutboxEvent]) -> str:
        if outbox:
            return "dispatched"
        if state.get("approval_status") == "pending":
            return "pending_approval_no_dispatch"
        if state.get("approval_status") == "rejected":
            return "rejected_no_dispatch"
        return "no_dispatch_records"

    def _next_steps(
        self,
        state: dict[str, Any],
        approval: Approval | None,
        outbox: list[OutboxEvent],
    ) -> list[str]:
        steps = []
        sla_risk = state.get("sla_risk", {})
        if approval and approval.status == "pending":
            steps.append(f"Review and decide pending approval {approval.approval_id}.")
        if sla_risk.get("level") == "high":
            steps.append("Keep engineering escalation active until mitigation is confirmed.")
        if state.get("failure_state"):
            steps.append("Assign a human owner to validate customer guidance after KB retry failure.")
        if outbox:
            steps.append("Monitor dispatched Zendesk/Jira/Slack handoffs for owner response.")
        if not steps:
            steps.append("Continue standard support follow-up and monitor SLA timer.")
        return steps

    def _markdown(self, brief: dict[str, Any]) -> str:
        impact = brief["customer_impact"]
        classification = brief["classification"]
        sla_risk = brief["sla_risk"]
        approval = brief["approval_status"]
        trace = brief["trace_summary"]
        outbox = brief["outbox_status"]
        citations = brief["kb_citations"]
        citation_lines = [
            f"- {item['article_id']}: {item['title']} (score {item['score']})"
            for item in citations
        ] or ["- No KB citations found."]
        outbox_lines = [
            f"- {item['action_type']} -> {item['destination']} [{item['status']}]"
            for item in outbox["events"]
        ] or [f"- {outbox['status']}"]
        next_steps = [f"- {step}" for step in brief["recommended_next_steps"]]

        return "\n".join(
            [
                f"# Incident Brief: {brief['run_id']}",
                "",
                "## Customer Impact",
                f"- Ticket: {brief['ticket_id']}",
                f"- Tier: {impact['customer_tier']}",
                f"- Priority: {impact['priority']}",
                f"- Subject: {impact['subject']}",
                f"- Summary: {impact['summary']}",
                "",
                "## Classification",
                f"- Category: {classification.get('category', 'unknown')}",
                f"- Confidence: {classification.get('confidence', 'unknown')}",
                f"- Rationale: {classification.get('rationale', 'unknown')}",
                "",
                "## SLA Risk",
                f"- Level: {sla_risk.get('level', 'unknown')}",
                f"- Score: {sla_risk.get('score', 'unknown')}",
                f"- Reasons: {', '.join(sla_risk.get('reasons', [])) or 'none'}",
                "",
                "## KB Citations",
                *citation_lines,
                "",
                "## Customer Reply Draft",
                brief["customer_reply_draft"] or "No customer reply draft.",
                "",
                "## Engineering Escalation Draft",
                brief["engineering_escalation_draft"] or "No engineering escalation draft.",
                "",
                "## Approval Status",
                f"- Approval: {approval.get('approval_id')}",
                f"- Status: {approval.get('status')}",
                "",
                "## Trace Summary",
                f"- Trace: {brief['trace_id']}",
                f"- Events: {trace['event_count']}",
                f"- Nodes: {', '.join(trace['nodes'])}",
                f"- Errors: {trace['error_count']}",
                "",
                "## Outbox Status",
                *outbox_lines,
                "",
                "## Recommended Next Steps",
                *next_steps,
                "",
            ]
        )
