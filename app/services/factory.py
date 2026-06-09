from pathlib import Path

from app.adapters.fake import FakeKnowledgeBaseAdapter
from app.core.config import Settings
from app.core.storage import JsonStateStore
from app.services.analytics import AnalyticsService
from app.services.approvals import ApprovalService
from app.services.api_contract import ApiContractService
from app.services.artifacts import ArtifactInventoryService
from app.services.audit import AuditService
from app.services.briefs import IncidentBriefService
from app.services.customers import CustomerHealthService
from app.services.demo import DemoService
from app.services.drills import DrillService
from app.services.final_handoff import FinalHandoffService
from app.services.git_readiness import GitReadinessService
from app.services.incident_narrative import IncidentNarrativeService
from app.services.knowledge import KnowledgeQualityService, KnowledgeRetrievalService
from app.services.launch_checklist import LaunchChecklistService
from app.services.leadership import LeadershipScorecardService
from app.services.metrics import MetricsService
from app.services.oncall_handoff import OnCallHandoffService
from app.services.ops import OpsService
from app.services.outbox import OutboxService
from app.services.playbooks import PlaybookService
from app.services.policy_guardrails import PolicyGuardrailService
from app.services.postmortem_rca import PostmortemRcaService
from app.services.portfolio import PortfolioService
from app.services.replay_lab import ReplayLabService
from app.services.release import ReleaseService
from app.services.reviewer import ReviewerService
from app.services.runbook_qa import RunbookQaService
from app.services.runtime_demo import RuntimeDemoService
from app.services.scenarios import ScenarioCatalogService
from app.services.tickets import TicketService
from app.services.trace import TraceService
from app.services.ui_verification import UIVerificationService
from app.services.workflow import AgentWorkflowService


class ServiceContainer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = JsonStateStore(settings.state_file)
        self.trace = TraceService(self.store)
        self.audit = AuditService(self.store)
        self.metrics = MetricsService(self.store)
        self.outbox = OutboxService(self.store)
        self.tickets = TicketService(self.store)
        self.knowledge = KnowledgeRetrievalService(
            FakeKnowledgeBaseAdapter(Path("sample_data/kb_articles.json")),
            self.trace,
            settings.max_tool_attempts,
        )
        self.approvals = ApprovalService(self.store)
        self.playbooks = PlaybookService(
            self.store,
            self.tickets,
            Path("sample_data/playbooks.json"),
            settings.state_file.parent / "checklists",
        )
        self.workflow = AgentWorkflowService(
            self.store,
            self.tickets,
            self.knowledge,
            self.approvals,
            self.trace,
            self.metrics,
            self.audit,
            self.outbox,
            self.playbooks,
            settings.low_confidence_threshold,
            settings.sla_high_risk_threshold,
        )
        self.drills = DrillService(
            self.store,
            self.tickets,
            self.workflow,
            self.trace,
            self.approvals,
        )
        self.briefs = IncidentBriefService(
            self.store,
            self.tickets,
            self.workflow,
            self.trace,
            settings.state_file.parent / "briefs",
        )
        self.analytics = AnalyticsService(
            self.store,
            settings.state_file.parent / "reports",
            settings.state_file.parent / "briefs",
        )
        self.ops = OpsService(
            self.store,
            settings.state_file.parent / "optimization_reports",
        )
        self.launch_checklist = LaunchChecklistService(
            settings.state_file.parent / "launch_checklists",
        )
        self.customers = CustomerHealthService(
            self.store,
            self.tickets,
            self.playbooks,
            Path("sample_data/customers.json"),
            settings.state_file.parent / "account_briefs",
        )
        self.replay_lab = ReplayLabService(
            self.store,
            self.tickets,
            self.workflow,
            self.trace,
            settings.state_file.parent / "replay_reports",
            settings.low_confidence_threshold,
        )
        self.policy_guardrails = PolicyGuardrailService(
            self.store,
            self.tickets,
            self.workflow,
            self.replay_lab,
            settings.state_file.parent / "policy_packs",
            settings.low_confidence_threshold,
        )
        self.incident_narratives = IncidentNarrativeService(
            self.store,
            self.tickets,
            self.workflow,
            self.trace,
            self.approvals,
            self.briefs,
            self.playbooks,
            self.analytics,
            self.customers,
            self.ops,
            self.replay_lab,
            self.policy_guardrails,
            self.audit,
            settings.state_file.parent / "incident_narratives",
        )
        self.demo = DemoService(
            self.tickets,
            self.workflow,
            self.trace,
            self.approvals,
            self.outbox,
            self.playbooks,
            self.drills,
            self.briefs,
            self.analytics,
            self.customers,
            self.ops,
            self.replay_lab,
            self.incident_narratives,
            self.audit,
            settings.state_file.parent / "demo_packs",
        )
        self.runbook_qa = RunbookQaService(
            self.store,
            self.tickets,
            self.workflow,
            self.trace,
            self.approvals,
            self.outbox,
            self.playbooks,
            self.drills,
            self.briefs,
            self.analytics,
            self.customers,
            self.ops,
            settings.state_file.parent / "operator_packs",
        )
        self.leadership = LeadershipScorecardService(
            self.store,
            self.tickets,
            self.workflow,
            self.metrics,
            self.analytics,
            self.customers,
            self.ops,
            self.replay_lab,
            self.policy_guardrails,
            self.runbook_qa,
            settings.state_file.parent / "leadership_reviews",
        )
        self.knowledge_quality = KnowledgeQualityService(
            self.store,
            self.tickets,
            self.audit,
            self.leadership,
            Path("sample_data/kb_articles.json"),
            settings.state_file.parent / "kb_refresh_plans",
            settings.state_file.parent / "incident_narratives",
        )
        self.portfolio = PortfolioService(
            self.store,
            settings.state_file.parent / "portfolio_packs",
        )
        self.release = ReleaseService(
            self.store,
            settings.state_file.parent / "release_packs",
        )
        self.reviewer = ReviewerService(
            self.store,
            settings.state_file.parent / "reviewer_packs",
        )
        self.artifacts = ArtifactInventoryService(settings.state_file.parent)
        self.ui_verification = UIVerificationService(
            settings.state_file.parent / "ui_verification",
        )
        self.final_handoff = FinalHandoffService(
            self.store,
            settings.state_file.parent,
        )
        self.oncall_handoff = OnCallHandoffService(
            self.store,
            self.tickets,
            self.workflow,
            self.trace,
            self.approvals,
            self.policy_guardrails,
            self.audit,
            Path("sample_data/scenarios.json"),
            settings.state_file.parent / "customer_comms_packs",
        )
        self.postmortem_rca = PostmortemRcaService(
            self.store,
            self.tickets,
            self.workflow,
            self.trace,
            self.approvals,
            self.audit,
            self.oncall_handoff,
            Path("sample_data/scenarios.json"),
            settings.state_file.parent / "rca_packs",
        )
        self.git_readiness = GitReadinessService(
            settings.state_file.parent / "git_packs",
        )
        self.api_contract = ApiContractService(
            settings.state_file.parent / "api_contracts",
        )
        self.runtime_demo = RuntimeDemoService(
            settings.state_file.parent / "runtime_packs",
        )
        self.scenarios = ScenarioCatalogService(
            self.tickets,
            self.workflow,
            self.audit,
            Path("sample_data/scenarios.json"),
            Path("data/scenario_packs"),
        )
