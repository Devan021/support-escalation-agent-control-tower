from datetime import datetime, timezone

from app.core.storage import JsonStateStore
from app.models import TicketCreate
from app.services.approvals import ApprovalService
from app.services.tickets import TicketService
from app.services.trace import TraceService
from app.services.workflow import AgentWorkflowService


class DrillService:
    def __init__(
        self,
        store: JsonStateStore,
        ticket_service: TicketService,
        workflow_service: AgentWorkflowService,
        trace_service: TraceService,
        approval_service: ApprovalService,
    ):
        self.store = store
        self.ticket_service = ticket_service
        self.workflow_service = workflow_service
        self.trace_service = trace_service
        self.approval_service = approval_service

    async def sla_breach_simulation(self) -> dict:
        samples = [
            {
                "external_id": "sla-sim-enterprise-breached",
                "minutes_to_sla": -12,
                "subject": "SLA simulator: enterprise production login outage",
                "body": "Production outage blocks all agents from SAML SSO. SLA breach is active.",
                "customer": "Northstar Health",
                "priority": "urgent",
                "customer_tier": "enterprise",
                "tags": ["drill", "sla", "outage", "sso"],
            },
            {
                "external_id": "sla-sim-pro-critical",
                "minutes_to_sla": 8,
                "subject": "SLA simulator: pro webhook 500 regression",
                "body": "Webhook delivery returns 500 for checkout events and production is blocked.",
                "customer": "BrightWorks Studio",
                "priority": "urgent",
                "customer_tier": "pro",
                "tags": ["drill", "sla", "webhook", "5xx"],
            },
            {
                "external_id": "sla-sim-enterprise-warning",
                "minutes_to_sla": 45,
                "subject": "SLA simulator: enterprise API latency escalation",
                "body": "Enterprise API latency is delaying batch jobs and customer reports SLA risk.",
                "customer": "Atlas Logistics",
                "priority": "high",
                "customer_tier": "enterprise",
                "tags": ["drill", "sla", "api"],
            },
            {
                "external_id": "sla-sim-standard-watch",
                "minutes_to_sla": 95,
                "subject": "SLA simulator: standard billing clarification",
                "body": "Customer needs invoice clarification before their internal deadline.",
                "customer": "Cobalt Retail",
                "priority": "normal",
                "customer_tier": "standard",
                "tags": ["drill", "billing"],
            },
        ]

        queue = []
        for sample in samples:
            minutes_to_sla = sample["minutes_to_sla"]
            ticket = await self.ticket_service.get_by_external_id(sample["external_id"])
            if ticket is None:
                ticket = await self.ticket_service.ingest(
                    TicketCreate(
                        external_id=sample["external_id"],
                        subject=sample["subject"],
                        body=sample["body"],
                        customer=sample["customer"],
                        priority=sample["priority"],
                        customer_tier=sample["customer_tier"],
                        tags=sample["tags"],
                    )
                )
            run = await self.workflow_service.analyze_ticket(ticket.ticket_id)
            approvals = await self.approval_service.list_pending()
            approval = next((item for item in approvals if item.run_id == run.run_id), None)
            risk_level = self._risk_level(minutes_to_sla, ticket.customer_tier)
            item = {
                "ticket_id": ticket.ticket_id,
                "customer_tier": ticket.customer_tier,
                "minutes_to_sla": minutes_to_sla,
                "risk_level": risk_level,
                "recommended_action": self._recommended_action(risk_level, ticket.customer_tier),
                "run_id": run.run_id,
                "approval_id": approval.approval_id if approval else None,
            }
            queue.append(item)

        risk_rank = {"breached": 0, "critical": 1, "warning": 2, "watch": 3}
        queue = sorted(
            queue,
            key=lambda item: (risk_rank[item["risk_level"]], item["minutes_to_sla"]),
        )
        drill = {
            "drill_type": "sla_breach_simulation",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ticket_count": len(queue),
            "queue": queue,
        }

        def mutate(state):
            state["drills"][f"sla_breach_simulation:{drill['created_at']}"] = drill

        await self.store.update(mutate)
        return {"drill": drill, "queue": queue}

    async def tool_failure(self) -> dict:
        ticket = await self.ticket_service.ingest(
            TicketCreate(
                subject="Failure drill: unclear export delay",
                body=(
                    "force-kb-failure ??? Export status is unclear and the customer needs a "
                    "safe next step without unsupported claims."
                ),
                customer="Evergreen Bank",
                priority="normal",
                customer_tier="enterprise",
                tags=["drill", "reliability", "kb"],
            )
        )
        run = await self.workflow_service.analyze_ticket(ticket.ticket_id)
        trace = await self.trace_service.list_events(run.run_id)
        approvals = await self.approval_service.list_pending()
        approval = next((item for item in approvals if item.run_id == run.run_id), None)
        tool_failures = [
            event
            for event in trace
            if event.event_type == "tool_call" and event.status == "error"
        ]

        drill = {
            "drill_type": "tool_failure",
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "ticket_id": ticket.ticket_id,
            "failure_count": len(tool_failures),
            "final_status": run.status,
            "approval_id": approval.approval_id if approval else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        def mutate(state):
            state["drills"][run.run_id] = drill

        await self.store.update(mutate)
        run.state["drill_type"] = "tool_failure"
        return {
            "drill": drill,
            "ticket": ticket,
            "run": run,
            "approval": approval,
            "trace": trace,
            "failure_timeline": tool_failures,
        }

    def _risk_level(self, minutes_to_sla: int, customer_tier: str) -> str:
        if minutes_to_sla < 0:
            return "breached"
        if minutes_to_sla <= 15 or (customer_tier == "enterprise" and minutes_to_sla <= 30):
            return "critical"
        if minutes_to_sla <= 60:
            return "warning"
        return "watch"

    def _recommended_action(self, risk_level: str, customer_tier: str) -> str:
        if risk_level == "breached":
            return "Page support lead, approve customer update, and open engineering incident now."
        if risk_level == "critical":
            return "Prioritize lead approval and prepare engineering handoff before SLA breach."
        if risk_level == "warning" and customer_tier == "enterprise":
            return "Assign senior owner and confirm mitigation plan with engineering."
        if risk_level == "warning":
            return "Move ahead of normal queue and send proactive customer update."
        return "Monitor in queue and continue standard support workflow."
