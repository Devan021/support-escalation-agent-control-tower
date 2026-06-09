from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TicketPriority(StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class TicketStatus(StrEnum):
    open = "open"
    analyzing = "analyzing"
    pending_approval = "pending_approval"
    escalated = "escalated"
    replied = "replied"
    human_review = "human_review"


class RunStatus(StrEnum):
    pending = "pending"
    running = "running"
    pending_approval = "awaiting_approval"
    completed = "completed"
    rejected = "rejected"
    human_review = "human_review"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class OutboxActionType(StrEnum):
    customer_reply = "customer_reply"
    engineering_escalation = "engineering_escalation"
    slack_alert = "slack_alert"
    jira_issue = "jira_issue"
    zendesk_update = "zendesk_update"


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subject: str
    body: str
    customer: str | None = None
    account: str | None = None
    customer_email: str = "customer@example.com"
    priority: TicketPriority = TicketPriority.normal
    external_id: str | None = None
    customer_tier: Literal["standard", "pro", "enterprise"] = "standard"
    tags: list[str] = Field(default_factory=list)
    sla_due_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class Ticket(TicketCreate):
    ticket_id: str = Field(default_factory=lambda: f"tkt_{uuid4().hex[:10]}")
    status: TicketStatus = TicketStatus.open

    @computed_field
    @property
    def id(self) -> str:
        return self.ticket_id


class Classification(BaseModel):
    category: str
    priority: TicketPriority
    confidence: float
    sentiment: str
    rationale: str


class SlaRisk(BaseModel):
    score: float
    level: Literal["low", "medium", "high"]
    reasons: list[str] = Field(default_factory=list)
    should_escalate: bool = False


class KnowledgeArticle(BaseModel):
    article_id: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    score: float = 0.0


class Playbook(BaseModel):
    id: str
    title: str
    category: str
    tags: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "critical"]
    checklist: list[str] = Field(default_factory=list)
    owner_roles: list[str] = Field(default_factory=list)
    escalation_policy: str
    customer_update_template: str


class PlaybookRecommendation(BaseModel):
    id: str
    title: str
    category: str
    tags: list[str] = Field(default_factory=list)
    severity: str
    match_reasons: list[str] = Field(default_factory=list)
    confidence: float
    checklist: list[str] = Field(default_factory=list)
    owner_roles: list[str] = Field(default_factory=list)
    escalation_policy: str
    customer_update_template: str


class PlaybookRecommendRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ticket_id: str | None = None
    ticket: TicketCreate | None = None
    top_n: int = Field(default=3, ge=1, le=5)


class RemediationChecklistRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    playbook_id: str | None = None


class RunbookQaRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str | None = None


class ReplayModifiers(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sla_pressure: Literal["normal", "high", "critical"] = "normal"
    kb_context: Literal["full", "missing", "conflicting"] = "full"
    adapter_health: Literal["healthy", "degraded", "failing"] = "healthy"
    confidence_override: float | None = Field(default=None, ge=0.0, le=1.0)
    approval_policy: Literal["strict", "standard", "auto_internal_only"] = "standard"


class ReplayLabRunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str | None = None
    modifiers: ReplayModifiers = Field(default_factory=ReplayModifiers)


class ReplayLabReportRequest(ReplayLabRunRequest):
    pass


class PolicySimulationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str | None = None
    modifiers: ReplayModifiers = Field(default_factory=ReplayModifiers)
    requested_actions: list[OutboxActionType] = Field(
        default_factory=lambda: [
            OutboxActionType.customer_reply,
            OutboxActionType.zendesk_update,
            OutboxActionType.jira_issue,
            OutboxActionType.slack_alert,
            OutboxActionType.engineering_escalation,
        ]
    )
    replay_risk_threshold: int = Field(default=70, ge=0, le=100)


class PolicyExportRequest(PolicySimulationRequest):
    pass


class IncidentNarrativeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str | None = None


class QaResult(BaseModel):
    confidence: float
    risky: bool = False
    requires_human_review: bool = False
    findings: list[str] = Field(default_factory=list)


class TraceEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:12]}")
    run_id: str
    trace_id: str
    ticket_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    event_type: str
    node: str | None = None
    status: str = "ok"
    message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    tokens: int = 0
    cost_usd: float = 0.0

    @computed_field
    @property
    def node_name(self) -> str | None:
        return self.node


class Approval(BaseModel):
    approval_id: str = Field(default_factory=lambda: f"apr_{uuid4().hex[:10]}")
    run_id: str
    ticket_id: str
    status: ApprovalStatus = ApprovalStatus.pending
    reason: str
    customer_reply: str = ""
    engineering_escalation: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str | None = None


class OutboxEvent(BaseModel):
    outbox_id: str = Field(default_factory=lambda: f"out_{uuid4().hex[:12]}")
    trace_id: str
    run_id: str
    ticket_id: str
    action_type: OutboxActionType
    destination: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "dispatched"
    created_at: datetime = Field(default_factory=utc_now)

    @computed_field
    @property
    def id(self) -> str:
        return self.outbox_id


class RunRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:10]}")
    ticket_id: str
    trace_id: str = Field(default_factory=lambda: f"trc_{uuid4().hex[:12]}")
    status: RunStatus = RunStatus.pending
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    final_action: str = ""
    failure_state: dict[str, Any] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def id(self) -> str:
        return self.run_id


class AuditEvent(BaseModel):
    audit_id: str = Field(default_factory=lambda: f"aud_{uuid4().hex[:12]}")
    timestamp: datetime = Field(default_factory=utc_now)
    actor: str
    action: str
    resource_type: str
    resource_id: str
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")
    decided_by: str = "demo-human"
    note: str | None = None
    reviewer: str | None = None
    reviewer_notes: str | None = None

    def actor(self) -> str:
        return self.reviewer or self.decided_by

    def decision_note(self) -> str | None:
        return self.reviewer_notes or self.note


class AgentWorkflowState(TypedDict, total=False):
    run_id: str
    ticket_id: str
    trace_id: str
    ticket: dict[str, Any]
    classification: dict[str, Any]
    sla_risk: dict[str, Any]
    kb_results: list[dict[str, Any]]
    playbook_recommendations: list[dict[str, Any]]
    drafts: dict[str, str]
    qa: dict[str, Any]
    approval_id: str | None
    approval_status: str
    approval_decision: str | None
    final_action: str
    failure_state: dict[str, Any] | None
    node_history: list[str]
    tool_calls: list[dict[str, Any]]
    metrics: dict[str, Any]
