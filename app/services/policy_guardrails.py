import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.storage import JsonStateStore
from app.models import OutboxActionType, PolicySimulationRequest, ReplayModifiers, RunRecord, Ticket
from app.services.replay_lab import ReplayLabService
from app.services.tickets import TicketService
from app.services.workflow import AgentWorkflowService


DISPATCH_ACTIONS = [
    OutboxActionType.customer_reply,
    OutboxActionType.zendesk_update,
    OutboxActionType.jira_issue,
    OutboxActionType.slack_alert,
    OutboxActionType.engineering_escalation,
]


class PolicyGuardrailService:
    def __init__(
        self,
        store: JsonStateStore,
        tickets: TicketService,
        workflow: AgentWorkflowService,
        replay_lab: ReplayLabService,
        policy_packs_dir: Path,
        low_confidence_threshold: float,
    ):
        self.store = store
        self.tickets = tickets
        self.workflow = workflow
        self.replay_lab = replay_lab
        self.policy_packs_dir = policy_packs_dir
        self.low_confidence_threshold = low_confidence_threshold

    async def simulate(
        self,
        payload: PolicySimulationRequest | None = None,
    ) -> dict[str, Any]:
        request = payload or PolicySimulationRequest()
        replay = await self.replay_lab.replay(request.run_id, request.modifiers)
        run = await self.workflow.get_run(replay["source_run_id"])
        ticket = await self._ticket_for_run(run)
        requested_actions = self._requested_actions(request)
        context = self._context(request, replay, run, ticket)
        matched_rules = self._matched_rules(context, requested_actions, request.replay_risk_threshold)
        blocked_actions = self._blocked_actions(matched_rules, requested_actions)
        allowed_actions = self._allowed_actions(requested_actions, blocked_actions)
        approval_chain = self._approval_chain(matched_rules)
        decision = self._decision(matched_rules)
        required_approval_type = approval_chain[0] if approval_chain else "none"
        warnings = self._warnings(context, matched_rules)
        recommended_action = self._recommended_operator_action(
            decision,
            required_approval_type,
            blocked_actions,
            context,
        )

        return {
            "simulation_id": f"polsim_{uuid4().hex[:10]}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "local-deterministic-policy-simulator",
            "source_run_id": replay["source_run_id"],
            "source_trace_id": replay["source_trace_id"],
            "ticket_id": ticket.ticket_id,
            "customer_tier": self._customer_tier(ticket),
            "requested_actions": [action.value for action in requested_actions],
            "policy_decision": decision,
            "required_approval_type": required_approval_type,
            "approval_chain": approval_chain,
            "blocked_actions": [action.value for action in blocked_actions],
            "allowed_actions": [action.value for action in allowed_actions],
            "matched_rules": matched_rules,
            "warnings": warnings,
            "recommended_operator_action": recommended_action,
            "approval_matrix": self.approval_matrix(),
            "policy_inputs": context,
            "replay_summary": {
                "risk_score": replay["comparison"]["risk_score"],
                "risk_flags": replay["comparison"]["risk_flags"],
                "recommended_operator_action": replay["comparison"]["recommended_operator_action"],
                "changed_decisions": replay["comparison"]["changed_decisions"],
            },
            "local_verification_commands": self._verification_commands(),
        }

    async def export_pack(
        self,
        payload: PolicySimulationRequest | None = None,
    ) -> dict[str, Any]:
        request = payload or PolicySimulationRequest()
        generated_at = datetime.now(timezone.utc)
        pack_id = f"policy_pack_{generated_at.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        primary = await self.simulate(request)
        scenario_outcomes = await self._sample_scenario_outcomes(primary["source_run_id"])
        pack = {
            "pack_id": pack_id,
            "generated_at": generated_at.isoformat(),
            "simulated_policies": self._simulated_policies(),
            "primary_simulation": primary,
            "matched_rules": primary["matched_rules"],
            "approval_matrix": self.approval_matrix(),
            "sample_scenario_outcomes": scenario_outcomes,
            "local_verification_commands": self._verification_commands(),
            "jd_skills_demonstrated": self._jd_skills(),
            "interviewer_talking_points": self._talking_points(primary),
        }
        markdown = self._markdown(pack)
        json_path, markdown_path = self._write_pack(pack_id, pack, markdown)
        pack["artifact_paths"] = {
            "policy_pack_json": str(json_path),
            "policy_pack_markdown": str(markdown_path),
        }
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        return {
            "pack_id": pack_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "pack": pack,
            "markdown": markdown,
        }

    def approval_matrix(self) -> list[dict[str, Any]]:
        return [
            {
                "rule_id": "external_reply_requires_approval",
                "approval_type": "support_lead",
                "actions": ["customer_reply", "zendesk_update"],
                "default_effect": "approval_required",
            },
            {
                "rule_id": "enterprise_or_vip_customer",
                "approval_type": "support_manager",
                "actions": [action.value for action in DISPATCH_ACTIONS],
                "default_effect": "approval_required",
            },
            {
                "rule_id": "high_or_critical_sla_pressure",
                "approval_type": "incident_commander",
                "actions": ["jira_issue", "slack_alert", "engineering_escalation"],
                "default_effect": "approval_required",
            },
            {
                "rule_id": "low_confidence",
                "approval_type": "support_lead",
                "actions": ["customer_reply", "zendesk_update"],
                "default_effect": "block_until_review",
            },
            {
                "rule_id": "adapter_degraded_or_failing",
                "approval_type": "ops_lead",
                "actions": [action.value for action in DISPATCH_ACTIONS],
                "default_effect": "block_until_adapter_recovery",
            },
            {
                "rule_id": "replay_risk_above_threshold",
                "approval_type": "policy_admin",
                "actions": [action.value for action in DISPATCH_ACTIONS],
                "default_effect": "block_policy_rollout",
            },
            {
                "rule_id": "missing_or_conflicting_kb_context",
                "approval_type": "knowledge_owner",
                "actions": ["customer_reply", "zendesk_update"],
                "default_effect": "block_until_grounded",
            },
        ]

    async def _sample_scenario_outcomes(self, source_run_id: str) -> list[dict[str, Any]]:
        scenarios = [
            (
                "standard_current_context",
                ReplayModifiers(),
                70,
            ),
            (
                "low_confidence_external_reply",
                ReplayModifiers(confidence_override=0.38),
                70,
            ),
            (
                "critical_sla_enterprise",
                ReplayModifiers(sla_pressure="critical", approval_policy="strict"),
                70,
            ),
            (
                "adapter_failure_missing_kb",
                ReplayModifiers(
                    sla_pressure="critical",
                    kb_context="missing",
                    adapter_health="failing",
                    confidence_override=0.2,
                ),
                70,
            ),
            (
                "conflicting_kb_policy_rollout",
                ReplayModifiers(kb_context="conflicting", confidence_override=0.55),
                45,
            ),
        ]
        outcomes = []
        for name, modifiers, threshold in scenarios:
            simulation = await self.simulate(
                PolicySimulationRequest(
                    run_id=source_run_id,
                    modifiers=modifiers,
                    replay_risk_threshold=threshold,
                )
            )
            outcomes.append(
                {
                    "scenario": name,
                    "policy_decision": simulation["policy_decision"],
                    "required_approval_type": simulation["required_approval_type"],
                    "blocked_actions": simulation["blocked_actions"],
                    "matched_rule_ids": [rule["rule_id"] for rule in simulation["matched_rules"]],
                    "replay_risk_score": simulation["replay_summary"]["risk_score"],
                    "recommended_operator_action": simulation["recommended_operator_action"],
                }
            )
        return outcomes

    async def _ticket_for_run(self, run: RunRecord) -> Ticket:
        ticket = await self.tickets.get(run.ticket_id)
        if ticket is None:
            raise KeyError(run.ticket_id)
        return ticket

    def _requested_actions(self, request: PolicySimulationRequest) -> list[OutboxActionType]:
        seen = []
        for action in request.requested_actions or DISPATCH_ACTIONS:
            if action not in seen:
                seen.append(action)
        return seen

    def _context(
        self,
        request: PolicySimulationRequest,
        replay: dict[str, Any],
        run: RunRecord,
        ticket: Ticket,
    ) -> dict[str, Any]:
        replay_outcome = replay["replay"]
        comparison = replay["comparison"]
        qa = replay_outcome.get("qa") or {}
        ticket_tags = [tag.lower() for tag in ticket.tags]
        return {
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "ticket_id": ticket.ticket_id,
            "customer_tier": self._customer_tier(ticket),
            "is_vip": "vip" in ticket_tags or "executive" in ticket_tags,
            "classification_confidence": replay_outcome["classification"]["confidence"],
            "qa_confidence": qa.get("confidence", replay_outcome["classification"]["confidence"]),
            "sla_level": replay_outcome["sla_risk"]["level"],
            "sla_score": replay_outcome["sla_risk"]["score"],
            "adapter_health": request.modifiers.adapter_health,
            "adapter_failed": bool(replay_outcome.get("failure_state")),
            "kb_context": request.modifiers.kb_context,
            "qa_findings": qa.get("findings", []),
            "replay_risk_score": comparison["risk_score"],
            "replay_risk_flags": comparison["risk_flags"],
            "final_action": replay_outcome["final_action"],
            "approval_policy": request.modifiers.approval_policy,
            "low_confidence_threshold": self.low_confidence_threshold,
            "existing_approval_id": run.state.get("approval_id"),
        }

    def _customer_tier(self, ticket: Ticket) -> str:
        if "vip" in [tag.lower() for tag in ticket.tags]:
            return "vip"
        return ticket.customer_tier

    def _matched_rules(
        self,
        context: dict[str, Any],
        requested_actions: list[OutboxActionType],
        replay_risk_threshold: int,
    ) -> list[dict[str, Any]]:
        rules = []
        external_actions = [
            action
            for action in requested_actions
            if action in {OutboxActionType.customer_reply, OutboxActionType.zendesk_update}
        ]
        internal_dispatch_actions = [
            action
            for action in requested_actions
            if action
            in {
                OutboxActionType.jira_issue,
                OutboxActionType.slack_alert,
                OutboxActionType.engineering_escalation,
            }
        ]
        if context["qa_confidence"] < self.low_confidence_threshold:
            rules.append(
                self._rule(
                    "low_confidence",
                    "QA or classification confidence is below the automation threshold.",
                    "support_lead",
                    external_actions or requested_actions,
                    "high",
                    {
                        "confidence": context["qa_confidence"],
                        "threshold": self.low_confidence_threshold,
                    },
                )
            )
        if context["sla_level"] == "high":
            rules.append(
                self._rule(
                    "high_or_critical_sla_pressure",
                    "High or critical SLA pressure makes escalation dispatch approval-bound.",
                    "incident_commander",
                    internal_dispatch_actions or requested_actions,
                    "high",
                    {"sla_level": context["sla_level"], "sla_score": context["sla_score"]},
                )
            )
        if context["customer_tier"] in {"enterprise", "vip"} or context["is_vip"]:
            rules.append(
                self._rule(
                    "enterprise_or_vip_customer",
                    "Enterprise or VIP customer tier requires manager approval for automation.",
                    "support_manager",
                    requested_actions,
                    "medium",
                    {"customer_tier": context["customer_tier"], "is_vip": context["is_vip"]},
                )
            )
        if external_actions:
            rules.append(
                self._rule(
                    "external_reply_requires_approval",
                    "Customer-visible replies and Zendesk updates are external actions.",
                    "support_lead",
                    external_actions,
                    "medium",
                    {"external_actions": [action.value for action in external_actions]},
                )
            )
        if context["adapter_health"] in {"degraded", "failing"} or context["adapter_failed"]:
            rules.append(
                self._rule(
                    "adapter_degraded_or_failing",
                    "Adapter health is degraded or failing, so dispatch waits for recovery review.",
                    "ops_lead",
                    requested_actions,
                    "block",
                    {
                        "adapter_health": context["adapter_health"],
                        "adapter_failed": context["adapter_failed"],
                    },
                )
            )
        if context["replay_risk_score"] >= replay_risk_threshold:
            rules.append(
                self._rule(
                    "replay_risk_above_threshold",
                    "Replay Lab risk exceeds the configured policy rollout threshold.",
                    "policy_admin",
                    requested_actions,
                    "block",
                    {
                        "replay_risk_score": context["replay_risk_score"],
                        "threshold": replay_risk_threshold,
                    },
                )
            )
        if context["kb_context"] in {"missing", "conflicting"}:
            rules.append(
                self._rule(
                    "missing_or_conflicting_kb_context",
                    "KB context is missing or conflicting, so customer-facing text must be grounded.",
                    "knowledge_owner",
                    external_actions or requested_actions,
                    "block",
                    {"kb_context": context["kb_context"], "qa_findings": context["qa_findings"]},
                )
            )
        return rules

    def _rule(
        self,
        rule_id: str,
        reason: str,
        approval_type: str,
        blocked_actions: list[OutboxActionType],
        severity: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "rule_id": rule_id,
            "label": rule_id.replace("_", " ").title(),
            "effect": "block" if severity == "block" else "approval_required",
            "severity": severity,
            "required_approval_type": approval_type,
            "blocked_actions": [action.value for action in blocked_actions],
            "reason": reason,
            "evidence": evidence,
        }

    def _blocked_actions(
        self,
        matched_rules: list[dict[str, Any]],
        requested_actions: list[OutboxActionType],
    ) -> list[OutboxActionType]:
        by_value = {action.value: action for action in requested_actions}
        blocked = []
        for rule in matched_rules:
            for action in rule["blocked_actions"]:
                typed = by_value.get(action)
                if typed and typed not in blocked:
                    blocked.append(typed)
        return blocked

    def _allowed_actions(
        self,
        requested_actions: list[OutboxActionType],
        blocked_actions: list[OutboxActionType],
    ) -> list[OutboxActionType]:
        return [action for action in requested_actions if action not in blocked_actions]

    def _approval_chain(self, matched_rules: list[dict[str, Any]]) -> list[str]:
        rank = {
            "policy_admin": 0,
            "ops_lead": 1,
            "incident_commander": 2,
            "knowledge_owner": 3,
            "support_manager": 4,
            "support_lead": 5,
        }
        approvals = {rule["required_approval_type"] for rule in matched_rules}
        return sorted(approvals, key=lambda item: rank.get(item, 99))

    def _decision(self, matched_rules: list[dict[str, Any]]) -> str:
        if any(rule["effect"] == "block" for rule in matched_rules):
            return "blocked_pending_remediation"
        if matched_rules:
            return "requires_approval"
        return "auto_allowed"

    def _warnings(
        self,
        context: dict[str, Any],
        matched_rules: list[dict[str, Any]],
    ) -> list[str]:
        warnings = []
        if not matched_rules:
            warnings.append("No default guardrail matched; continue trace and audit monitoring.")
        if context["existing_approval_id"]:
            warnings.append(f"Run already has approval record {context['existing_approval_id']}.")
        if context["replay_risk_flags"]:
            warnings.append("Replay risk flags: " + ", ".join(context["replay_risk_flags"]))
        if context["qa_findings"]:
            warnings.extend(context["qa_findings"])
        return list(dict.fromkeys(warnings))

    def _recommended_operator_action(
        self,
        decision: str,
        required_approval_type: str,
        blocked_actions: list[OutboxActionType],
        context: dict[str, Any],
    ) -> str:
        if decision == "blocked_pending_remediation":
            return (
                "Pause automation, assign "
                f"{required_approval_type}, remediate {', '.join(action.value for action in blocked_actions)}, "
                "then re-run the simulator before dispatch."
            )
        if decision == "requires_approval":
            return (
                f"Route the policy preview to {required_approval_type}; allow only unblocked internal "
                "work until approval is recorded."
            )
        if context["sla_level"] == "high":
            return "Monitor SLA pressure and keep incident handoff ready even though policy allows automation."
        return "Policy preview is clear for local mock automation; keep audit and trace evidence attached."

    def _simulated_policies(self) -> list[dict[str, Any]]:
        return [
            {
                "policy_id": "standard_enterprise_guardrails",
                "description": "Default approval policy for support automation dispatches.",
                "rules": [item["rule_id"] for item in self.approval_matrix()],
            },
            {
                "policy_id": "strict_replay_rollout",
                "description": "Blocks automation rollout when replay risk or grounding risk is elevated.",
                "rules": [
                    "adapter_degraded_or_failing",
                    "replay_risk_above_threshold",
                    "missing_or_conflicting_kb_context",
                ],
            },
            {
                "policy_id": "internal_low_risk_autonomy",
                "description": "Allows low-risk internal notes while customer-visible actions wait.",
                "rules": ["external_reply_requires_approval", "low_confidence"],
            },
        ]

    def _verification_commands(self) -> list[str]:
        return [
            r".\.venv\Scripts\python.exe -m pytest -q",
            r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
            r".\.venv\Scripts\python.exe -m app.evals.run_eval",
            r".\.venv\Scripts\python.exe scripts\demo_run.py",
            (
                r'rg "policies/simulate|policies/export|Policy Guardrail|policy_packs|'
                r'approval policy" app dashboard docs README.md tests scripts'
            ),
        ]

    def _jd_skills(self) -> list[str]:
        return [
            "Enterprise AI governance with explainable approval policy simulation.",
            "FastAPI control-plane design for local-only agent automation guardrails.",
            "Human-in-the-loop escalation logic across customer replies, Jira, Slack, and engineering.",
            "Replay-informed risk modeling that connects counterfactual findings to dispatch policy.",
            "Audit-ready Markdown and JSON evidence packs for operator and interviewer review.",
        ]

    def _talking_points(self, primary: dict[str, Any]) -> list[str]:
        return [
            (
                "The Policy Guardrail Center turns agent governance into deterministic rules with "
                f"{len(primary['matched_rules'])} matched rules for the primary scenario."
            ),
            (
                f"The primary approval path is `{primary['required_approval_type']}` and the "
                f"decision is `{primary['policy_decision']}`."
            ),
            "Managers can preview how external replies differ from internal Jira, Slack, and engineering actions.",
            "Replay Lab risk, adapter health, confidence, SLA pressure, and KB grounding all feed the same approval matrix.",
            "The exported pack includes local commands and scenario outcomes so reviewers can reproduce the governance demo.",
        ]

    def _write_pack(
        self,
        pack_id: str,
        pack: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.policy_packs_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.policy_packs_dir / f"{pack_id}.json"
        markdown_path = self.policy_packs_dir / f"{pack_id}.md"
        json_path.write_text(json.dumps(pack, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _markdown(self, pack: dict[str, Any]) -> str:
        primary = pack["primary_simulation"]
        policies = [
            f"- {policy['policy_id']}: {policy['description']}"
            for policy in pack["simulated_policies"]
        ]
        rules = [
            (
                f"- {rule['rule_id']}: {rule['effect']} via "
                f"`{rule['required_approval_type']}` for {', '.join(rule['blocked_actions'])}"
            )
            for rule in pack["matched_rules"]
        ] or ["- None"]
        matrix = [
            (
                f"- {item['rule_id']}: `{item['approval_type']}` | "
                f"{item['default_effect']} | actions: {', '.join(item['actions'])}"
            )
            for item in pack["approval_matrix"]
        ]
        outcomes = [
            (
                f"- {item['scenario']}: {item['policy_decision']} / "
                f"{item['required_approval_type']} / risk {item['replay_risk_score']}"
            )
            for item in pack["sample_scenario_outcomes"]
        ]
        commands = [f"- `{command}`" for command in pack["local_verification_commands"]]
        skills = [f"- {skill}" for skill in pack["jd_skills_demonstrated"]]
        talking_points = [f"- {point}" for point in pack["interviewer_talking_points"]]
        return "\n".join(
            [
                f"# Policy Guardrail Pack: {pack['pack_id']}",
                "",
                "## Approval Policy Summary",
                f"- Primary decision: {primary['policy_decision']}",
                f"- Required approval type: {primary['required_approval_type']}",
                f"- Source run: {primary['source_run_id']}",
                f"- Ticket: {primary['ticket_id']} ({primary['customer_tier']})",
                f"- Blocked actions: {', '.join(primary['blocked_actions']) or 'none'}",
                f"- Allowed actions: {', '.join(primary['allowed_actions']) or 'none'}",
                f"- Recommended operator action: {primary['recommended_operator_action']}",
                "",
                "## Simulated Policies",
                *policies,
                "",
                "## Matched Rules",
                *rules,
                "",
                "## Approval Matrix",
                *matrix,
                "",
                "## Sample Scenario Outcomes",
                *outcomes,
                "",
                "## Local Verification Commands",
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
