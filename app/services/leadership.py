import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore
from app.models import PolicySimulationRequest, ReplayModifiers, RunRecord
from app.services.analytics import AnalyticsService
from app.services.customers import CustomerHealthService
from app.services.metrics import MetricsService
from app.services.ops import OpsService
from app.services.policy_guardrails import PolicyGuardrailService
from app.services.replay_lab import ReplayLabService
from app.services.runbook_qa import JD_SKILLS_DEMONSTRATED, RunbookQaService
from app.services.tickets import TicketService
from app.services.workflow import AgentWorkflowService


LOCAL_COMMANDS = [
    r".\.venv\Scripts\python.exe -m pytest -q",
    r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
    r".\.venv\Scripts\python.exe -m app.evals.run_eval",
    r".\.venv\Scripts\python.exe scripts\demo_run.py",
    (
        r'rg "leadership/scorecard|leadership/review-pack|Leadership Scorecard|'
        r'leadership_reviews|automation KPI" app dashboard docs README.md tests scripts'
    ),
]


KPI_DEFINITIONS = {
    "automation_safety": "Scores whether automation stays gated by QA, policy, replay, and trace evidence.",
    "approval_health": "Tracks approval completion, queue pressure, and pending approval risk.",
    "sla_risk": "Measures local SLA exposure across analyzed tickets and SLO budget posture.",
    "escalation_quality": "Checks whether high-risk tickets produce playbooks, engineering handoffs, and evidence.",
    "retry_failure_behavior": "Summarizes retry exhaustion, tool errors, and failure drill behavior.",
    "policy_blocks": "Shows whether policy guardrails block risky customer-visible or internal actions.",
    "replay_risk": "Uses deterministic counterfactual replay to quantify automation-change risk.",
    "customer_impact": "Connects customer health, outbox follow-through, and incident impact posture.",
    "operator_readiness": "Reports whether the operator handoff has the required sections and artifacts.",
}


class LeadershipScorecardService:
    def __init__(
        self,
        store: JsonStateStore,
        tickets: TicketService,
        workflow: AgentWorkflowService,
        metrics: MetricsService,
        analytics: AnalyticsService,
        customers: CustomerHealthService,
        ops: OpsService,
        replay_lab: ReplayLabService,
        policy_guardrails: PolicyGuardrailService,
        runbook_qa: RunbookQaService,
        leadership_reviews_dir: Path,
    ):
        self.store = store
        self.tickets = tickets
        self.workflow = workflow
        self.metrics = metrics
        self.analytics = analytics
        self.customers = customers
        self.ops = ops
        self.replay_lab = replay_lab
        self.policy_guardrails = policy_guardrails
        self.runbook_qa = runbook_qa
        self.leadership_reviews_dir = leadership_reviews_dir

    async def scorecard(self) -> dict[str, Any]:
        await self.tickets.list()
        state = await self.store.load()
        latest_run = self._latest_run(state)
        readiness_run = self._readiness_run(state) or latest_run
        ops_snapshot = await self.analytics.ops_snapshot()
        agent_metrics = await self.metrics.agent_performance()
        slo_budget = await self.ops.slo_budget()
        customer_health = await self.customers.health()
        replay = await self._replay_summary(latest_run)
        policy = await self._policy_summary(latest_run)
        readiness = await self._readiness_summary(readiness_run)
        artifact_links = self._artifact_links()

        categories = {
            "automation_safety": self._automation_safety(
                state,
                agent_metrics,
                replay,
                policy,
            ),
            "approval_health": self._approval_health(state),
            "sla_risk": self._sla_risk(state, ops_snapshot, slo_budget),
            "escalation_quality": self._escalation_quality(state, ops_snapshot),
            "retry_failure_behavior": self._retry_failure_behavior(agent_metrics),
            "policy_blocks": self._policy_blocks(policy),
            "replay_risk": self._replay_risk(replay),
            "customer_impact": self._customer_impact(customer_health, ops_snapshot),
            "operator_readiness": self._operator_readiness(readiness),
        }
        overall_score = round(sum(item["score"] for item in categories.values()) / len(categories))
        risk_flags = self._overall_risk_flags(categories)
        recommended_actions = self._recommended_actions(categories, risk_flags)
        readiness_status = self._readiness_status(overall_score, risk_flags, readiness)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "local-deterministic-automation-kpi-scorecard",
            "overall_score": overall_score,
            "readiness_status": readiness_status,
            "sample_window": {
                "ticket_count": len(state["tickets"]),
                "run_count": len(state["runs"]),
                "trace_count": len(state["traces"]),
                "approval_count": len(state["approvals"]),
                "outbox_dispatch_count": len(state["outbox"]),
                "drill_count": len(state["drills"]),
            },
            "kpi_categories": categories,
            "trendish_local_values": self._trendish_values(
                state,
                ops_snapshot,
                agent_metrics,
                slo_budget,
                replay,
                policy,
                readiness,
            ),
            "risk_flags": risk_flags,
            "recommended_actions": recommended_actions,
            "artifact_links": artifact_links,
            "readiness": readiness,
            "kpi_definitions": KPI_DEFINITIONS,
            "local_commands": LOCAL_COMMANDS,
        }

    async def export_review_pack(self) -> dict[str, Any]:
        scorecard = await self.scorecard()
        generated_at = datetime.now(timezone.utc)
        review_id = f"leadership_review_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        review = {
            "review_id": review_id,
            "generated_at": generated_at.isoformat(),
            "scorecard": scorecard,
            "kpi_definitions": KPI_DEFINITIONS,
            "local_evidence_links": scorecard["artifact_links"],
            "top_risks": scorecard["risk_flags"][:8],
            "recommended_next_actions": scorecard["recommended_actions"],
            "local_commands": LOCAL_COMMANDS,
            "jd_skills_demonstrated": self._jd_skills(),
            "interviewer_talking_points": self._talking_points(scorecard),
        }
        markdown = self._markdown(review)
        json_path, markdown_path = self._write_pack(review_id, review, markdown)
        review["artifact_paths"] = {
            "leadership_review_json": str(json_path),
            "leadership_review_markdown": str(markdown_path),
        }
        json_path.write_text(json.dumps(review, indent=2, default=str), encoding="utf-8")
        return {
            "review_id": review_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "readiness_status": scorecard["readiness_status"],
            "overall_score": scorecard["overall_score"],
            "review": review,
            "markdown": markdown,
        }

    def _latest_run(self, state: dict[str, Any]) -> RunRecord | None:
        runs = list(state["runs"].values())
        if not runs:
            return None
        return RunRecord(**sorted(runs, key=lambda item: item.get("started_at", ""))[-1])

    def _readiness_run(self, state: dict[str, Any]) -> RunRecord | None:
        tickets = state["tickets"]
        runs = sorted(
            state["runs"].values(),
            key=lambda item: item.get("started_at", ""),
            reverse=True,
        )
        for run in runs:
            ticket = tickets.get(run.get("ticket_id"), {})
            has_customer_context = bool(ticket.get("customer") or ticket.get("account"))
            if run.get("status") == "completed" and has_customer_context:
                return RunRecord(**run)
        for run in runs:
            if run.get("status") == "completed":
                return RunRecord(**run)
        return None

    async def _replay_summary(self, run: RunRecord | None) -> dict[str, Any]:
        if run is None:
            return {
                "risk_score": 0,
                "risk_flags": [],
                "changed_decisions": [],
                "recommended_operator_action": "Run the demo scenario to generate replay evidence.",
            }
        replay = await self.replay_lab.replay(
            run.run_id,
            ReplayModifiers(
                sla_pressure="critical",
                kb_context="conflicting",
                adapter_health="degraded",
                confidence_override=0.48,
                approval_policy="strict",
            ),
        )
        comparison = replay["comparison"]
        return {
            "risk_score": comparison["risk_score"],
            "risk_flags": comparison["risk_flags"],
            "changed_decisions": comparison["changed_decisions"],
            "recommended_operator_action": comparison["recommended_operator_action"],
        }

    async def _policy_summary(self, run: RunRecord | None) -> dict[str, Any]:
        if run is None:
            return {
                "policy_decision": "not_evaluated",
                "required_approval_type": "none",
                "blocked_actions": [],
                "matched_rules": [],
                "warnings": ["Run a local scenario to generate policy evidence."],
                "recommended_operator_action": "Generate local workflow evidence before policy review.",
            }
        simulation = await self.policy_guardrails.simulate(
            PolicySimulationRequest(
                run_id=run.run_id,
                modifiers=ReplayModifiers(
                    sla_pressure="critical",
                    kb_context="conflicting",
                    adapter_health="degraded",
                    confidence_override=0.48,
                    approval_policy="strict",
                ),
                replay_risk_threshold=70,
            )
        )
        return {
            "policy_decision": simulation["policy_decision"],
            "required_approval_type": simulation["required_approval_type"],
            "blocked_actions": simulation["blocked_actions"],
            "matched_rules": simulation["matched_rules"],
            "warnings": simulation["warnings"],
            "recommended_operator_action": simulation["recommended_operator_action"],
        }

    async def _readiness_summary(self, run: RunRecord | None) -> dict[str, Any]:
        if run is None:
            return {
                "status": "not_evaluated",
                "score": 0,
                "missing_sections": ["run_evidence"],
                "warnings": ["No workflow run is available for operator readiness."],
                "linked_artifact_paths": {},
                "recommended_fixes": ["Run the demo scenario or analyze a sample ticket."],
            }
        try:
            return await self.runbook_qa.evaluate(run.run_id)
        except KeyError:
            return {
                "status": "fail",
                "score": 0,
                "run_id": run.run_id,
                "missing_sections": ["customer_account_health"],
                "warnings": ["Operator readiness artifacts could not resolve customer account context."],
                "linked_artifact_paths": {},
                "recommended_fixes": [
                    "Run the demo scenario or use a run whose ticket has customer/account metadata."
                ],
            }

    def _automation_safety(
        self,
        state: dict[str, Any],
        agent_metrics: dict[str, Any],
        replay: dict[str, Any],
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        run_count = max(1, len(state["runs"]))
        completed = agent_metrics["completed_runs"]
        pending = agent_metrics["pending_approval_runs"]
        failures = agent_metrics["failure_count"]
        replay_penalty = min(25, replay["risk_score"] // 4)
        policy_penalty = 20 if policy["policy_decision"] == "blocked_pending_remediation" else 0
        score = self._clamp(
            100
            - round((failures / run_count) * 30)
            - round((pending / run_count) * 15)
            - replay_penalty
            - policy_penalty
        )
        flags = []
        if failures:
            flags.append("workflow_failures_present")
        if pending:
            flags.append("automation_waiting_on_approval")
        if policy_penalty:
            flags.append("policy_block_prevents_automation")
        return self._category(
            score,
            {
                "completed_runs": completed,
                "pending_approval_runs": pending,
                "failure_count": failures,
                "replay_risk_score": replay["risk_score"],
                "policy_decision": policy["policy_decision"],
            },
            flags,
            [
                "Keep customer-visible dispatch gated by approval and policy simulation.",
                "Review replay and policy blocks before expanding automation scope.",
            ],
        )

    def _approval_health(self, state: dict[str, Any]) -> dict[str, Any]:
        approvals = list(state["approvals"].values())
        counts = Counter(item.get("status", "unknown") for item in approvals)
        total = len(approvals)
        decided = counts.get("approved", 0) + counts.get("rejected", 0)
        pending = counts.get("pending", 0)
        approval_rate = round((counts.get("approved", 0) / total) * 100, 2) if total else 100.0
        score = self._clamp(round((decided / total) * 100) if total else 90, pending * 8)
        flags = ["pending_approvals"] if pending else []
        return self._category(
            score,
            {
                "approval_count": total,
                "approved": counts.get("approved", 0),
                "rejected": counts.get("rejected", 0),
                "pending": pending,
                "approval_rate_percent": approval_rate,
            },
            flags,
            ["Clear oldest pending approvals and assign explicit support-lead ownership."],
        )

    def _sla_risk(
        self,
        state: dict[str, Any],
        ops_snapshot: dict[str, Any],
        slo_budget: dict[str, Any],
    ) -> dict[str, Any]:
        runs = list(state["runs"].values())
        high = ops_snapshot["counts"]["sla_risk"].get("high", 0)
        medium = ops_snapshot["counts"]["sla_risk"].get("medium", 0)
        score = self._clamp(100 - high * 12 - medium * 5 - (20 if slo_budget["overall_status"] == "fail" else 0))
        flags = []
        if high:
            flags.append("high_sla_risk_tickets")
        if slo_budget["overall_status"] in {"warn", "fail"}:
            flags.append(f"slo_{slo_budget['overall_status']}")
        return self._category(
            score,
            {
                "run_count": len(runs),
                "high_sla_risk_count": high,
                "medium_sla_risk_count": medium,
                "slo_status": slo_budget["overall_status"],
            },
            flags,
            ["Review high-SLA tickets with support and engineering leads before lower-risk queue work."],
        )

    def _escalation_quality(
        self,
        state: dict[str, Any],
        ops_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        runs = list(state["runs"].values())
        high_runs = [
            run
            for run in runs
            if run.get("state", {}).get("sla_risk", {}).get("level") == "high"
        ]
        with_playbooks = [
            run
            for run in high_runs
            if run.get("state", {}).get("playbook_recommendations")
        ]
        with_engineering = [
            run
            for run in high_runs
            if run.get("state", {}).get("drafts", {}).get("engineering_escalation")
        ]
        denominator = len(high_runs) or 1
        score = self._clamp(round(((len(with_playbooks) + len(with_engineering)) / (denominator * 2)) * 100))
        flags = []
        if len(with_playbooks) < len(high_runs):
            flags.append("high_risk_runs_missing_playbooks")
        if len(with_engineering) < len(high_runs):
            flags.append("high_risk_runs_missing_engineering_handoff")
        return self._category(
            score,
            {
                "high_risk_run_count": len(high_runs),
                "with_playbook": len(with_playbooks),
                "with_engineering_escalation": len(with_engineering),
                "top_risky_ticket_count": len(ops_snapshot["top_risky_tickets"]),
            },
            flags,
            ["Ensure every high-risk run has a playbook and engineering handoff draft."],
        )

    def _retry_failure_behavior(self, agent_metrics: dict[str, Any]) -> dict[str, Any]:
        failures = agent_metrics["failure_count"]
        tool_failures = agent_metrics["tool_failure_count"]
        drills = agent_metrics["failure_drill_count"]
        score = self._clamp(100 - failures * 15 - tool_failures * 3 + min(15, drills * 5))
        flags = []
        if failures:
            flags.append("workflow_failure_state_recorded")
        if tool_failures:
            flags.append("tool_retry_errors_recorded")
        return self._category(
            score,
            {
                "failure_count": failures,
                "tool_failure_count": tool_failures,
                "failure_drill_count": drills,
            },
            flags,
            ["Use failure drill output to harden retry classification and operator fallback runbooks."],
        )

    def _policy_blocks(self, policy: dict[str, Any]) -> dict[str, Any]:
        blocked_count = len(policy["blocked_actions"])
        matched_count = len(policy["matched_rules"])
        score = self._clamp(100 - blocked_count * 8 - (15 if policy["policy_decision"] == "blocked_pending_remediation" else 0))
        flags = []
        if policy["policy_decision"] == "blocked_pending_remediation":
            flags.append("policy_blocked_pending_remediation")
        if blocked_count:
            flags.append("blocked_actions_present")
        return self._category(
            score,
            {
                "policy_decision": policy["policy_decision"],
                "required_approval_type": policy["required_approval_type"],
                "blocked_action_count": blocked_count,
                "matched_rule_count": matched_count,
            },
            flags,
            [policy["recommended_operator_action"]],
        )

    def _replay_risk(self, replay: dict[str, Any]) -> dict[str, Any]:
        risk_score = replay["risk_score"]
        score = self._clamp(100 - risk_score)
        flags = list(replay["risk_flags"])
        if risk_score >= 75:
            flags.append("high_replay_change_risk")
        return self._category(
            score,
            {
                "replay_risk_score": risk_score,
                "changed_decision_count": len(replay["changed_decisions"]),
                "risk_flags": replay["risk_flags"],
            },
            flags,
            [replay["recommended_operator_action"]],
        )

    def _customer_impact(
        self,
        customer_health: dict[str, Any],
        ops_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        customers = customer_health["customers"]
        at_risk = [
            customer
            for customer in customers
            if customer["risk_level"] in {"critical", "at_risk"}
        ]
        dispatches = ops_snapshot["summary_metrics"]["outbox_dispatch_count"]
        pending = ops_snapshot["summary_metrics"]["pending_approval_count"]
        score = self._clamp(100 - len(at_risk) * 10 - pending * 5 + min(10, dispatches))
        flags = []
        if at_risk:
            flags.append("customer_accounts_at_risk")
        if pending:
            flags.append("customer_impact_pending_approval")
        return self._category(
            score,
            {
                "customer_count": len(customers),
                "at_risk_customer_count": len(at_risk),
                "outbox_dispatch_count": dispatches,
                "pending_approval_count": pending,
            },
            flags,
            ["Pair support lead review with customer-success follow-up for critical or at-risk accounts."],
        )

    def _operator_readiness(self, readiness: dict[str, Any]) -> dict[str, Any]:
        score = int(readiness.get("score", 0))
        flags = []
        if readiness.get("status") != "pass":
            flags.append("operator_readiness_not_passing")
        if readiness.get("missing_sections"):
            flags.append("operator_pack_missing_sections")
        return self._category(
            score,
            {
                "readiness_status": readiness.get("status"),
                "readiness_score": score,
                "missing_section_count": len(readiness.get("missing_sections", [])),
                "linked_artifact_count": len(readiness.get("linked_artifact_paths", {})),
            },
            flags,
            readiness.get("recommended_fixes", []),
        )

    def _category(
        self,
        score: int,
        local_values: dict[str, Any],
        risk_flags: list[str],
        recommended_actions: list[str],
    ) -> dict[str, Any]:
        return {
            "score": score,
            "status": self._status(score, risk_flags),
            "local_values": local_values,
            "risk_flags": list(dict.fromkeys(risk_flags)),
            "recommended_actions": list(dict.fromkeys(recommended_actions)),
        }

    def _status(self, score: int, risk_flags: list[str]) -> str:
        if score < 65 or any("blocked" in flag or "high_replay" in flag for flag in risk_flags):
            return "risk"
        if score < 85 or risk_flags:
            return "watch"
        return "healthy"

    def _overall_risk_flags(self, categories: dict[str, dict[str, Any]]) -> list[str]:
        flags = []
        for name, category in categories.items():
            flags.extend(f"{name}:{flag}" for flag in category["risk_flags"])
        return list(dict.fromkeys(flags))

    def _recommended_actions(
        self,
        categories: dict[str, dict[str, Any]],
        risk_flags: list[str],
    ) -> list[str]:
        actions = []
        for category in categories.values():
            if category["status"] != "healthy":
                actions.extend(category["recommended_actions"][:2])
        if not risk_flags:
            actions.append("Keep the weekly leadership review cadence and monitor local score trends.")
        return list(dict.fromkeys(actions))[:10]

    def _readiness_status(
        self,
        overall_score: int,
        risk_flags: list[str],
        readiness: dict[str, Any],
    ) -> str:
        if readiness.get("status") != "pass" or overall_score < 65:
            return "needs_attention"
        if overall_score < 85 or risk_flags:
            return "review_ready_with_risks"
        return "leadership_ready"

    def _trendish_values(
        self,
        state: dict[str, Any],
        ops_snapshot: dict[str, Any],
        agent_metrics: dict[str, Any],
        slo_budget: dict[str, Any],
        replay: dict[str, Any],
        policy: dict[str, Any],
        readiness: dict[str, Any],
    ) -> dict[str, Any]:
        runs = list(state["runs"].values())
        recent = sorted(runs, key=lambda item: item.get("started_at", ""))[-5:]
        recent_actions = Counter(run.get("final_action") or "none" for run in recent)
        return {
            "recent_run_count": len(recent),
            "recent_final_actions": dict(sorted(recent_actions.items())),
            "approval_rate_percent": self._approval_rate(state),
            "pending_approvals": agent_metrics["pending_approvals"],
            "high_sla_risk_count": ops_snapshot["counts"]["sla_risk"].get("high", 0),
            "failure_count": agent_metrics["failure_count"],
            "tool_failure_count": agent_metrics["tool_failure_count"],
            "outbox_dispatch_count": agent_metrics["outbox_dispatch_count"],
            "slo_status": slo_budget["overall_status"],
            "replay_risk_score": replay["risk_score"],
            "policy_decision": policy["policy_decision"],
            "operator_readiness_score": readiness.get("score", 0),
        }

    def _approval_rate(self, state: dict[str, Any]) -> float:
        approvals = list(state["approvals"].values())
        if not approvals:
            return 100.0
        approved = len([item for item in approvals if item.get("status") == "approved"])
        return round((approved / len(approvals)) * 100, 2)

    def _artifact_links(self) -> dict[str, str]:
        directories = {
            "briefs": self.leadership_reviews_dir.parent / "briefs",
            "weekly_reviews": self.leadership_reviews_dir.parent / "reports",
            "optimization_reports": self.leadership_reviews_dir.parent / "optimization_reports",
            "account_briefs": self.leadership_reviews_dir.parent / "account_briefs",
            "replay_reports": self.leadership_reviews_dir.parent / "replay_reports",
            "policy_packs": self.leadership_reviews_dir.parent / "policy_packs",
            "operator_packs": self.leadership_reviews_dir.parent / "operator_packs",
            "incident_narratives": self.leadership_reviews_dir.parent / "incident_narratives",
            "leadership_reviews": self.leadership_reviews_dir,
        }
        links = {}
        for name, directory in directories.items():
            latest = self._latest_file(directory)
            if latest:
                links[f"{name}_latest"] = str(latest)
        return links

    def _latest_file(self, directory: Path) -> Path | None:
        if not directory.exists():
            return None
        files = sorted(directory.glob("*.md"), key=lambda item: item.stat().st_mtime)
        return files[-1] if files else None

    def _write_pack(
        self,
        review_id: str,
        review: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.leadership_reviews_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.leadership_reviews_dir / f"{review_id}.json"
        markdown_path = self.leadership_reviews_dir / f"{review_id}.md"
        json_path.write_text(json.dumps(review, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _jd_skills(self) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    "Executive KPI design for safe support automation leadership review.",
                    "Local-first FastAPI reporting over traces, approvals, SLOs, replay, and guardrails.",
                    "Artifact export discipline with Markdown and JSON review packs.",
                    *JD_SKILLS_DEMONSTRATED,
                ]
            )
        )

    def _talking_points(self, scorecard: dict[str, Any]) -> list[str]:
        return [
            (
                "The Leadership Scorecard turns local agent evidence into an executive automation KPI view "
                f"with overall score {scorecard['overall_score']}."
            ),
            (
                f"Readiness is `{scorecard['readiness_status']}` across "
                f"{len(scorecard['kpi_categories'])} categories covering safety, SLA, replay, policy, and impact."
            ),
            (
                f"Replay risk is {scorecard['trendish_local_values']['replay_risk_score']} and policy decision is "
                f"`{scorecard['trendish_local_values']['policy_decision']}`."
            ),
            "The review pack links local evidence artifacts instead of relying on external BI or warehouse data.",
            "Leaders get top risks, next actions, reproducible local commands, and interview-ready talking points.",
        ]

    def _markdown(self, review: dict[str, Any]) -> str:
        scorecard = review["scorecard"]
        category_rows = [
            (
                f"- {name}: {category['score']} ({category['status']}) - "
                f"{json.dumps(category['local_values'], sort_keys=True)}"
            )
            for name, category in scorecard["kpi_categories"].items()
        ]
        definitions = [
            f"- {name}: {definition}" for name, definition in review["kpi_definitions"].items()
        ]
        risks = [f"- {risk}" for risk in review["top_risks"]] or ["- None"]
        actions = [f"- {action}" for action in review["recommended_next_actions"]]
        links = [
            f"- {name}: `{path}`" for name, path in sorted(review["local_evidence_links"].items())
        ] or ["- No local evidence artifacts have been exported yet."]
        commands = [f"- `{command}`" for command in review["local_commands"]]
        skills = [f"- {skill}" for skill in review["jd_skills_demonstrated"]]
        talking_points = [f"- {point}" for point in review["interviewer_talking_points"]]
        return "\n".join(
            [
                f"# Leadership Review Pack: {review['review_id']}",
                "",
                "## Automation KPI Scorecard",
                f"- Overall score: {scorecard['overall_score']}",
                f"- Readiness status: {scorecard['readiness_status']}",
                f"- Sample window: {json.dumps(scorecard['sample_window'], sort_keys=True)}",
                "",
                "## KPI Categories",
                *category_rows,
                "",
                "## KPI Definitions",
                *definitions,
                "",
                "## Top Risks",
                *risks,
                "",
                "## Recommended Next Actions",
                *actions,
                "",
                "## Local Evidence Links",
                *links,
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

    def _clamp(self, value: int, penalty: int = 0) -> int:
        return max(0, min(100, value - penalty))
