import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.storage import JsonStateStore
from app.models import Approval, AuditEvent, OutboxEvent, RunRecord, Ticket, TicketCreate, TraceEvent
from app.services.approvals import ApprovalService
from app.services.audit import AuditService
from app.services.oncall_handoff import OnCallHandoffService
from app.services.tickets import TicketService
from app.services.trace import TraceService
from app.services.workflow import AgentWorkflowService


RCA_VERIFY_COMMANDS = [
    r".\.venv\Scripts\python.exe -m pytest -q",
    r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
    r".\.venv\Scripts\python.exe -m app.evals.run_eval",
    r".\.venv\Scripts\python.exe scripts\dashboard_smoke.py",
    r".\.venv\Scripts\python.exe scripts\demo_run.py",
    (
        r'rg "incidents/postmortem-summary|incidents/rca-pack|Postmortem RCA|'
        r'Corrective Action|rca_packs|root cause" app dashboard docs README.md tests scripts sample_data'
    ),
    (
        r"Get-ChildItem -Recurse -File data\rca_packs -ErrorAction SilentlyContinue "
        r"| Select-Object FullName,Length,LastWriteTime"
    ),
]

RCA_SCENARIO_IDS = [
    "scn_enterprise_login_outage",
    "scn_webhook_api_regression",
    "scn_webhook_kb_failure",
    "scn_privacy_data_export",
    "scn_renewal_risk_billing_credit",
    "scn_low_confidence_ambiguity",
]

ROOT_CAUSE_LABELS = {
    "product_or_api_incident": "Product/API incident",
    "tool_failure_retry_exhausted": "Tool failure / retry exhausted",
    "privacy_data_handling": "Privacy/data export handling",
    "billing_customer_risk": "Billing/customer risk",
    "ambiguous_low_confidence": "Low-confidence ambiguity",
    "process_followup_gap": "Process/customer follow-up gap",
}


class PostmortemRcaService:
    """Builds postmortem, root-cause, and corrective-action proof artifacts."""

    def __init__(
        self,
        store: JsonStateStore,
        tickets: TicketService,
        workflow: AgentWorkflowService,
        trace: TraceService,
        approvals: ApprovalService,
        audit: AuditService,
        oncall_handoff: OnCallHandoffService,
        scenario_fixture: Path,
        rca_dir: Path,
    ):
        self.store = store
        self.tickets = tickets
        self.workflow = workflow
        self.trace = trace
        self.approvals = approvals
        self.audit = audit
        self.oncall_handoff = oncall_handoff
        self.scenario_fixture = scenario_fixture
        self.rca_dir = rca_dir

    async def postmortem_summary(self, run_id: str | None = None) -> dict[str, Any]:
        run, ticket, source = await self._resolve_run(run_id)
        context = await self._context(run)
        root_cause = self._root_cause(run, ticket)
        timeline = self._timeline(ticket, run, context)
        corrective_actions = self._corrective_actions(run, ticket, root_cause, context)
        approval_comms = self._approval_comms_status(run, context)
        recurrence_risk = self._recurrence_risk(run, root_cause, context)
        readiness = self._readiness_summary(run, corrective_actions, approval_comms, recurrence_risk)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "title": "Postmortem RCA Summary",
            "mode": "local-deterministic-postmortem-rca",
            "source": source,
            "run_id": run.run_id,
            "ticket_id": ticket.ticket_id,
            "trace_id": run.trace_id,
            "incident_summary": self._incident_summary(ticket, run, root_cause),
            "severity": self._severity(run, ticket),
            "timeline": timeline,
            "root_cause_category": root_cause,
            "root cause": root_cause,
            "contributing_factors": self._contributing_factors(run, ticket, context),
            "impacted_customer": self._customer(ticket),
            "impacted_account": ticket.account or ticket.customer or self._customer(ticket),
            "approval_comms_status": approval_comms,
            "trace_links": self._trace_links(run, context),
            "corrective_actions": corrective_actions,
            "customer_follow_up_state": self._customer_follow_up_state(run, context),
            "recurrence_risk": recurrence_risk,
            "scenario_coverage": await self._scenario_coverage(),
            "readiness_summary": readiness,
            "local_proof_commands": RCA_VERIFY_COMMANDS,
        }

    async def export_rca_pack(self, run_id: str | None = None) -> dict[str, Any]:
        summary = await self.postmortem_summary(run_id)
        generated_at = datetime.now(timezone.utc)
        pack_id = f"rca_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        json_path = self.rca_dir / f"{pack_id}.json"
        markdown_path = self.rca_dir / f"{pack_id}.md"
        audit_evidence = await self._audit_evidence(summary["run_id"], summary["trace_id"])
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "title": "Postmortem RCA + Corrective Action Tracking Pack",
            "postmortem_summary": summary,
            "postmortem_narrative": self._postmortem_narrative(summary),
            "timeline": summary["timeline"],
            "trace_audit_evidence": audit_evidence,
            "action_owners": self._action_owner_table(summary["corrective_actions"]),
            "due_dates": self._due_date_table(summary["corrective_actions"]),
            "recurrence_risk": summary["recurrence_risk"],
            "customer_follow_up_state": summary["customer_follow_up_state"],
            "scenario_coverage": summary["scenario_coverage"],
            "proof_commands": RCA_VERIFY_COMMANDS,
            "reviewer_artifacts": {
                "rca_pack_markdown": str(markdown_path),
                "rca_pack_json": str(json_path),
                "summary_endpoint": "GET /incidents/postmortem-summary",
                "export_endpoint": "POST /incidents/rca-pack",
            },
            "limitations": [
                "RCA classification is deterministic and local; it does not inspect production logs or external SaaS systems.",
                "Corrective action owners and due dates are portfolio-ready defaults, not commitments from a real incident team.",
                "Customer follow-up state is inferred from local approval and outbox records; no customer message is sent.",
                "Scenario coverage runs local fake tickets and adapters only.",
            ],
        }
        markdown = self._markdown(pack)
        self.rca_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        await self.audit.record(
            AuditEvent(
                actor="postmortem-rca",
                action="incident.rca_pack_exported",
                resource_type="rca_pack",
                resource_id=pack_id,
                trace_id=summary["trace_id"],
                metadata={"markdown_path": str(markdown_path), "json_path": str(json_path)},
            )
        )
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "status": summary["readiness_summary"]["status"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "scenario_count": summary["scenario_coverage"]["scenario_count"],
            "coverage_status": summary["scenario_coverage"]["coverage_status"],
            "pack": pack,
            "markdown": markdown,
        }

    async def _resolve_run(self, run_id: str | None) -> tuple[RunRecord, Ticket, str]:
        if run_id:
            run = await self.workflow.get_run(run_id)
            return run, await self._ticket_for_run(run), "supplied_run"
        state = await self.store.load()
        if state["runs"]:
            run = RunRecord(**sorted(state["runs"].values(), key=lambda item: item.get("started_at", ""))[-1])
            return run, await self._ticket_for_run(run), "latest_run"
        scenario = self._scenarios_by_id()["scn_enterprise_login_outage"]
        ticket = await self._ingest_or_get_scenario_ticket(scenario)
        run = await self.workflow.analyze_ticket(ticket.ticket_id)
        return run, ticket, "scenario_bootstrap"

    async def _context(self, run: RunRecord) -> dict[str, Any]:
        state = await self.store.load()
        trace = await self.trace.list_events(run.run_id)
        approvals = [
            Approval(**raw)
            for raw in state["approvals"].values()
            if raw.get("run_id") == run.run_id
        ]
        outbox = [
            OutboxEvent(**raw)
            for raw in state["outbox"].values()
            if raw.get("run_id") == run.run_id
        ]
        oncall = await self._oncall_snapshot_for_run(run)
        return {"trace": trace, "approvals": approvals, "outbox": outbox, "oncall": oncall}

    async def _oncall_snapshot_for_run(self, run: RunRecord) -> dict[str, Any]:
        try:
            ticket = await self._ticket_for_run(run)
            context = await self.oncall_handoff._run_context(run, ticket)
            readiness = self.oncall_handoff._communication_readiness(run, context)
        except (KeyError, ValueError):
            readiness = {
                "status": "unknown",
                "communication readiness": False,
                "reasons": ["On-call snapshot could not resolve the RCA run ticket."],
            }
        return {"customer_communication_readiness": readiness}

    async def _scenario_coverage(self) -> dict[str, Any]:
        scenarios = [self._scenarios_by_id()[scenario_id] for scenario_id in RCA_SCENARIO_IDS]
        rows = []
        for scenario in scenarios:
            ticket = await self._ingest_or_get_scenario_ticket(scenario)
            run = await self.workflow.analyze_ticket(ticket.ticket_id)
            context = await self._context(run)
            root_cause = self._root_cause(run, ticket)
            rows.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "title": scenario["title"],
                    "domain": scenario["domain"],
                    "run_id": run.run_id,
                    "ticket_id": ticket.ticket_id,
                    "trace_id": run.trace_id,
                    "severity": self._severity(run, ticket),
                    "root_cause_category": root_cause["category"],
                    "root_cause_label": root_cause["label"],
                    "approval_pause": str(run.status) == "awaiting_approval",
                    "tool_retry": self._tool_error_count(run) > 0,
                    "low_confidence_review": self._is_low_confidence(run),
                    "customer_follow_up_state": self._customer_follow_up_state(run, context)["status"],
                    "corrective_action_count": len(self._corrective_actions(run, ticket, root_cause, context)),
                    "expected": scenario.get("expected", {}),
                }
            )
        required_paths = {
            "outage_api_incident": any(
                row["root_cause_category"] == "product_or_api_incident" for row in rows
            ),
            "tool_failure_retry": any(
                row["root_cause_category"] == "tool_failure_retry_exhausted" for row in rows
            ),
            "privacy_data_export": any(
                row["root_cause_category"] == "privacy_data_handling" for row in rows
            ),
            "billing_customer_risk": any(
                row["root_cause_category"] == "billing_customer_risk" for row in rows
            ),
            "low_confidence_human_review": any(
                row["root_cause_category"] == "ambiguous_low_confidence" for row in rows
            ),
        }
        return {
            "coverage_status": "pass" if all(required_paths.values()) else "gap",
            "scenario_count": len(rows),
            "required_paths": required_paths,
            "root_cause_counts": dict(Counter(row["root_cause_category"] for row in rows)),
            "scenarios": rows,
        }

    def _scenarios_by_id(self) -> dict[str, dict[str, Any]]:
        scenarios = json.loads(self.scenario_fixture.read_text(encoding="utf-8"))
        return {scenario["scenario_id"]: scenario for scenario in scenarios}

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

    def _root_cause(self, run: RunRecord, ticket: Ticket) -> dict[str, Any]:
        text = f"{ticket.subject} {ticket.body} {' '.join(ticket.tags)}".lower()
        classification = run.state.get("classification", {})
        category = classification.get("category", "")
        if run.failure_state or self._tool_error_count(run) > 0:
            key = "tool_failure_retry_exhausted"
        elif self._is_low_confidence(run):
            key = "ambiguous_low_confidence"
        elif category == "security_privacy" or any(word in text for word in ["privacy", "export", "deletion", "compliance", "breach"]):
            key = "privacy_data_handling"
        elif category == "billing" or any(word in text for word in ["billing", "invoice", "refund", "credit", "renewal"]):
            key = "billing_customer_risk"
        elif category in {"incident", "bug", "api_integrations", "authentication"} or any(
            word in text for word in ["outage", "5xx", "500", "webhook", "login loop", "production"]
        ):
            key = "product_or_api_incident"
        else:
            key = "process_followup_gap"
        confidence = classification.get("confidence", 0)
        return {
            "category": key,
            "label": ROOT_CAUSE_LABELS[key],
            "classification_category": category or "unknown",
            "confidence": confidence,
            "rationale": self._root_cause_rationale(key, run, ticket),
        }

    def _root_cause_rationale(self, key: str, run: RunRecord, ticket: Ticket) -> str:
        if key == "tool_failure_retry_exhausted":
            return "The trace captured failed tool calls or a workflow failure_state before human review."
        if key == "ambiguous_low_confidence":
            return "The workflow confidence fell below the human-review threshold, so RCA stays in ambiguity review."
        if key == "privacy_data_handling":
            return "Ticket content and classification indicate privacy, export, deletion, compliance, or breach handling risk."
        if key == "billing_customer_risk":
            return "Ticket content and classification indicate invoice, credit, refund, or renewal exposure."
        if key == "product_or_api_incident":
            return "The ticket describes production, outage, API, webhook, authentication, or regression impact."
        return f"The incident for {self._customer(ticket)} needs a follow-up process review."

    def _incident_summary(self, ticket: Ticket, run: RunRecord, root_cause: dict[str, Any]) -> dict[str, Any]:
        return {
            "subject": ticket.subject,
            "customer": self._customer(ticket),
            "ticket_priority": str(ticket.priority),
            "ticket_status": str(ticket.status),
            "workflow_status": str(run.status),
            "final_action": run.final_action or "pending",
            "classification": run.state.get("classification", {}),
            "sla_risk": run.state.get("sla_risk", {}),
            "root_cause_label": root_cause["label"],
            "summary": (
                f"{self._customer(ticket)} reported `{ticket.subject}`. "
                f"The local agent classified it as `{root_cause['classification_category']}` with "
                f"RCA category `{root_cause['category']}` and workflow status `{run.status}`."
            ),
        }

    def _severity(self, run: RunRecord, ticket: Ticket) -> str:
        sla = run.state.get("sla_risk", {})
        if run.failure_state or sla.get("score", 0) >= 0.9:
            return "sev1"
        if ticket.priority == "urgent" or sla.get("level") == "high":
            return "sev2"
        if ticket.priority == "high" or sla.get("level") == "medium":
            return "sev3"
        return "sev4"

    def _timeline(self, ticket: Ticket, run: RunRecord, context: dict[str, Any]) -> list[dict[str, Any]]:
        rows = [
            self._timeline_row(ticket.created_at, "ticket_intake", "customer", ticket.subject),
            self._timeline_row(run.started_at, "agent_run_started", "agent", f"Run {run.run_id} started."),
        ]
        for event in context["trace"]:
            if event.event_type in {"node_end", "tool_call", "outbox_dispatch"}:
                rows.append(self._timeline_row(event.timestamp, event.event_type, "agent", event.message, event))
        for approval in context["approvals"]:
            rows.append(
                self._timeline_row(
                    approval.created_at,
                    "approval_requested",
                    "support_lead",
                    approval.reason,
                    evidence_id=approval.approval_id,
                )
            )
            if approval.decided_at:
                rows.append(
                    self._timeline_row(
                        approval.decided_at,
                        "approval_decided",
                        approval.decided_by or "support_lead",
                        str(approval.status),
                        evidence_id=approval.approval_id,
                    )
                )
        for event in context["outbox"]:
            rows.append(
                self._timeline_row(
                    event.created_at,
                    f"outbox_{event.action_type}",
                    "agent",
                    f"Recorded {event.action_type} to {event.destination}.",
                    evidence_id=event.outbox_id,
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
        evidence_id: str = "",
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
            "evidence_id": evidence_id,
        }

    def _contributing_factors(self, run: RunRecord, ticket: Ticket, context: dict[str, Any]) -> list[dict[str, str]]:
        factors = []
        sla = run.state.get("sla_risk", {})
        qa = run.state.get("qa", {})
        if sla.get("level") in {"high", "medium"}:
            factors.append(
                {
                    "factor": "SLA/customer-impact pressure",
                    "evidence": ", ".join(sla.get("reasons", [])) or str(sla.get("score", "")),
                }
            )
        if any(approval.status == "pending" for approval in context["approvals"]):
            factors.append({"factor": "Human approval gate still pending", "evidence": run.state.get("approval_id", "")})
        if run.failure_state:
            factors.append({"factor": "Tool retry failure", "evidence": json.dumps(run.failure_state)})
        if qa.get("confidence", 1.0) < self.workflow.low_confidence_threshold:
            factors.append({"factor": "Low-confidence grounding", "evidence": str(qa.get("confidence"))})
        if ticket.customer_tier == "enterprise":
            factors.append({"factor": "Enterprise account sensitivity", "evidence": ticket.customer_tier})
        if not context["outbox"]:
            factors.append({"factor": "No customer-visible dispatch recorded", "evidence": str(run.status)})
        return factors or [{"factor": "Standard follow-up risk", "evidence": run.run_id}]

    def _approval_comms_status(self, run: RunRecord, context: dict[str, Any]) -> dict[str, Any]:
        pending = [approval for approval in context["approvals"] if approval.status == "pending"]
        decided = [approval for approval in context["approvals"] if approval.status != "pending"]
        customer_dispatches = [
            event for event in context["outbox"] if str(event.action_type) in {"customer_reply", "zendesk_update"}
        ]
        engineering_dispatches = [
            event
            for event in context["outbox"]
            if str(event.action_type) in {"engineering_escalation", "jira_issue", "slack_alert"}
        ]
        return {
            "approval_status": run.state.get("approval_status", "unknown"),
            "approval_id": run.state.get("approval_id"),
            "pending_approval_count": len(pending),
            "decided_approval_count": len(decided),
            "customer_comms_status": "sent" if customer_dispatches else "draft_pending_approval",
            "engineering_comms_status": "sent" if engineering_dispatches else "draft_or_not_required",
            "customer_dispatch_ids": [event.outbox_id for event in customer_dispatches],
            "engineering_dispatch_ids": [event.outbox_id for event in engineering_dispatches],
            "on_call_readiness": context["oncall"]["customer_communication_readiness"]["status"],
        }

    def _trace_links(self, run: RunRecord, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "run": f"/runs/{run.run_id}",
            "trace": f"/runs/{run.run_id}/trace",
            "approval_queue": "/approvals",
            "outbox": "/integrations/outbox",
            "event_count": len(context["trace"]),
            "trace_event_ids": [event.event_id for event in context["trace"][:10]],
        }

    def _corrective_actions(
        self,
        run: RunRecord,
        ticket: Ticket,
        root_cause: dict[str, Any],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        actions = [
            self._action(
                "ca_customer_followup",
                "Customer Success",
                "Confirm customer follow-up status and capture customer acknowledgement.",
                context["outbox"] and "in_progress" or "pending",
                now + timedelta(days=1),
                f"/runs/{run.run_id}/trace",
            ),
            self._action(
                "ca_trace_evidence_review",
                "Support Ops",
                "Review trace, approval, and outbox evidence for reviewer-ready auditability.",
                "completed" if context["trace"] else "pending",
                now + timedelta(days=2),
                f"/runs/{run.run_id}/trace",
            ),
        ]
        category = root_cause["category"]
        if category == "product_or_api_incident":
            actions.extend(
                [
                    self._action(
                        "ca_mitigation_owner_eta",
                        "Engineering Manager",
                        "Publish mitigation owner, rollback status, customer-safe ETA, and recurrence guard.",
                        "pending",
                        now + timedelta(days=2),
                        run.trace_id,
                    ),
                    self._action(
                        "ca_playbook_update",
                        "Incident Commander",
                        "Update outage/API playbook with detection, triage, and customer update checkpoints.",
                        "pending",
                        now + timedelta(days=7),
                        ticket.ticket_id,
                    ),
                ]
            )
        elif category == "tool_failure_retry_exhausted":
            actions.extend(
                [
                    self._action(
                        "ca_adapter_retry_runbook",
                        "Platform Support",
                        "Add adapter health precheck, fallback citation path, and exhausted-retry operator prompt.",
                        "pending",
                        now + timedelta(days=3),
                        json.dumps(run.failure_state or {}),
                    ),
                    self._action(
                        "ca_kb_fixture_repair",
                        "Knowledge Owner",
                        "Repair missing or failing KB retrieval fixture before customer-visible automation resumes.",
                        "pending",
                        now + timedelta(days=5),
                        run.run_id,
                    ),
                ]
            )
        elif category == "privacy_data_handling":
            actions.append(
                self._action(
                    "ca_privacy_approval_matrix",
                    "Privacy Reviewer",
                    "Document export/deletion verification gates and required customer-safe wording.",
                    "pending",
                    now + timedelta(days=5),
                    ticket.ticket_id,
                )
            )
        elif category == "billing_customer_risk":
            actions.append(
                self._action(
                    "ca_billing_credit_owner",
                    "Billing Operations",
                    "Assign refund/credit owner and renewal-risk escalation path for the account.",
                    "pending",
                    now + timedelta(days=4),
                    ticket.ticket_id,
                )
            )
        elif category == "ambiguous_low_confidence":
            actions.append(
                self._action(
                    "ca_human_review_clarification",
                    "Support Lead",
                    "Request clarifying details and attach explicit human review notes before any automated answer.",
                    "pending",
                    now + timedelta(days=1),
                    run.state.get("approval_id", ""),
                )
            )
        return actions

    def _action(
        self,
        action_id: str,
        owner: str,
        action: str,
        status: str,
        due_at: datetime,
        evidence: str,
    ) -> dict[str, Any]:
        return {
            "action_id": action_id,
            "owner": owner,
            "action": action,
            "status": status,
            "due_at": due_at.date().isoformat(),
            "evidence": evidence,
        }

    def _customer_follow_up_state(self, run: RunRecord, context: dict[str, Any]) -> dict[str, Any]:
        customer_events = [
            event for event in context["outbox"] if str(event.action_type) in {"customer_reply", "zendesk_update"}
        ]
        if customer_events:
            status = "customer_update_sent"
            next_step = "Customer Success confirms acknowledgement and resolution sentiment."
        elif any(approval.status == "pending" for approval in context["approvals"]):
            status = "pending_approval"
            next_step = "Support Lead approves or rewrites the customer update."
        elif run.failure_state:
            status = "blocked_tool_review"
            next_step = "Resolve grounding failure before sending customer-visible RCA."
        else:
            status = "draft_needed"
            next_step = "Draft customer-safe follow-up with root cause and next update ETA."
        return {
            "status": status,
            "customer_update_sent": bool(customer_events),
            "latest_customer_dispatch_id": customer_events[-1].outbox_id if customer_events else "",
            "next_step": next_step,
        }

    def _recurrence_risk(
        self,
        run: RunRecord,
        root_cause: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        score = 20
        flags = []
        if root_cause["category"] in {"tool_failure_retry_exhausted", "ambiguous_low_confidence"}:
            score += 30
            flags.append("automation_guardrail")
        if root_cause["category"] == "product_or_api_incident":
            score += 25
            flags.append("customer_impact")
        if any(approval.status == "pending" for approval in context["approvals"]):
            score += 15
            flags.append("pending_approval")
        if not context["outbox"]:
            score += 10
            flags.append("followup_not_sent")
        if run.failure_state:
            score += 15
            flags.append("retry_exhaustion")
        score = min(score, 100)
        return {
            "score": score,
            "level": "high" if score >= 70 else "medium" if score >= 45 else "low",
            "flags": flags,
            "recommended_review_cadence": "daily" if score >= 70 else "weekly",
        }

    def _readiness_summary(
        self,
        run: RunRecord,
        corrective_actions: list[dict[str, Any]],
        approval_comms: dict[str, Any],
        recurrence_risk: dict[str, Any],
    ) -> dict[str, Any]:
        blockers = []
        if approval_comms["pending_approval_count"]:
            blockers.append("approval_pending")
        if approval_comms["customer_comms_status"] != "sent":
            blockers.append("customer_followup_not_sent")
        if recurrence_risk["level"] == "high":
            blockers.append("high_recurrence_risk")
        overdue_or_pending = [action for action in corrective_actions if action["status"] == "pending"]
        status = "ready" if not blockers and not overdue_or_pending else "needs_review"
        return {
            "status": status,
            "blockers": blockers,
            "open_corrective_action_count": len(overdue_or_pending),
            "completed_corrective_action_count": len(corrective_actions) - len(overdue_or_pending),
            "reviewer_ready": status == "ready" or bool(corrective_actions),
            "next_reviewer_step": "Review RCA pack Markdown and action owner table.",
        }

    async def _audit_evidence(self, run_id: str, trace_id: str) -> dict[str, Any]:
        state = await self.store.load()
        events = [
            raw
            for raw in state["audit_events"].values()
            if raw.get("resource_id") == run_id or raw.get("trace_id") == trace_id
        ]
        events.sort(key=lambda item: item.get("timestamp", ""))
        return {
            "audit_event_count": len(events),
            "audit_events": events[-20:],
            "trace_link": f"/runs/{run_id}/trace",
            "approval_link": "/approvals",
            "outbox_link": "/integrations/outbox",
        }

    def _postmortem_narrative(self, summary: dict[str, Any]) -> str:
        impact = summary["incident_summary"]
        root = summary["root_cause_category"]
        return (
            f"{summary['impacted_customer']} experienced `{impact['subject']}` at {summary['severity']}. "
            f"The workflow classified the issue as `{impact['classification'].get('category', 'unknown')}` and "
            f"RCA classified root cause as `{root['category']}` ({root['label']}). "
            f"Current readiness is `{summary['readiness_summary']['status']}` with "
            f"{summary['readiness_summary']['open_corrective_action_count']} open corrective actions."
        )

    def _action_owner_table(self, actions: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "action_id": action["action_id"],
                "owner": action["owner"],
                "status": action["status"],
                "evidence": action["evidence"],
            }
            for action in actions
        ]

    def _due_date_table(self, actions: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "action_id": action["action_id"],
                "owner": action["owner"],
                "due_at": action["due_at"],
                "status": action["status"],
            }
            for action in actions
        ]

    def _markdown(self, pack: dict[str, Any]) -> str:
        summary = pack["postmortem_summary"]
        root = summary["root_cause_category"]
        timeline_rows = [
            f"- {item['sequence']}. {item['timestamp']} | {item['phase']} | {item['summary']}"
            for item in pack["timeline"]
        ]
        factor_rows = [
            f"- {item['factor']}: {item['evidence']}"
            for item in summary["contributing_factors"]
        ]
        action_rows = [
            (
                f"| {item['action_id']} | {item['owner']} | {item['status']} | "
                f"{item['due_at']} | {item['action']} |"
            )
            for item in summary["corrective_actions"]
        ]
        scenario_rows = [
            (
                f"| {item['scenario_id']} | {item['domain']} | {item['root_cause_category']} | "
                f"{item['severity']} | {item['customer_follow_up_state']} |"
            )
            for item in pack["scenario_coverage"]["scenarios"]
        ]
        command_rows = [f"- `{command}`" for command in pack["proof_commands"]]
        limitation_rows = [f"- {item}" for item in pack["limitations"]]
        return "\n".join(
            [
                f"# Postmortem RCA + Corrective Action Tracking Pack: {pack['pack_id']}",
                "",
                "## Postmortem Narrative",
                pack["postmortem_narrative"],
                "",
                "## Root Cause",
                f"- Category: `{root['category']}`",
                f"- Label: {root['label']}",
                f"- Rationale: {root['rationale']}",
                "",
                "## Incident Summary",
                f"- Customer: {summary['impacted_customer']}",
                f"- Severity: {summary['severity']}",
                f"- Workflow status: {summary['incident_summary']['workflow_status']}",
                f"- Final action: {summary['incident_summary']['final_action']}",
                f"- Customer follow-up: {summary['customer_follow_up_state']['status']}",
                "",
                "## Timeline",
                *timeline_rows,
                "",
                "## Contributing Factors",
                *factor_rows,
                "",
                "## Corrective Action Tracking",
                "| Action ID | Owner | Status | Due | Corrective Action |",
                "| --- | --- | --- | --- | --- |",
                *action_rows,
                "",
                "## Trace / Audit Evidence",
                f"- Trace: `{pack['trace_audit_evidence']['trace_link']}`",
                f"- Audit events: {pack['trace_audit_evidence']['audit_event_count']}",
                f"- Approval link: `{pack['trace_audit_evidence']['approval_link']}`",
                f"- Outbox link: `{pack['trace_audit_evidence']['outbox_link']}`",
                "",
                "## Recurrence Risk",
                f"- Level: {pack['recurrence_risk']['level']}",
                f"- Score: {pack['recurrence_risk']['score']}",
                f"- Flags: {', '.join(pack['recurrence_risk']['flags']) or 'none'}",
                "",
                "## Scenario Coverage",
                f"- Status: {pack['scenario_coverage']['coverage_status']}",
                f"- Required paths: {pack['scenario_coverage']['required_paths']}",
                "| Scenario | Domain | Root Cause | Severity | Customer Follow-up |",
                "| --- | --- | --- | --- | --- |",
                *scenario_rows,
                "",
                "## Proof Commands",
                *command_rows,
                "",
                "## Limitations",
                *limitation_rows,
                "",
            ]
        )

    def _tool_error_count(self, run: RunRecord) -> int:
        return sum(1 for call in run.state.get("tool_calls", []) if call.get("status") == "error")

    def _is_low_confidence(self, run: RunRecord) -> bool:
        return run.state.get("qa", {}).get("confidence", 1.0) < self.workflow.low_confidence_threshold

    def _customer(self, ticket: Ticket) -> str:
        return ticket.customer or ticket.account or ticket.customer_email

    def _parse_time(self, value: datetime | str) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
