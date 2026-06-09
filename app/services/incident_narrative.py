import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore
from app.models import (
    Approval,
    AuditEvent,
    OutboxActionType,
    OutboxEvent,
    PolicySimulationRequest,
    ReplayModifiers,
    RunRecord,
    Ticket,
    TicketCreate,
    TicketPriority,
    TraceEvent,
)
from app.services.analytics import AnalyticsService
from app.services.approvals import ApprovalService
from app.services.audit import AuditService
from app.services.briefs import IncidentBriefService
from app.services.customers import CustomerHealthService
from app.services.ops import OpsService
from app.services.playbooks import PlaybookService
from app.services.policy_guardrails import PolicyGuardrailService
from app.services.replay_lab import ReplayLabService
from app.services.tickets import TicketService
from app.services.trace import TraceService
from app.services.workflow import AgentWorkflowService


SAMPLE_INCIDENT_TICKET = TicketCreate(
    external_id="incident-narrative-sample-enterprise-outage",
    subject="Customer Impact Timeline sample: enterprise SSO outage",
    body=(
        "Northstar Health cannot log in with SAML SSO. Production support agents are blocked, "
        "the customer reports an active outage, and SLA breach risk is high."
    ),
    customer="Northstar Health",
    customer_email="ops@northstar.example",
    priority=TicketPriority.urgent,
    customer_tier="enterprise",
    tags=["incident-narrative", "auth", "sso", "outage", "sla"],
)

NARRATIVE_REPLAY_MODIFIERS = ReplayModifiers(
    sla_pressure="critical",
    kb_context="conflicting",
    adapter_health="degraded",
    confidence_override=0.48,
    approval_policy="strict",
)


class IncidentNarrativeService:
    def __init__(
        self,
        store: JsonStateStore,
        tickets: TicketService,
        workflow: AgentWorkflowService,
        trace: TraceService,
        approvals: ApprovalService,
        briefs: IncidentBriefService,
        playbooks: PlaybookService,
        analytics: AnalyticsService,
        customers: CustomerHealthService,
        ops: OpsService,
        replay_lab: ReplayLabService,
        policy_guardrails: PolicyGuardrailService,
        audit: AuditService,
        narrative_dir: Path,
    ):
        self.store = store
        self.tickets = tickets
        self.workflow = workflow
        self.trace = trace
        self.approvals = approvals
        self.briefs = briefs
        self.playbooks = playbooks
        self.analytics = analytics
        self.customers = customers
        self.ops = ops
        self.replay_lab = replay_lab
        self.policy_guardrails = policy_guardrails
        self.audit = audit
        self.narrative_dir = narrative_dir

    async def timeline(self, run_id: str | None = None) -> dict[str, Any]:
        run, fallback_used = await self._resolve_run(run_id)
        ticket = await self._ticket_for_run(run)
        state = await self.store.load()
        trace = await self.trace.list_events(run.run_id)
        approvals = self._approvals_for_run(state, run.run_id)
        outbox = self._outbox_for_run(state, run.run_id)
        artifacts = await self._evidence_artifacts(run, ticket)
        policy = artifacts["policy_simulation"]
        replay = artifacts["replay_report"]["report"]["comparison"]
        account_brief = artifacts["account_brief"]["brief"]
        weekly_review = artifacts["weekly_review"]["review"]
        slo = artifacts["slo_budget"]
        checklist = artifacts["remediation_checklist"]["checklist"]
        incident_brief = artifacts["incident_brief"]["brief"]

        response = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run.run_id,
            "ticket_id": ticket.ticket_id,
            "trace_id": run.trace_id,
            "fallback_used": fallback_used,
            "customer_impact_summary": self._customer_impact_summary(
                ticket,
                run,
                account_brief,
                slo,
                policy,
                replay,
            ),
            "events": self._events(
                ticket=ticket,
                run=run,
                trace=trace,
                approvals=approvals,
                outbox=outbox,
                incident_brief=incident_brief,
                checklist=checklist,
                weekly_review=weekly_review,
                account_brief=account_brief,
                slo=slo,
                policy=policy,
                replay=replay,
                artifact_links=artifacts["artifact_links"],
            ),
            "internal_actions": self._internal_actions(run, approvals, outbox, checklist, policy, replay),
            "external_actions": self._external_actions(run, approvals, outbox, incident_brief),
            "policy_annotations": self._policy_annotations(policy),
            "replay_annotations": self._replay_annotations(replay),
            "unresolved_risks": self._unresolved_risks(run, approvals, outbox, policy, replay, slo),
            "owner_next_steps": self._owner_next_steps(
                run,
                approvals,
                outbox,
                checklist,
                policy,
                replay,
                slo,
                account_brief,
            ),
            "evidence_artifact_links": artifacts["artifact_links"],
        }
        response["impact_status"] = response["customer_impact_summary"]["impact_status"]
        return response

    async def export_executive_narrative(self, run_id: str | None = None) -> dict[str, Any]:
        timeline = await self.timeline(run_id)
        generated_at = datetime.now(timezone.utc)
        narrative_id = f"incident_narrative_{generated_at.strftime('%Y%m%d_%H%M%S')}_{timeline['run_id']}"
        narrative = {
            "narrative_id": narrative_id,
            "generated_at": generated_at.isoformat(),
            "run_id": timeline["run_id"],
            "ticket_id": timeline["ticket_id"],
            "trace_id": timeline["trace_id"],
            "impact_status": timeline["impact_status"],
            "executive_summary": self._executive_summary(timeline),
            "customer_impact": timeline["customer_impact_summary"],
            "timeline": timeline["events"],
            "decisions_made": self._decisions_made(timeline),
            "approval_evidence": self._approval_evidence(timeline),
            "policy_guardrail_decision": timeline["policy_annotations"],
            "replay_risk": timeline["replay_annotations"],
            "slo_posture": timeline["customer_impact_summary"]["slo_posture"],
            "owner_actions": timeline["owner_next_steps"],
            "unresolved_risks": timeline["unresolved_risks"],
            "evidence_artifact_links": timeline["evidence_artifact_links"],
            "local_commands": self._local_commands(),
            "jd_skills_demonstrated": self._jd_skills(),
            "interviewer_talking_points": self._talking_points(timeline),
        }
        markdown = self._markdown(narrative)
        json_path, markdown_path = self._write_files(narrative_id, narrative, markdown)
        narrative["artifact_paths"] = {
            "incident_narrative_json": str(json_path),
            "incident_narrative_markdown": str(markdown_path),
        }
        json_path.write_text(json.dumps(narrative, indent=2, default=str), encoding="utf-8")
        await self.audit.record(
            AuditEvent(
                actor="incident-narrative",
                action="incident.executive_narrative_exported",
                resource_type="run",
                resource_id=timeline["run_id"],
                trace_id=timeline["trace_id"],
                metadata={"markdown_path": str(markdown_path), "json_path": str(json_path)},
            )
        )
        return {
            "narrative_id": narrative_id,
            "format": "markdown+json",
            "run_id": timeline["run_id"],
            "ticket_id": timeline["ticket_id"],
            "impact_status": timeline["impact_status"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "narrative": narrative,
            "markdown": markdown,
        }

    async def _resolve_run(self, run_id: str | None) -> tuple[RunRecord, str]:
        if run_id:
            return await self.workflow.get_run(run_id), "supplied_run"
        state = await self.store.load()
        runs = list(state["runs"].values())
        if runs:
            return RunRecord(**sorted(runs, key=lambda item: item.get("started_at", ""))[-1]), "latest_run"

        ticket = await self.tickets.get_by_external_id(SAMPLE_INCIDENT_TICKET.external_id or "")
        if ticket is None:
            ticket = await self.tickets.ingest(SAMPLE_INCIDENT_TICKET)
        run = await self.workflow.analyze_ticket(ticket.ticket_id)
        run = await self.workflow.approve(
            run.run_id,
            "incident-narrative-sample",
            "Approved sample incident so timeline includes dispatched customer and engineering handoffs.",
        )
        return run, "sample_bootstrap"

    async def _ticket_for_run(self, run: RunRecord) -> Ticket:
        ticket = await self.tickets.get(run.ticket_id)
        if ticket is None:
            raise KeyError(run.ticket_id)
        return ticket

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

    async def _evidence_artifacts(self, run: RunRecord, ticket: Ticket) -> dict[str, Any]:
        incident_brief = await self.briefs.export(run.run_id)
        remediation_checklist = await self.playbooks.export_remediation_checklist(run.run_id)
        weekly_review = await self.analytics.export_weekly_review()
        account_brief = await self.customers.export_account_brief(
            ticket.customer or ticket.account or ticket.customer_email
        )
        slo_budget = await self.ops.slo_budget()
        optimization_report = await self.ops.export_optimization_report()
        replay_report = await self.replay_lab.export_report(run.run_id, NARRATIVE_REPLAY_MODIFIERS)
        policy_simulation = await self.policy_guardrails.simulate(
            PolicySimulationRequest(
                run_id=run.run_id,
                modifiers=NARRATIVE_REPLAY_MODIFIERS,
                requested_actions=[
                    OutboxActionType.customer_reply,
                    OutboxActionType.zendesk_update,
                    OutboxActionType.jira_issue,
                    OutboxActionType.slack_alert,
                    OutboxActionType.engineering_escalation,
                ],
                replay_risk_threshold=70,
            )
        )
        artifact_links = {
            "incident_brief_markdown": incident_brief["markdown_path"],
            "incident_brief_json": incident_brief["json_path"],
            "remediation_checklist_markdown": remediation_checklist["markdown_path"],
            "remediation_checklist_json": remediation_checklist["json_path"],
            "weekly_review_markdown": weekly_review["markdown_path"],
            "weekly_review_json": weekly_review["json_path"],
            "account_brief_markdown": account_brief["markdown_path"],
            "account_brief_json": account_brief["json_path"],
            "optimization_report_markdown": optimization_report["markdown_path"],
            "optimization_report_json": optimization_report["json_path"],
            "replay_report_markdown": replay_report["markdown_path"],
            "replay_report_json": replay_report["json_path"],
        }
        return {
            "incident_brief": incident_brief,
            "remediation_checklist": remediation_checklist,
            "weekly_review": weekly_review,
            "account_brief": account_brief,
            "slo_budget": slo_budget,
            "optimization_report": optimization_report,
            "replay_report": replay_report,
            "policy_simulation": policy_simulation,
            "artifact_links": artifact_links,
        }

    def _customer_impact_summary(
        self,
        ticket: Ticket,
        run: RunRecord,
        account_brief: dict[str, Any],
        slo: dict[str, Any],
        policy: dict[str, Any],
        replay: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_state = run.state
        classification = workflow_state.get("classification", {})
        sla_risk = workflow_state.get("sla_risk", {})
        health = account_brief["customer_health"]
        impact_status = self._impact_status(run, policy, replay, slo, health)
        return {
            "impact_status": impact_status,
            "customer": ticket.customer or ticket.account or health["account"],
            "account": health["account"],
            "segment": health.get("segment", "unknown"),
            "customer_tier": ticket.customer_tier,
            "priority": ticket.priority,
            "subject": ticket.subject,
            "summary": ticket.body,
            "ticket_status": ticket.status,
            "classification": classification,
            "sla_risk": sla_risk,
            "account_health_score": health["health_score"],
            "account_risk_level": health["risk_level"],
            "slo_posture": {
                "overall_status": slo["overall_status"],
                "failure_count": slo["metrics"]["failure_count"]["current_value"],
                "pending_approvals": slo["metrics"]["pending_approvals"]["current_value"],
                "outbox_dispatch_delay_minutes": slo["metrics"]["outbox_dispatch_delay_minutes"][
                    "current_value"
                ],
            },
            "policy_decision": policy["policy_decision"],
            "replay_risk_score": replay["comparison"]["risk_score"],
            "final_action": run.final_action,
        }

    def _impact_status(
        self,
        run: RunRecord,
        policy: dict[str, Any],
        replay: dict[str, Any],
        slo: dict[str, Any],
        health: dict[str, Any],
    ) -> str:
        if policy["policy_decision"] == "blocked_pending_remediation":
            return "blocked_by_guardrail"
        if replay["comparison"]["risk_score"] >= 75:
            return "at_risk_replay_change"
        if health["risk_level"] in {"critical", "at_risk"}:
            return "customer_at_risk"
        if slo["overall_status"] == "fail":
            return "ops_slo_at_risk"
        if run.status == "completed":
            return "contained_with_followup"
        return "pending_owner_action"

    def _events(
        self,
        *,
        ticket: Ticket,
        run: RunRecord,
        trace: list[TraceEvent],
        approvals: list[Approval],
        outbox: list[OutboxEvent],
        incident_brief: dict[str, Any],
        checklist: dict[str, Any],
        weekly_review: dict[str, Any],
        account_brief: dict[str, Any],
        slo: dict[str, Any],
        policy: dict[str, Any],
        replay: dict[str, Any],
        artifact_links: dict[str, str],
    ) -> list[dict[str, Any]]:
        events = []

        def add(
            timestamp: datetime | str | None,
            phase: str,
            actor: str,
            visibility: str,
            summary: str,
            evidence: list[dict[str, str]] | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            events.append(
                {
                    "_sort_time": self._parse_time(timestamp) or datetime.now(timezone.utc),
                    "_insert_order": len(events),
                    "timestamp": self._iso(timestamp),
                    "phase": phase,
                    "actor": actor,
                    "visibility": visibility,
                    "summary": summary,
                    "evidence": evidence or [],
                    "metadata": metadata or {},
                }
            )

        add(
            ticket.created_at,
            "ticket_intake",
            "customer",
            "external",
            f"Ticket received from {ticket.customer or ticket.account or ticket.customer_email}: {ticket.subject}",
            [{"label": "Incident brief", "path": artifact_links["incident_brief_markdown"]}],
            {"ticket_id": ticket.ticket_id, "priority": ticket.priority, "tier": ticket.customer_tier},
        )
        add(
            run.started_at,
            "triage_started",
            "agent",
            "internal",
            "Agent run started and trace capture began.",
            [{"label": "Trace", "path": f"/runs/{run.run_id}/trace"}],
            {"run_id": run.run_id, "trace_id": run.trace_id},
        )

        node_summaries = self._node_summaries(run)
        for event in trace:
            if event.event_type != "node_end" or not event.node:
                continue
            summary = node_summaries.get(event.node, event.message or f"{event.node} completed.")
            add(
                event.timestamp,
                self._phase_for_node(event.node),
                "agent",
                "internal",
                summary,
                [{"label": "Trace event", "path": f"/runs/{run.run_id}/trace"}],
                {"node": event.node, "latency_ms": event.latency_ms},
            )

        for approval in approvals:
            add(
                approval.created_at,
                "human_approval_requested",
                "agent",
                "internal",
                f"Human approval requested: {approval.reason}",
                [{"label": "Approval queue", "path": "/approvals"}],
                {"approval_id": approval.approval_id, "status": approval.status},
            )
            if approval.decided_at:
                add(
                    approval.decided_at,
                    "human_approval_decided",
                    approval.decided_by or "human",
                    "internal",
                    f"Approval {approval.status} by {approval.decided_by or 'human reviewer'}.",
                    [{"label": "Approval record", "path": "/approvals"}],
                    {
                        "approval_id": approval.approval_id,
                        "decision_note": approval.decision_note,
                    },
                )

        for event in outbox:
            add(
                event.created_at,
                self._phase_for_outbox(event),
                "agent",
                "external" if event.action_type in {"customer_reply", "zendesk_update"} else "internal",
                f"Dispatched {event.action_type} to {event.destination}.",
                [{"label": "Outbox event", "path": f"/integrations/outbox/{event.outbox_id}"}],
                {
                    "outbox_id": event.outbox_id,
                    "status": event.status,
                    "action_type": event.action_type,
                },
            )

        add(
            policy["generated_at"],
            "policy_guardrail_decision",
            "policy_guardrail",
            "internal",
            (
                f"Policy simulator decided {policy['policy_decision']} with "
                f"{len(policy['matched_rules'])} matched rules."
            ),
            [{"label": "Policy inputs", "path": "/policies/simulate"}],
            {
                "policy_decision": policy["policy_decision"],
                "required_approval_type": policy["required_approval_type"],
                "blocked_actions": policy["blocked_actions"],
            },
        )
        add(
            replay["generated_at"],
            "replay_risk_review",
            "replay_lab",
            "internal",
            (
                "Replay Lab scored change risk "
                f"{replay['comparison']['risk_score']} and recommended operator review."
            ),
            [{"label": "Replay report", "path": artifact_links["replay_report_markdown"]}],
            {
                "risk_score": replay["comparison"]["risk_score"],
                "risk_flags": replay["comparison"]["risk_flags"],
            },
        )
        add(
            checklist["generated_at"],
            "remediation_plan",
            "support_lead",
            "internal",
            f"Remediation checklist selected {checklist['selected_playbook']['title']}.",
            [{"label": "Remediation checklist", "path": artifact_links["remediation_checklist_markdown"]}],
            {
                "owners": checklist["owners"],
                "playbook_id": checklist["selected_playbook"]["id"],
            },
        )
        add(
            account_brief["generated_at"],
            "customer_health_review",
            "customer_success",
            "internal",
            (
                f"Account health reviewed as {account_brief['customer_health']['risk_level']} "
                f"with score {account_brief['customer_health']['health_score']}."
            ),
            [{"label": "Account brief", "path": artifact_links["account_brief_markdown"]}],
            {"customer_id": account_brief["customer_health"]["customer_id"]},
        )
        add(
            weekly_review["generated_at"],
            "weekly_ops_review",
            "support_ops",
            "internal",
            "Weekly review linked the incident to queue, dispatch, failure, and SLA trends.",
            [{"label": "Weekly review", "path": artifact_links["weekly_review_markdown"]}],
            {"run_count": weekly_review["summary_metrics"]["run_count"]},
        )
        add(
            slo["generated_at"],
            "slo_posture",
            "support_ops",
            "internal",
            f"SLO posture is {slo['overall_status']}.",
            [{"label": "Optimization report", "path": artifact_links["optimization_report_markdown"]}],
            {"overall_status": slo["overall_status"]},
        )

        ordered = sorted(events, key=lambda item: (item["_sort_time"], item["_insert_order"]))
        for sequence, item in enumerate(ordered, start=1):
            item["sequence"] = sequence
            item.pop("_sort_time", None)
            item.pop("_insert_order", None)
        return ordered

    def _node_summaries(self, run: RunRecord) -> dict[str, str]:
        state = run.state
        classification = state.get("classification", {})
        sla = state.get("sla_risk", {})
        qa = state.get("qa", {})
        recommendations = state.get("playbook_recommendations", [])
        selected = recommendations[0]["title"] if recommendations else "a fallback playbook"
        return {
            "intake_classifier": (
                f"Classified as {classification.get('category', 'unknown')} "
                f"with confidence {classification.get('confidence', 'unknown')}."
            ),
            "sla_risk_scorer": (
                f"SLA risk scored {sla.get('level', 'unknown')} "
                f"({sla.get('score', 'unknown')}) from {', '.join(sla.get('reasons', [])) or 'no explicit reasons'}."
            ),
            "playbook_recommender": f"Recommended {selected} for the support owner path.",
            "knowledge_retriever": f"Retrieved {len(state.get('kb_results', []))} KB grounding articles.",
            "customer_reply_drafter": "Drafted customer-facing status update for approval.",
            "engineering_escalation_drafter": "Prepared engineering escalation context and reproduction notes.",
            "qa_evaluator": (
                f"QA confidence {qa.get('confidence', 'unknown')} with "
                f"{len(qa.get('findings', []))} review findings."
            ),
            "human_approval": "Paused automation for human approval before customer or engineering dispatch.",
            "finalizer": f"Finalized run action: {run.final_action or state.get('final_action', 'pending')}.",
        }

    def _phase_for_node(self, node: str) -> str:
        return {
            "intake_classifier": "triage_classification",
            "sla_risk_scorer": "sla_risk_assessment",
            "playbook_recommender": "playbook_selection",
            "knowledge_retriever": "knowledge_grounding",
            "customer_reply_drafter": "customer_reply_drafted",
            "engineering_escalation_drafter": "engineering_escalation_drafted",
            "qa_evaluator": "qa_policy_precheck",
            "human_approval": "human_approval_gate",
            "finalizer": "workflow_finalized",
        }.get(node, node)

    def _phase_for_outbox(self, event: OutboxEvent) -> str:
        return {
            "customer_reply": "customer_reply_sent",
            "zendesk_update": "customer_ticket_updated",
            "engineering_escalation": "engineering_escalation_sent",
            "jira_issue": "engineering_ticket_created",
            "slack_alert": "war_room_notified",
        }.get(str(event.action_type), "outbox_dispatch")

    def _internal_actions(
        self,
        run: RunRecord,
        approvals: list[Approval],
        outbox: list[OutboxEvent],
        checklist: dict[str, Any],
        policy: dict[str, Any],
        replay: dict[str, Any],
    ) -> list[dict[str, Any]]:
        actions = [
            {
                "action": "triage_and_risk_assessment",
                "owner": "Support Agent",
                "status": "completed",
                "evidence": run.run_id,
            },
            {
                "action": "remediation_playbook_selected",
                "owner": ", ".join(checklist["owners"]) or "Support Lead",
                "status": "planned",
                "evidence": checklist["selected_playbook"]["id"],
            },
            {
                "action": "policy_guardrail_review",
                "owner": policy["required_approval_type"],
                "status": policy["policy_decision"],
                "evidence": policy["simulation_id"],
            },
            {
                "action": "replay_change_risk_review",
                "owner": "Policy Admin",
                "status": "review_required" if replay["comparison"]["risk_score"] >= 70 else "monitor",
                "evidence": replay["replay_id"],
            },
        ]
        for approval in approvals:
            actions.append(
                {
                    "action": "human_approval",
                    "owner": approval.decided_by or "Support Lead",
                    "status": approval.status,
                    "evidence": approval.approval_id,
                }
            )
        for event in outbox:
            if event.action_type not in {"customer_reply", "zendesk_update"}:
                actions.append(
                    {
                        "action": event.action_type,
                        "owner": "Engineering" if "jira" in event.destination else "Support Ops",
                        "status": event.status,
                        "evidence": event.outbox_id,
                    }
                )
        return actions

    def _external_actions(
        self,
        run: RunRecord,
        approvals: list[Approval],
        outbox: list[OutboxEvent],
        incident_brief: dict[str, Any],
    ) -> list[dict[str, Any]]:
        actions = []
        for approval in approvals:
            if approval.customer_reply:
                actions.append(
                    {
                        "action": "customer_reply_draft",
                        "status": approval.status,
                        "owner": approval.decided_by or "Support Lead",
                        "evidence": approval.approval_id,
                    }
                )
        for event in outbox:
            if event.action_type in {"customer_reply", "zendesk_update"}:
                actions.append(
                    {
                        "action": event.action_type,
                        "status": event.status,
                        "owner": "Support Agent",
                        "evidence": event.outbox_id,
                    }
                )
        if not actions:
            actions.append(
                {
                    "action": "customer_update_pending",
                    "status": run.status,
                    "owner": "Support Lead",
                    "evidence": incident_brief["approval_status"].get("approval_id"),
                }
            )
        return actions

    def _policy_annotations(self, policy: dict[str, Any]) -> dict[str, Any]:
        return {
            "simulation_id": policy["simulation_id"],
            "policy_decision": policy["policy_decision"],
            "required_approval_type": policy["required_approval_type"],
            "approval_chain": policy["approval_chain"],
            "blocked_actions": policy["blocked_actions"],
            "allowed_actions": policy["allowed_actions"],
            "matched_rule_ids": [rule["rule_id"] for rule in policy["matched_rules"]],
            "warnings": policy["warnings"],
            "recommended_operator_action": policy["recommended_operator_action"],
        }

    def _replay_annotations(self, replay: dict[str, Any]) -> dict[str, Any]:
        return {
            "replay_id": replay["replay_id"],
            "risk_score": replay["comparison"]["risk_score"],
            "risk_flags": replay["comparison"]["risk_flags"],
            "changed_decisions": replay["comparison"]["changed_decisions"],
            "recommended_operator_action": replay["comparison"]["recommended_operator_action"],
            "modifiers": replay["modifiers"],
        }

    def _unresolved_risks(
        self,
        run: RunRecord,
        approvals: list[Approval],
        outbox: list[OutboxEvent],
        policy: dict[str, Any],
        replay: dict[str, Any],
        slo: dict[str, Any],
    ) -> list[dict[str, str]]:
        risks = []
        if any(approval.status == "pending" for approval in approvals):
            risks.append(
                {
                    "risk": "pending_human_approval",
                    "owner": "Support Lead",
                    "next_step": "Clear the pending approval before external dispatch.",
                }
            )
        if not outbox and run.status != "completed":
            risks.append(
                {
                    "risk": "no_customer_or_engineering_dispatch",
                    "owner": "Support Lead",
                    "next_step": "Approve, reject, or rewrite the proposed customer and engineering handoffs.",
                }
            )
        if policy["policy_decision"] == "blocked_pending_remediation":
            risks.append(
                {
                    "risk": "policy_guardrail_block",
                    "owner": policy["required_approval_type"],
                    "next_step": policy["recommended_operator_action"],
                }
            )
        if replay["comparison"]["risk_score"] >= 75:
            risks.append(
                {
                    "risk": "replay_change_risk",
                    "owner": "Policy Admin",
                    "next_step": replay["comparison"]["recommended_operator_action"],
                }
            )
        if slo["overall_status"] in {"warn", "fail"}:
            risks.append(
                {
                    "risk": "slo_budget_pressure",
                    "owner": "Support Ops",
                    "next_step": "Review optimization report and address failed or warning SLO metrics.",
                }
            )
        if not risks:
            risks.append(
                {
                    "risk": "standard_followup",
                    "owner": "Support Lead",
                    "next_step": "Continue monitoring customer confirmation and engineering mitigation.",
                }
            )
        return risks

    def _owner_next_steps(
        self,
        run: RunRecord,
        approvals: list[Approval],
        outbox: list[OutboxEvent],
        checklist: dict[str, Any],
        policy: dict[str, Any],
        replay: dict[str, Any],
        slo: dict[str, Any],
        account_brief: dict[str, Any],
    ) -> list[dict[str, str]]:
        steps = []
        if any(approval.status == "pending" for approval in approvals):
            steps.append(
                {
                    "owner": "Support Lead",
                    "action": "Review and decide the pending approval.",
                    "evidence": approvals[-1].approval_id,
                }
            )
        if outbox:
            steps.append(
                {
                    "owner": "Engineering Manager",
                    "action": "Acknowledge Jira or Slack escalation and publish mitigation ETA.",
                    "evidence": outbox[-1].outbox_id,
                }
            )
        steps.append(
            {
                "owner": ", ".join(checklist["owners"]) or "Incident Commander",
                "action": f"Work the {checklist['selected_playbook']['title']} remediation checklist.",
                "evidence": checklist["checklist_id"],
            }
        )
        steps.append(
            {
                "owner": policy["required_approval_type"] if policy["required_approval_type"] != "none" else "Support Ops",
                "action": policy["recommended_operator_action"],
                "evidence": policy["simulation_id"],
            }
        )
        steps.append(
            {
                "owner": "Policy Admin",
                "action": replay["comparison"]["recommended_operator_action"],
                "evidence": replay["replay_id"],
            }
        )
        if slo["overall_status"] in {"warn", "fail"}:
            steps.append(
                {
                    "owner": "Support Ops",
                    "action": "Address warning or failing SLO metrics before the next incident review.",
                    "evidence": slo["generated_at"],
                }
            )
        steps.append(
            {
                "owner": "Customer Success",
                "action": account_brief["customer_health"]["recommended_action"],
                "evidence": account_brief["account_brief_id"],
            }
        )
        if run.status == "completed":
            steps.append(
                {
                    "owner": "Support Lead",
                    "action": "Confirm customer-visible reply landed and collect customer confirmation.",
                    "evidence": run.run_id,
                }
            )
        return steps

    def _decisions_made(self, timeline: dict[str, Any]) -> list[str]:
        impact = timeline["customer_impact_summary"]
        return [
            f"Classified the incident as {impact['classification'].get('category', 'unknown')}.",
            f"Set SLA risk to {impact['sla_risk'].get('level', 'unknown')}.",
            f"Final workflow action is {impact['final_action'] or 'pending'}.",
            f"Policy guardrail decision is {timeline['policy_annotations']['policy_decision']}.",
            f"Replay risk score is {timeline['replay_annotations']['risk_score']}.",
        ]

    def _approval_evidence(self, timeline: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            event
            for event in timeline["events"]
            if event["phase"] in {"human_approval_requested", "human_approval_decided"}
        ]

    def _executive_summary(self, timeline: dict[str, Any]) -> str:
        impact = timeline["customer_impact_summary"]
        risks = ", ".join(item["risk"] for item in timeline["unresolved_risks"])
        return (
            f"{impact['account']} experienced `{impact['subject']}` with "
            f"{impact['sla_risk'].get('level', 'unknown')} SLA risk. "
            f"The workflow reached `{impact['final_action'] or 'pending'}` and the current impact status is "
            f"`{impact['impact_status']}`. Open risks: {risks}."
        )

    def _local_commands(self) -> list[str]:
        return [
            r".\.venv\Scripts\python.exe -m pytest -q",
            r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
            r".\.venv\Scripts\python.exe -m app.evals.run_eval",
            r".\.venv\Scripts\python.exe scripts\demo_run.py",
            (
                r'rg "incidents/timeline|incidents/executive-narrative|Incident Narrative|'
                r'incident_narratives|Customer Impact Timeline" app dashboard docs README.md tests scripts'
            ),
        ]

    def _jd_skills(self) -> list[str]:
        return [
            "Enterprise incident storytelling across agent trace, approval, dispatch, and customer impact evidence.",
            "FastAPI product surface design with deterministic local/mock workflow fallbacks.",
            "Human-in-the-loop governance connecting policy rules to customer-visible automation.",
            "Replay-based reliability analysis for counterfactual incident and rollout risk.",
            "Operator-ready Markdown and JSON artifacts with reproducible local verification commands.",
        ]

    def _talking_points(self, timeline: dict[str, Any]) -> list[str]:
        return [
            (
                f"The Customer Impact Timeline ties {len(timeline['events'])} ordered events "
                f"from ticket intake through policy and replay review."
            ),
            (
                f"The policy simulator produced `{timeline['policy_annotations']['policy_decision']}` "
                f"with rules {', '.join(timeline['policy_annotations']['matched_rule_ids'])}."
            ),
            (
                f"Replay Lab risk is {timeline['replay_annotations']['risk_score']} with flags "
                f"{', '.join(timeline['replay_annotations']['risk_flags'])}."
            ),
            "The narrative splits internal owner work from external customer-visible actions so leaders can audit accountability.",
            "The export links every artifact needed for an interviewer or support leader to reproduce the incident story locally.",
        ]

    def _markdown(self, narrative: dict[str, Any]) -> str:
        impact = narrative["customer_impact"]
        events = [
            (
                f"- {event['sequence']}. {event['timestamp']} | {event['phase']} | "
                f"{event['visibility']}: {event['summary']}"
            )
            for event in narrative["timeline"]
        ]
        decisions = [f"- {item}" for item in narrative["decisions_made"]]
        approvals = [
            f"- {item['timestamp']} | {item['phase']}: {item['summary']}"
            for item in narrative["approval_evidence"]
        ] or ["- No approval event recorded."]
        risks = [
            f"- {item['risk']} ({item['owner']}): {item['next_step']}"
            for item in narrative["unresolved_risks"]
        ]
        owner_actions = [
            f"- {item['owner']}: {item['action']} (evidence: {item['evidence']})"
            for item in narrative["owner_actions"]
        ]
        artifact_rows = [
            f"- {name}: `{path}`" for name, path in sorted(narrative["evidence_artifact_links"].items())
        ]
        commands = [f"- `{command}`" for command in narrative["local_commands"]]
        skills = [f"- {skill}" for skill in narrative["jd_skills_demonstrated"]]
        talking_points = [f"- {point}" for point in narrative["interviewer_talking_points"]]
        return "\n".join(
            [
                f"# Executive Incident Narrative: {narrative['run_id']}",
                "",
                "## Executive Summary",
                narrative["executive_summary"],
                "",
                "## Customer Impact",
                f"- Account: {impact['account']}",
                f"- Impact status: {impact['impact_status']}",
                f"- Priority: {impact['priority']}",
                f"- SLA risk: {impact['sla_risk'].get('level', 'unknown')} ({impact['sla_risk'].get('score', 'unknown')})",
                f"- Account health: {impact['account_risk_level']} ({impact['account_health_score']})",
                f"- SLO posture: {impact['slo_posture']['overall_status']}",
                "",
                "## Customer Impact Timeline",
                *events,
                "",
                "## Decisions Made",
                *decisions,
                "",
                "## Approval Evidence",
                *approvals,
                "",
                "## Policy Guardrail Decision",
                f"- Decision: {narrative['policy_guardrail_decision']['policy_decision']}",
                f"- Approval type: {narrative['policy_guardrail_decision']['required_approval_type']}",
                f"- Blocked actions: {', '.join(narrative['policy_guardrail_decision']['blocked_actions']) or 'none'}",
                f"- Matched rules: {', '.join(narrative['policy_guardrail_decision']['matched_rule_ids']) or 'none'}",
                "",
                "## Replay Risk",
                f"- Risk score: {narrative['replay_risk']['risk_score']}",
                f"- Risk flags: {', '.join(narrative['replay_risk']['risk_flags']) or 'none'}",
                f"- Recommended action: {narrative['replay_risk']['recommended_operator_action']}",
                "",
                "## SLO Posture",
                f"- Overall: {narrative['slo_posture']['overall_status']}",
                f"- Failures: {narrative['slo_posture']['failure_count']}",
                f"- Pending approvals: {narrative['slo_posture']['pending_approvals']}",
                "",
                "## Owner Actions",
                *owner_actions,
                "",
                "## Unresolved Risks",
                *risks,
                "",
                "## Evidence Artifact Links",
                *artifact_rows,
                "",
                "## Local Commands",
                *commands,
                "",
                "## JD Skills Demonstrated",
                *skills,
                "",
                "## Interviewer Talking Points",
                *talking_points,
                "",
            ]
        )

    def _write_files(
        self,
        narrative_id: str,
        narrative: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.narrative_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.narrative_dir / f"{narrative_id}.json"
        markdown_path = self.narrative_dir / f"{narrative_id}.md"
        json_path.write_text(json.dumps(narrative, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _parse_time(self, value: datetime | str | None) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _iso(self, value: datetime | str | None) -> str:
        parsed = self._parse_time(value)
        return parsed.isoformat() if parsed else datetime.now(timezone.utc).isoformat()
