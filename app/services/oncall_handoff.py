import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.storage import JsonStateStore
from app.models import Approval, AuditEvent, RunRecord, Ticket, TicketCreate, TraceEvent
from app.services.approvals import ApprovalService
from app.services.audit import AuditService
from app.services.policy_guardrails import PolicyGuardrailService
from app.services.tickets import TicketService
from app.services.trace import TraceService
from app.services.workflow import AgentWorkflowService


HANDOFF_VERIFY_COMMANDS = [
    r".\.venv\Scripts\python.exe -m pytest -q",
    r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
    r".\.venv\Scripts\python.exe -m app.evals.run_eval",
    r".\.venv\Scripts\python.exe scripts\dashboard_smoke.py",
    r".\.venv\Scripts\python.exe scripts\demo_run.py",
    (
        r'rg "handoff/on-call-summary|handoff/customer-comms-pack|On-Call Handoff|'
        r'Customer Communications|customer_comms_packs|communication readiness" '
        r"app dashboard docs README.md tests scripts sample_data"
    ),
    (
        r"Get-ChildItem -Recurse -File data\customer_comms_packs "
        r"-ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime"
    ),
]

REQUIRED_SCENARIO_DOMAINS = {
    "high_sla_risk": {"outage"},
    "low_confidence_approval_pause": {"low_confidence_ambiguity"},
    "tool_failure_retry": {"webhook_api"},
    "billing_privacy": {"billing", "data_export_privacy", "security"},
    "outage_api_incident": {"outage", "webhook_api"},
}


class OnCallHandoffService:
    """Builds deterministic on-call and customer communications proof artifacts."""

    def __init__(
        self,
        store: JsonStateStore,
        tickets: TicketService,
        workflow: AgentWorkflowService,
        trace: TraceService,
        approvals: ApprovalService,
        policy_guardrails: PolicyGuardrailService,
        audit: AuditService,
        scenario_fixture: Path,
        customer_comms_dir: Path,
    ):
        self.store = store
        self.tickets = tickets
        self.workflow = workflow
        self.trace = trace
        self.approvals = approvals
        self.policy_guardrails = policy_guardrails
        self.audit = audit
        self.scenario_fixture = scenario_fixture
        self.customer_comms_dir = customer_comms_dir

    async def on_call_summary(self) -> dict[str, Any]:
        run, ticket, source = await self._resolve_run()
        context = await self._run_context(run, ticket)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "title": "On-Call Handoff Summary",
            "mode": "local-deterministic-on-call-handoff",
            "source": source,
            "run_id": run.run_id,
            "ticket_id": ticket.ticket_id,
            "trace_id": run.trace_id,
            "customer": self._customer_name(ticket),
            "subject": ticket.subject,
            "severity": self._severity(run, ticket),
            "status": self._operational_status(run, context),
            "owners": self._owners(run, context),
            "sla_deadline": self._sla_deadline(ticket, run).isoformat(),
            "sla": self._sla_status(ticket, run),
            "trace_links": self._trace_links(run, context),
            "customer_communication_readiness": self._communication_readiness(run, context),
            "approval_and_guardrail_status": self._approval_and_guardrail_status(run, context),
            "risk_gap_checklist": self._risk_gap_checklist(run, ticket, context),
            "latest_drafts": self._customer_updates(ticket, run, context),
            "engineering_incident_ticket_summary": self._engineering_ticket(ticket, run, context),
            "local_proof_commands": HANDOFF_VERIFY_COMMANDS,
        }

    async def export_customer_comms_pack(self) -> dict[str, Any]:
        summary = await self.on_call_summary()
        scenario_coverage = await self._scenario_coverage_pack()
        timeline = await self._timeline(summary["run_id"])
        generated_at = datetime.now(timezone.utc)
        pack_id = f"customer_comms_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        json_path = self.customer_comms_dir / f"{pack_id}.json"
        markdown_path = self.customer_comms_dir / f"{pack_id}.md"
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "title": "On-Call Handoff + Customer Communications Simulation Pack",
            "on_call_handoff_summary": summary,
            "customer_updates": summary["latest_drafts"],
            "internal_handoff": self._internal_handoff(summary),
            "engineering_ticket_draft": summary["engineering_incident_ticket_summary"],
            "sla_customer_impact_timeline": timeline,
            "approval_checklist": self._approval_checklist(summary),
            "approval_and_guardrail_status": summary["approval_and_guardrail_status"],
            "risk_gap_checklist": summary["risk_gap_checklist"],
            "scenario_coverage": scenario_coverage,
            "trace_ids": self._trace_ids(summary, scenario_coverage),
            "local_proof_commands": HANDOFF_VERIFY_COMMANDS,
            "artifact_paths": {
                "customer_comms_pack_markdown": str(markdown_path),
                "customer_comms_pack_json": str(json_path),
            },
            "limitations": [
                "Customer updates are drafts only; the pack never dispatches customer-visible messages.",
                "Scenario coverage uses local deterministic fake tickets and mock adapters.",
                "No Azure, OpenAI, Zendesk, Jira, Slack, GitHub, or external SaaS calls are made.",
            ],
        }
        markdown = self._markdown(pack)
        self.customer_comms_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        await self.audit.record(
            AuditEvent(
                actor="on-call-handoff",
                action="handoff.customer_comms_pack_exported",
                resource_type="customer_comms_pack",
                resource_id=pack_id,
                trace_id=summary["trace_id"],
                metadata={"markdown_path": str(markdown_path), "json_path": str(json_path)},
            )
        )
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "status": summary["customer_communication_readiness"]["status"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "scenario_count": scenario_coverage["scenario_count"],
            "coverage_status": scenario_coverage["coverage_status"],
            "pack": pack,
            "markdown": markdown,
        }

    async def _resolve_run(self) -> tuple[RunRecord, Ticket, str]:
        state = await self.store.load()
        if state["runs"]:
            run = RunRecord(**sorted(state["runs"].values(), key=lambda item: item["started_at"])[-1])
            ticket = await self._ticket_for_run(run)
            return run, ticket, "latest_run"
        scenario = self._selected_scenarios()[0]
        ticket = await self._ingest_or_get_scenario_ticket(scenario)
        run = await self.workflow.analyze_ticket(ticket.ticket_id)
        return run, ticket, "scenario_bootstrap"

    async def _run_context(self, run: RunRecord, ticket: Ticket) -> dict[str, Any]:
        state = await self.store.load()
        trace = await self.trace.list_events(run.run_id)
        approvals = [
            Approval(**raw)
            for raw in state["approvals"].values()
            if raw.get("run_id") == run.run_id
        ]
        outbox = [
            raw
            for raw in state["outbox"].values()
            if raw.get("run_id") == run.run_id
        ]
        policy = await self.policy_guardrails.simulate(self._policy_request_for_run(run.run_id))
        return {
            "trace": trace,
            "approvals": approvals,
            "outbox": outbox,
            "policy": policy,
            "ticket": ticket,
        }

    def _policy_request_for_run(self, run_id: str):
        from app.models import PolicySimulationRequest

        return PolicySimulationRequest(run_id=run_id)

    async def _scenario_coverage_pack(self) -> dict[str, Any]:
        scenarios = self._selected_scenarios()
        rows = []
        for scenario in scenarios:
            ticket = await self._ingest_or_get_scenario_ticket(scenario)
            run = await self.workflow.analyze_ticket(ticket.ticket_id)
            context = await self._run_context(run, ticket)
            readiness = self._communication_readiness(run, context)
            rows.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "title": scenario["title"],
                    "domain": scenario["domain"],
                    "run_id": run.run_id,
                    "ticket_id": ticket.ticket_id,
                    "trace_id": run.trace_id,
                    "severity": self._severity(run, ticket),
                    "sla_level": run.state.get("sla_risk", {}).get("level"),
                    "approval_pause": str(run.status) == "awaiting_approval",
                    "low_confidence": self._is_low_confidence(run),
                    "tool_retry": self._tool_error_count(run) > 0,
                    "failure_state": bool(run.failure_state),
                    "communication_readiness": readiness["status"],
                    "guardrail_decision": context["policy"]["policy_decision"],
                }
            )
        coverage = self._coverage_summary(rows)
        return {
            "coverage_status": "pass" if all(coverage["required_paths"].values()) else "gap",
            "scenario_count": len(rows),
            "required_path_coverage": coverage,
            "scenarios": rows,
        }

    def _selected_scenarios(self) -> list[dict[str, Any]]:
        scenarios = json.loads(self.scenario_fixture.read_text(encoding="utf-8"))
        preferred = [
            "scn_enterprise_login_outage",
            "scn_low_confidence_ambiguity",
            "scn_webhook_kb_failure",
            "scn_billing_duplicate_invoice",
            "scn_privacy_data_export",
            "scn_webhook_api_regression",
        ]
        by_id = {item["scenario_id"]: item for item in scenarios}
        return [by_id[item] for item in preferred if item in by_id]

    async def _ingest_or_get_scenario_ticket(self, scenario: dict[str, Any]) -> Ticket:
        payload = TicketCreate(**scenario["ticket"])
        if payload.external_id:
            existing = await self.tickets.get_by_external_id(payload.external_id)
            if existing:
                return existing
        return await self.tickets.ingest(payload)

    async def _ticket_for_run(self, run: RunRecord) -> Ticket:
        ticket = await self.tickets.get(run.ticket_id)
        if ticket is None:
            raise KeyError(run.ticket_id)
        return ticket

    def _customer_name(self, ticket: Ticket) -> str:
        return ticket.customer or ticket.account or ticket.customer_email

    def _severity(self, run: RunRecord, ticket: Ticket) -> str:
        sla = run.state.get("sla_risk", {})
        if run.failure_state or sla.get("score", 0) >= 0.85:
            return "sev1"
        if ticket.priority == "urgent" or sla.get("level") == "high":
            return "sev2"
        if ticket.priority == "high" or sla.get("level") == "medium":
            return "sev3"
        return "sev4"

    def _operational_status(self, run: RunRecord, context: dict[str, Any]) -> str:
        if run.failure_state:
            return "paused_tool_failure"
        if any(approval.status == "pending" for approval in context["approvals"]):
            return "pending_approval"
        if context["outbox"]:
            return "approved_dispatch_recorded"
        return str(run.status)

    def _owners(self, run: RunRecord, context: dict[str, Any]) -> dict[str, str]:
        policy = context["policy"]
        escalation_owner = "Engineering Manager" if self._requires_engineering(run) else "Support Lead"
        return {
            "incident_commander": "Support Lead"
            if policy["required_approval_type"] != "incident_commander"
            else "Incident Commander",
            "support_owner": "Support Agent",
            "customer_comms_owner": "Support Lead",
            "engineering_owner": escalation_owner,
            "approval_owner": policy["required_approval_type"],
            "knowledge_owner": "Knowledge Owner"
            if "knowledge_owner" in policy.get("approval_chain", [])
            else "Support Ops",
        }

    def _sla_deadline(self, ticket: Ticket, run: RunRecord) -> datetime:
        if ticket.sla_due_at:
            return ticket.sla_due_at if ticket.sla_due_at.tzinfo else ticket.sla_due_at.replace(tzinfo=timezone.utc)
        created = ticket.created_at if ticket.created_at.tzinfo else ticket.created_at.replace(tzinfo=timezone.utc)
        severity = self._severity(run, ticket)
        hours = {"sev1": 1, "sev2": 4, "sev3": 12, "sev4": 48}[severity]
        return created + timedelta(hours=hours)

    def _sla_status(self, ticket: Ticket, run: RunRecord) -> dict[str, Any]:
        deadline = self._sla_deadline(ticket, run)
        minutes = round((deadline - datetime.now(timezone.utc)).total_seconds() / 60)
        return {
            "deadline": deadline.isoformat(),
            "minutes_remaining": minutes,
            "risk_level": "breached" if minutes < 0 else "critical" if minutes <= 30 else run.state.get("sla_risk", {}).get("level", "low"),
            "score": run.state.get("sla_risk", {}).get("score", 0),
            "reasons": run.state.get("sla_risk", {}).get("reasons", []),
        }

    def _trace_links(self, run: RunRecord, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "run": f"/runs/{run.run_id}",
            "trace": f"/runs/{run.run_id}/trace",
            "approval_queue": "/approvals",
            "event_count": len(context["trace"]),
            "trace_event_ids": [event.event_id for event in context["trace"][:8]],
        }

    def _communication_readiness(self, run: RunRecord, context: dict[str, Any]) -> dict[str, Any]:
        qa = run.state.get("qa", {})
        status = "draft_ready_for_approval"
        blockers = []
        if any(approval.status == "pending" for approval in context["approvals"]):
            status = "pending_approval"
            blockers.append("Human approval is pending before customer-visible dispatch.")
        if qa.get("confidence", 1.0) < self.workflow.low_confidence_threshold:
            status = "blocked_guardrail_review"
            blockers.append("Low confidence requires review before customer update.")
        if run.failure_state:
            status = "blocked_tool_failure_review"
            blockers.append("Tool retry failure requires grounding review before update.")
        if context["policy"]["policy_decision"] == "blocked_pending_remediation":
            status = "blocked_guardrail_review"
            blockers.append(context["policy"]["recommended_operator_action"])
        if context["outbox"]:
            status = "dispatch_recorded"
        return {
            "status": status,
            "communication readiness": status,
            "ready_for_customer_send": status == "dispatch_recorded",
            "ready_for_approval_review": bool(run.state.get("drafts", {}).get("customer_reply")),
            "blockers": list(dict.fromkeys(blockers)),
            "next_action": self._next_comms_action(status),
        }

    def _approval_and_guardrail_status(self, run: RunRecord, context: dict[str, Any]) -> dict[str, Any]:
        policy = context["policy"]
        return {
            "run_status": str(run.status),
            "approval_status": run.state.get("approval_status"),
            "approval_id": run.state.get("approval_id"),
            "pending_approval_count": sum(1 for item in context["approvals"] if item.status == "pending"),
            "policy_decision": policy["policy_decision"],
            "required_approval_type": policy["required_approval_type"],
            "approval_chain": policy["approval_chain"],
            "blocked_actions": policy["blocked_actions"],
            "allowed_actions": policy["allowed_actions"],
            "matched_rule_ids": [rule["rule_id"] for rule in policy["matched_rules"]],
            "warnings": policy["warnings"],
        }

    def _risk_gap_checklist(
        self,
        run: RunRecord,
        ticket: Ticket,
        context: dict[str, Any],
    ) -> list[dict[str, str]]:
        drafts = run.state.get("drafts", {})
        risks = []
        if not drafts.get("customer_reply"):
            risks.append(self._risk("missing_customer_update", "Support Lead", "Draft customer update."))
        if self._requires_engineering(run) and not drafts.get("engineering_escalation"):
            risks.append(self._risk("missing_engineering_ticket", "Engineering Manager", "Create ticket draft."))
        if any(approval.status == "pending" for approval in context["approvals"]):
            risks.append(self._risk("approval_pause", "Support Lead", "Approve, reject, or rewrite."))
        if self._is_low_confidence(run):
            risks.append(self._risk("low_confidence", "Support Lead", "Validate grounding and wording."))
        if run.failure_state:
            risks.append(self._risk("tool_failure_retry", "Knowledge Owner", "Resolve failed retrieval."))
        if self._sla_status(ticket, run)["risk_level"] in {"critical", "breached", "high"}:
            risks.append(self._risk("sla_pressure", "Incident Commander", "Publish owner ETA."))
        if not context["trace"]:
            risks.append(self._risk("missing_trace", "Support Ops", "Regenerate run trace."))
        if not risks:
            risks.append(self._risk("standard_monitoring", "Support Lead", "Monitor customer confirmation."))
        return risks

    def _risk(self, risk: str, owner: str, next_step: str) -> dict[str, str]:
        return {"risk": risk, "owner": owner, "next_step": next_step}

    def _customer_updates(
        self,
        ticket: Ticket,
        run: RunRecord,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        draft = run.state.get("drafts", {}).get("customer_reply") or self._fallback_customer_draft(ticket, run)
        readiness = self._communication_readiness(run, context)
        customer = self._customer_name(ticket)
        return [
            {
                "type": "initial_update",
                "audience": "customer",
                "status": readiness["status"],
                "subject": f"Update on {ticket.subject}",
                "body": draft,
                "requires_approval": readiness["status"] != "dispatch_recorded",
            },
            {
                "type": "sla_holding_update",
                "audience": "customer",
                "status": "draft",
                "subject": f"SLA-aware update for {customer}",
                "body": (
                    f"We are actively tracking `{ticket.subject}` against the SLA deadline. "
                    "The current owner is reviewing impact, workaround options, and the next ETA."
                ),
                "requires_approval": True,
            },
            {
                "type": "follow_up_after_engineering_ack",
                "audience": "customer",
                "status": "draft",
                "subject": f"Follow-up on {ticket.subject}",
                "body": (
                    "Engineering has been asked to confirm scope, mitigation, and customer-safe ETA. "
                    "We will send the next update after the approval gate is cleared."
                ),
                "requires_approval": True,
            },
        ]

    def _fallback_customer_draft(self, ticket: Ticket, run: RunRecord) -> str:
        sla = run.state.get("sla_risk", {})
        return (
            f"Hi {self._customer_name(ticket)}, we are reviewing `{ticket.subject}` with "
            f"{sla.get('level', 'unknown')} SLA risk. We have paused external dispatch until "
            "the support lead approves the grounded customer update."
        )

    def _engineering_ticket(self, ticket: Ticket, run: RunRecord, context: dict[str, Any]) -> dict[str, Any]:
        classification = run.state.get("classification", {})
        body = run.state.get("drafts", {}).get("engineering_escalation") or (
            f"Investigate customer impact for `{ticket.subject}`. "
            f"Classification: {classification.get('category', 'unknown')}. "
            f"SLA: {run.state.get('sla_risk', {}).get('level', 'unknown')}."
        )
        return {
            "title": f"{self._severity(run, ticket).upper()} support escalation: {ticket.subject}",
            "status": "draft_pending_approval" if not context["outbox"] else "dispatch_recorded",
            "owner": self._owners(run, context)["engineering_owner"],
            "customer": self._customer_name(ticket),
            "severity": self._severity(run, ticket),
            "labels": ["support-escalation", classification.get("category", "unknown"), ticket.customer_tier],
            "summary": body,
            "trace_id": run.trace_id,
            "run_id": run.run_id,
            "ticket_id": ticket.ticket_id,
            "requested_engineering_outputs": [
                "Confirm blast radius and customer-visible symptoms.",
                "Publish mitigation owner and ETA.",
                "Attach logs, request IDs, or rollback status when available.",
            ],
        }

    async def _timeline(self, run_id: str) -> list[dict[str, Any]]:
        run = await self.workflow.get_run(run_id)
        ticket = await self._ticket_for_run(run)
        context = await self._run_context(run, ticket)
        rows = [
            self._timeline_row(ticket.created_at, "ticket_intake", "customer", ticket.subject),
            self._timeline_row(run.started_at, "agent_run_started", "agent", f"Run {run.run_id} started."),
        ]
        for event in context["trace"]:
            if event.event_type in {"node_end", "tool_call"}:
                rows.append(self._timeline_row(event.timestamp, event.event_type, "agent", event.message, event))
        for approval in context["approvals"]:
            rows.append(
                self._timeline_row(
                    approval.created_at,
                    "approval_requested",
                    "support_lead",
                    approval.reason,
                )
            )
            if approval.decided_at:
                rows.append(
                    self._timeline_row(
                        approval.decided_at,
                        "approval_decided",
                        approval.decided_by or "support_lead",
                        approval.status,
                    )
                )
        rows.append(
            self._timeline_row(
                self._sla_deadline(ticket, run),
                "sla_deadline",
                "support_ops",
                f"SLA deadline for {self._customer_name(ticket)}.",
            )
        )
        rows.sort(key=lambda item: item["_sort_time"])
        for index, row in enumerate(rows, start=1):
            row["sequence"] = index
            row.pop("_sort_time", None)
        return rows

    def _timeline_row(
        self,
        timestamp: datetime | str,
        phase: str,
        actor: str,
        summary: str,
        trace_event: TraceEvent | None = None,
    ) -> dict[str, Any]:
        parsed = self._parse_time(timestamp)
        return {
            "_sort_time": parsed.isoformat(),
            "timestamp": parsed.isoformat(),
            "phase": phase,
            "actor": actor,
            "summary": summary,
            "trace_event_id": trace_event.event_id if trace_event else "",
            "node": trace_event.node if trace_event else "",
            "status": trace_event.status if trace_event else "ok",
        }

    def _internal_handoff(self, summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "handoff_type": "on_call_internal",
            "status": summary["status"],
            "customer": summary["customer"],
            "severity": summary["severity"],
            "owners": summary["owners"],
            "sla_deadline": summary["sla_deadline"],
            "trace_links": summary["trace_links"],
            "operator_brief": (
                f"{summary['customer']} has `{summary['subject']}` at {summary['severity']} "
                f"with communication readiness `{summary['customer_communication_readiness']['status']}`."
            ),
            "next_steps": [item["next_step"] for item in summary["risk_gap_checklist"]],
        }

    def _approval_checklist(self, summary: dict[str, Any]) -> list[dict[str, str]]:
        guardrails = summary["approval_and_guardrail_status"]
        return [
            {
                "item": "Customer update grounded and approved",
                "status": "pending"
                if guardrails["pending_approval_count"]
                else summary["customer_communication_readiness"]["status"],
                "evidence": guardrails.get("approval_id") or "approval not created",
            },
            {
                "item": "Guardrails reviewed",
                "status": guardrails["policy_decision"],
                "evidence": ", ".join(guardrails["matched_rule_ids"]) or "no matched rules",
            },
            {
                "item": "Engineering incident ticket prepared",
                "status": summary["engineering_incident_ticket_summary"]["status"],
                "evidence": summary["engineering_incident_ticket_summary"]["trace_id"],
            },
            {
                "item": "SLA/customer-impact timeline attached",
                "status": summary["sla"]["risk_level"],
                "evidence": summary["sla_deadline"],
            },
        ]

    def _trace_ids(self, summary: dict[str, Any], coverage: dict[str, Any]) -> list[str]:
        ids = [summary["trace_id"]]
        ids.extend(row["trace_id"] for row in coverage["scenarios"])
        return list(dict.fromkeys(ids))

    def _coverage_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        domains = {row["domain"] for row in rows}
        required_paths = {
            name: bool(domains & required)
            for name, required in REQUIRED_SCENARIO_DOMAINS.items()
        }
        return {
            "required_paths": required_paths,
            "domains": dict(Counter(row["domain"] for row in rows)),
            "high_sla_risk_count": sum(1 for row in rows if row["sla_level"] == "high"),
            "approval_pause_count": sum(1 for row in rows if row["approval_pause"]),
            "low_confidence_count": sum(1 for row in rows if row["low_confidence"]),
            "tool_retry_count": sum(1 for row in rows if row["tool_retry"]),
            "failure_state_count": sum(1 for row in rows if row["failure_state"]),
        }

    def _requires_engineering(self, run: RunRecord) -> bool:
        drafts = run.state.get("drafts", {})
        return bool(drafts.get("engineering_escalation")) or run.state.get("sla_risk", {}).get("level") == "high"

    def _is_low_confidence(self, run: RunRecord) -> bool:
        return run.state.get("qa", {}).get("confidence", 1.0) < self.workflow.low_confidence_threshold

    def _tool_error_count(self, run: RunRecord) -> int:
        return sum(1 for call in run.state.get("tool_calls", []) if call.get("status") == "error")

    def _next_comms_action(self, status: str) -> str:
        return {
            "pending_approval": "Support Lead reviews the customer draft and engineering ticket.",
            "blocked_guardrail_review": "Resolve guardrail blockers, then re-run handoff summary.",
            "blocked_tool_failure_review": "Restore grounding or attach manual KB evidence before approval.",
            "dispatch_recorded": "Confirm customer-visible reply and monitor follow-up.",
        }.get(status, "Route drafts through approval before external dispatch.")

    def _parse_time(self, value: datetime | str) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _markdown(self, pack: dict[str, Any]) -> str:
        summary = pack["on_call_handoff_summary"]
        updates = [
            f"- **{item['type']}** ({item['status']}): {item['subject']}"
            for item in pack["customer_updates"]
        ]
        timeline = [
            f"- {item['sequence']}. {item['timestamp']} | {item['phase']}: {item['summary']}"
            for item in pack["sla_customer_impact_timeline"]
        ]
        checklist = [
            f"- {item['item']}: {item['status']} ({item['evidence']})"
            for item in pack["approval_checklist"]
        ]
        risks = [
            f"- {item['risk']} ({item['owner']}): {item['next_step']}"
            for item in pack["risk_gap_checklist"]
        ]
        scenarios = [
            (
                f"| {item['scenario_id']} | {item['domain']} | {item['severity']} | "
                f"{item['approval_pause']} | {item['communication_readiness']} |"
            )
            for item in pack["scenario_coverage"]["scenarios"]
        ]
        commands = [f"- `{command}`" for command in pack["local_proof_commands"]]
        limitations = [f"- {item}" for item in pack["limitations"]]
        return "\n".join(
            [
                f"# Customer Communications Simulation Pack: {pack['pack_id']}",
                "",
                "## On-Call Handoff",
                f"- Customer: {summary['customer']}",
                f"- Severity: {summary['severity']}",
                f"- Status: {summary['status']}",
                f"- SLA deadline: {summary['sla_deadline']}",
                f"- Communication readiness: {summary['customer_communication_readiness']['status']}",
                f"- Run: `{summary['run_id']}`",
                f"- Trace: `{summary['trace_id']}`",
                "",
                "## Customer Updates",
                *updates,
                "",
                "## Internal Handoff",
                pack["internal_handoff"]["operator_brief"],
                "",
                "## Engineering Ticket Draft",
                f"- Title: {pack['engineering_ticket_draft']['title']}",
                f"- Owner: {pack['engineering_ticket_draft']['owner']}",
                f"- Status: {pack['engineering_ticket_draft']['status']}",
                "",
                "## SLA / Customer Impact Timeline",
                *timeline,
                "",
                "## Approval Checklist",
                *checklist,
                "",
                "## Risk / Gap Checklist",
                *risks,
                "",
                "## Scenario Coverage",
                "| Scenario | Domain | Severity | Approval Pause | Communication Readiness |",
                "| --- | --- | --- | --- | --- |",
                *scenarios,
                "",
                "## Local Proof Commands",
                *commands,
                "",
                "## Limitations",
                *limitations,
                "",
            ]
        )
