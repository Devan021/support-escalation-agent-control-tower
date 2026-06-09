import time
from datetime import datetime, timezone
from typing import Any, Callable

try:
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:
    END = "__end__"
    START = "__start__"
    StateGraph = None
    LANGGRAPH_AVAILABLE = False

from app.adapters.fake import FakeJiraAdapter, FakeSlackAdapter, FakeZendeskAdapter, LocalMockLlmProvider
from app.core.storage import JsonStateStore
from app.models import (
    AgentWorkflowState,
    ApprovalStatus,
    AuditEvent,
    Classification,
    KnowledgeArticle,
    OutboxActionType,
    QaResult,
    RunRecord,
    RunStatus,
    SlaRisk,
    Ticket,
    TicketPriority,
    TicketStatus,
    TraceEvent,
)
from app.services.approvals import ApprovalService
from app.services.audit import AuditService
from app.services.knowledge import KnowledgeRetrievalService
from app.services.metrics import MetricsService
from app.services.outbox import OutboxService
from app.services.playbooks import PlaybookService
from app.services.tickets import TicketService
from app.services.trace import TraceService

REQUIRED_WORKFLOW_NODES = [
    "intake_classifier",
    "sla_risk_scorer",
    "playbook_recommender",
    "knowledge_retriever",
    "customer_reply_drafter",
    "engineering_escalation_drafter",
    "qa_evaluator",
    "human_approval",
    "finalizer",
]


class AgentWorkflowService:
    def __init__(
        self,
        store: JsonStateStore,
        ticket_service: TicketService,
        knowledge_service: KnowledgeRetrievalService,
        approval_service: ApprovalService,
        trace_service: TraceService,
        metrics_service: MetricsService,
        audit_service: AuditService,
        outbox_service: OutboxService,
        playbook_service: PlaybookService,
        low_confidence_threshold: float,
        sla_high_risk_threshold: float,
    ):
        self.store = store
        self.ticket_service = ticket_service
        self.knowledge_service = knowledge_service
        self.approval_service = approval_service
        self.trace_service = trace_service
        self.metrics_service = metrics_service
        self.audit_service = audit_service
        self.outbox_service = outbox_service
        self.playbook_service = playbook_service
        self.low_confidence_threshold = low_confidence_threshold
        self.sla_high_risk_threshold = sla_high_risk_threshold
        self.llm = LocalMockLlmProvider()
        self.zendesk = FakeZendeskAdapter()
        self.jira = FakeJiraAdapter()
        self.slack = FakeSlackAdapter()
        self.graph = self._build_graph()

    def _build_graph(self):
        if not LANGGRAPH_AVAILABLE:
            return _SequentialGraph([getattr(self, node) for node in REQUIRED_WORKFLOW_NODES])
        graph = StateGraph(AgentWorkflowState)
        for node in REQUIRED_WORKFLOW_NODES:
            graph.add_node(node, getattr(self, node))
        graph.add_edge(START, "intake_classifier")
        for left, right in zip(REQUIRED_WORKFLOW_NODES, REQUIRED_WORKFLOW_NODES[1:]):
            graph.add_edge(left, right)
        graph.add_edge("finalizer", END)
        return graph.compile()

    async def analyze_ticket(self, ticket_id: str) -> RunRecord:
        ticket = await self.ticket_service.get(ticket_id)
        if not ticket:
            raise KeyError(ticket_id)
        await self.ticket_service.update_status(ticket_id, TicketStatus.analyzing)
        run = RunRecord(ticket_id=ticket_id, status=RunStatus.running)
        state: AgentWorkflowState = {"run_id": run.run_id, "ticket_id": ticket_id, "trace_id": run.trace_id, "ticket": ticket.model_dump(mode="json"), "approval_decision": None, "node_history": [], "tool_calls": [], "metrics": {}, "failure_state": None}
        await self._save_run(run, state)
        await self.audit_service.record(AuditEvent(actor="system", action="run.started", resource_type="run", resource_id=run.run_id, trace_id=run.trace_id))
        final_state = await self.graph.ainvoke(state)
        return await self._persist(final_state)

    async def approve(self, run_id: str, decided_by: str, note: str | None) -> RunRecord:
        if not await self.approval_service.decide(run_id, ApprovalStatus.approved, decided_by, note):
            raise KeyError(run_id)
        run = await self.get_run(run_id)
        state = run.state
        state["approval_status"] = "approved"
        state["approval_decision"] = "approved"
        state = await self.finalizer(state)
        await self.audit_service.record(AuditEvent(actor=decided_by, action="approval.approved", resource_type="run", resource_id=run_id, trace_id=run.trace_id))
        return await self._persist(state)

    async def reject(self, run_id: str, decided_by: str, note: str | None) -> RunRecord:
        if not await self.approval_service.decide(run_id, ApprovalStatus.rejected, decided_by, note):
            raise KeyError(run_id)
        run = await self.get_run(run_id)
        state = run.state
        state["approval_status"] = "rejected"
        state["approval_decision"] = "rejected"
        state = await self.finalizer(state)
        await self.audit_service.record(AuditEvent(actor=decided_by, action="approval.rejected", resource_type="run", resource_id=run_id, trace_id=run.trace_id))
        return await self._persist(state)

    async def get_run(self, run_id: str) -> RunRecord:
        state = await self.store.load()
        if run_id not in state["runs"]:
            raise KeyError(run_id)
        return RunRecord(**state["runs"][run_id])

    async def _save_run(self, run: RunRecord, workflow_state: dict[str, Any]) -> None:
        run.state = workflow_state

        def mutate(state):
            state["runs"][run.run_id] = run.model_dump(mode="json")

        await self.store.update(mutate)

    async def _persist(self, workflow_state: dict[str, Any]) -> RunRecord:
        final_action = workflow_state.get("final_action", "")
        status = RunStatus.pending_approval if final_action == "awaiting_human_approval" else RunStatus.rejected if final_action == "rejected_by_human" else RunStatus.completed
        ticket_status = TicketStatus.pending_approval if status == RunStatus.pending_approval else TicketStatus.human_review if status == RunStatus.rejected else TicketStatus.escalated if "engineering" in final_action else TicketStatus.replied
        completed_at = None if status == RunStatus.pending_approval else datetime.now(timezone.utc).isoformat()

        def mutate(state):
            raw = state["runs"].get(
                workflow_state["run_id"],
                RunRecord(
                    run_id=workflow_state["run_id"],
                    ticket_id=workflow_state["ticket_id"],
                    trace_id=workflow_state["trace_id"],
                ).model_dump(mode="json"),
            )
            raw.update({"status": status, "state": workflow_state, "final_action": final_action, "failure_state": workflow_state.get("failure_state"), "completed_at": completed_at})
            state["runs"][workflow_state["run_id"]] = raw
            return RunRecord(**raw)

        run = await self.store.update(mutate)
        await self.ticket_service.update_status(run.ticket_id, ticket_status)
        return run

    async def _node(self, state: AgentWorkflowState, node: str, fn: Callable[[], Any]) -> AgentWorkflowState:
        start = time.perf_counter()
        state.setdefault("node_history", []).append(node)
        async with self.trace_service.node_span(state["run_id"], state["trace_id"], state["ticket_id"], node):
            state = await fn()
        await self.metrics_service.record_node_metrics(node, (time.perf_counter() - start) * 1000)
        return state

    async def intake_classifier(self, state: AgentWorkflowState) -> AgentWorkflowState:
        async def work():
            ticket = Ticket(**state["ticket"])
            text = f"{ticket.subject} {ticket.body}".lower()
            if "api key" in text and any(word in text for word in ["rotate", "rotation"]):
                category = "how_to"
                best = 3
            elif any(word in text for word in ["webhook", "500", "5xx", "regression"]):
                category = "bug"
                best = 3
            elif any(word in text for word in ["cannot login", "login loop"]) and any(
                word in text for word in ["all", "production", "blocked"]
            ):
                category = "incident"
                best = 3
            else:
                mapping = {"authentication": ["sso", "login", "oauth", "saml", "auth"], "billing": ["invoice", "billing", "refund"], "api_integrations": ["api", "webhook", "5xx", "latency"], "security_privacy": ["privacy", "deletion", "export", "compliance"], "incident": ["outage", "down", "breach", "production", "blocked"]}
                scores = {cat: sum(1 for word in words if word in text) for cat, words in mapping.items()}
                category = max(scores, key=scores.get)
                best = scores[category]
                if best == 0:
                    category = "general_support"
            confidence = min(0.95, 0.45 + best * 0.16 + len(ticket.tags) * 0.04)
            if len(ticket.body.split()) < 8 or "???" in text:
                confidence = min(confidence, 0.45)
            priority = TicketPriority.urgent if any(w in text for w in ["outage", "breach", "production down"]) else ticket.priority
            state["classification"] = Classification(category=category, priority=priority, confidence=round(confidence, 2), sentiment="negative" if "outage" in text or "blocked" in text else "neutral", rationale=f"Matched {best} signal keywords.").model_dump(mode="json")
            return state

        return await self._node(state, "intake_classifier", work)

    async def sla_risk_scorer(self, state: AgentWorkflowState) -> AgentWorkflowState:
        async def work():
            ticket = Ticket(**state["ticket"])
            text = f"{ticket.subject} {ticket.body}".lower()
            score = 0.15
            reasons = []
            if ticket.priority == "urgent" or state["classification"]["priority"] == "urgent":
                score += 0.35
                reasons.append("urgent priority")
            if ticket.customer_tier == "enterprise":
                score += 0.2
                reasons.append("enterprise customer")
            for word, weight in {"outage": 0.18, "sla": 0.14, "blocked": 0.12, "production": 0.12, "breach": 0.12, "5xx": 0.08}.items():
                if word in text:
                    score += weight
                    reasons.append(word)
            score = min(score, 0.99)
            state["sla_risk"] = SlaRisk(score=round(score, 2), level="high" if score >= self.sla_high_risk_threshold else "medium" if score >= 0.45 else "low", reasons=reasons, should_escalate=score >= self.sla_high_risk_threshold).model_dump(mode="json")
            return state

        return await self._node(state, "sla_risk_scorer", work)

    async def knowledge_retriever(self, state: AgentWorkflowState) -> AgentWorkflowState:
        async def work():
            ticket = Ticket(**state["ticket"])
            results, calls, failure = await self.knowledge_service.search_with_retries(state["run_id"], state["trace_id"], state["ticket_id"], f"{ticket.subject} {ticket.body}", ticket.tags + [state["classification"]["category"]])
            state["kb_results"] = [r.model_dump(mode="json") for r in results]
            state.setdefault("tool_calls", []).extend(calls)
            if failure:
                state["failure_state"] = failure
            return state

        return await self._node(state, "knowledge_retriever", work)

    async def playbook_recommender(self, state: AgentWorkflowState) -> AgentWorkflowState:
        async def work():
            ticket = Ticket(**state["ticket"])
            recommendations = self.playbook_service.recommend_for_ticket(ticket, state, top_n=3)
            state["playbook_recommendations"] = [
                recommendation.model_dump(mode="json") for recommendation in recommendations
            ]
            return state

        return await self._node(state, "playbook_recommender", work)

    async def customer_reply_drafter(self, state: AgentWorkflowState) -> AgentWorkflowState:
        async def work():
            ticket = Ticket(**state["ticket"])
            draft = await self.llm.draft_customer_reply(ticket, [KnowledgeArticle(**i) for i in state.get("kb_results", [])])
            state.setdefault("drafts", {})["customer_reply"] = draft["text"]
            await self.metrics_service.record_node_metrics("customer_reply_drafter", 0, draft["tokens"], draft["cost_usd"])
            return state

        return await self._node(state, "customer_reply_drafter", work)

    async def engineering_escalation_drafter(self, state: AgentWorkflowState) -> AgentWorkflowState:
        async def work():
            ticket = Ticket(**state["ticket"])
            should = state["sla_risk"]["should_escalate"] or state["classification"]["category"] in {"api_integrations", "incident", "authentication", "bug"}
            if should:
                draft = await self.llm.draft_engineering_escalation(ticket, state["classification"], state["sla_risk"], [KnowledgeArticle(**i) for i in state.get("kb_results", [])])
                state.setdefault("drafts", {})["engineering_escalation"] = draft["text"]
                await self.metrics_service.record_node_metrics("engineering_escalation_drafter", 0, draft["tokens"], draft["cost_usd"])
            else:
                state.setdefault("drafts", {})["engineering_escalation"] = ""
            return state

        return await self._node(state, "engineering_escalation_drafter", work)

    async def qa_evaluator(self, state: AgentWorkflowState) -> AgentWorkflowState:
        async def work():
            findings = []
            confidence = min(float(state["classification"]["confidence"]), 0.9 if state.get("kb_results") else 0.5)
            risky = state["sla_risk"]["level"] == "high" or bool(state.get("failure_state"))
            if state.get("failure_state"):
                findings.append("Knowledge retrieval failed after retries.")
                confidence = min(confidence, 0.4)
            if confidence < self.low_confidence_threshold:
                findings.append("Low classification or retrieval confidence.")
            if state["sla_risk"]["level"] == "high":
                findings.append("High SLA risk requires lead approval.")
            state["qa"] = QaResult(confidence=round(confidence, 2), risky=risky, requires_human_review=risky or confidence < self.low_confidence_threshold, findings=findings).model_dump(mode="json")
            return state

        return await self._node(state, "qa_evaluator", work)

    async def human_approval(self, state: AgentWorkflowState) -> AgentWorkflowState:
        async def work():
            drafts = state.get("drafts", {})
            reason = "Customer replies and engineering tickets require approval before dispatch. " + " ".join(state.get("qa", {}).get("findings", []))
            approval = await self.approval_service.create_or_get_pending(state["run_id"], state["ticket_id"], reason, drafts.get("customer_reply", ""), drafts.get("engineering_escalation", ""))
            state["approval_id"] = approval.approval_id
            state["approval_status"] = approval.status
            return state

        return await self._node(state, "human_approval", work)

    async def finalizer(self, state: AgentWorkflowState) -> AgentWorkflowState:
        async def work():
            ticket = Ticket(**state["ticket"])
            drafts = state.get("drafts", {})
            if state.get("approval_decision") is None:
                state["final_action"] = "awaiting_human_approval"
                return state
            if state.get("approval_decision") == "rejected":
                state["final_action"] = "rejected_by_human"
                return state
            actions = []
            if drafts.get("customer_reply"):
                zendesk_payload = {
                    "ticket_id": ticket.ticket_id,
                    "status": "pending_customer_update_sent",
                    "comment": drafts["customer_reply"],
                }
                await self.outbox_service.record_dispatch(
                    trace_id=state["trace_id"],
                    run_id=state["run_id"],
                    ticket_id=ticket.ticket_id,
                    action_type=OutboxActionType.customer_reply,
                    destination=f"zendesk.ticket.{ticket.ticket_id}.comment",
                    payload=zendesk_payload,
                )
                zendesk_result = await self.zendesk.update_ticket(
                    ticket.ticket_id,
                    "pending_customer_update_sent",
                    drafts["customer_reply"],
                )
                await self.outbox_service.record_dispatch(
                    trace_id=state["trace_id"],
                    run_id=state["run_id"],
                    ticket_id=ticket.ticket_id,
                    action_type=OutboxActionType.zendesk_update,
                    destination=f"zendesk.ticket.{ticket.ticket_id}",
                    payload=zendesk_result,
                )
                await self.trace_service.add_event(
                    TraceEvent(
                        run_id=state["run_id"],
                        trace_id=state["trace_id"],
                        ticket_id=ticket.ticket_id,
                        event_type="outbox_dispatch",
                        node="finalizer",
                        message="Recorded customer reply and Zendesk update in outbox",
                        metadata={"action_types": ["customer_reply", "zendesk_update"]},
                    )
                )
                actions.append("customer_reply_sent")
            if drafts.get("engineering_escalation"):
                jira_payload = {
                    "title": f"SLA risk escalation: {ticket.subject}",
                    "body": drafts["engineering_escalation"],
                    "labels": ["support-escalation", state["classification"]["category"]],
                }
                await self.outbox_service.record_dispatch(
                    trace_id=state["trace_id"],
                    run_id=state["run_id"],
                    ticket_id=ticket.ticket_id,
                    action_type=OutboxActionType.engineering_escalation,
                    destination="jira.project.ESC.escalation",
                    payload=jira_payload,
                )
                issue = await self.jira.create_issue(
                    jira_payload["title"],
                    jira_payload["body"],
                    jira_payload["labels"],
                )
                await self.outbox_service.record_dispatch(
                    trace_id=state["trace_id"],
                    run_id=state["run_id"],
                    ticket_id=ticket.ticket_id,
                    action_type=OutboxActionType.jira_issue,
                    destination=f"jira.issue.{issue['issue_key']}",
                    payload=issue,
                )
                slack_payload = {
                    "channel": "#support-escalations",
                    "text": f"{issue['issue_key']} created for {ticket.ticket_id}",
                }
                slack_result = await self.slack.post_message(
                    slack_payload["channel"],
                    slack_payload["text"],
                )
                await self.outbox_service.record_dispatch(
                    trace_id=state["trace_id"],
                    run_id=state["run_id"],
                    ticket_id=ticket.ticket_id,
                    action_type=OutboxActionType.slack_alert,
                    destination="slack.channel.#support-escalations",
                    payload=slack_result,
                )
                await self.trace_service.add_event(
                    TraceEvent(
                        run_id=state["run_id"],
                        trace_id=state["trace_id"],
                        ticket_id=ticket.ticket_id,
                        event_type="outbox_dispatch",
                        node="finalizer",
                        message="Recorded Jira escalation and Slack alert in outbox",
                        metadata={"action_types": ["engineering_escalation", "jira_issue", "slack_alert"]},
                    )
                )
                actions.append("engineering_ticket_created")
            state["final_action"] = "+".join(actions) or "approved_no_external_action"
            return state

        return await self._node(state, "finalizer", work)


class _SequentialGraph:
    def __init__(self, nodes):
        self.nodes = nodes

    async def ainvoke(self, state):
        for node in self.nodes:
            state = await node(state)
        return state
