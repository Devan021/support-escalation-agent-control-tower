import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore
from app.models import Approval, Playbook, PlaybookRecommendation, Ticket, TicketCreate
from app.services.tickets import TicketService


class PlaybookService:
    def __init__(
        self,
        store: JsonStateStore,
        ticket_service: TicketService,
        library_path: Path,
        checklists_dir: Path,
    ):
        self.store = store
        self.ticket_service = ticket_service
        self.library_path = library_path
        self.checklists_dir = checklists_dir

    def list_playbooks(self) -> list[Playbook]:
        rows = json.loads(self.library_path.read_text(encoding="utf-8"))
        return [Playbook(**row) for row in rows]

    async def recommend(
        self,
        ticket_id: str | None = None,
        ticket_payload: TicketCreate | None = None,
        top_n: int = 3,
    ) -> dict[str, Any]:
        ticket, run_state = await self._resolve_ticket_context(ticket_id, ticket_payload)
        recommendations = self.recommend_for_ticket(ticket, run_state, top_n)
        return {
            "ticket_id": ticket.ticket_id,
            "source": "ticket_id" if ticket_id else "ticket_payload",
            "recommendations": [item.model_dump(mode="json") for item in recommendations],
        }

    def recommend_for_ticket(
        self,
        ticket: Ticket,
        run_state: dict[str, Any] | None = None,
        top_n: int = 3,
    ) -> list[PlaybookRecommendation]:
        run_state = run_state or {}
        classification = run_state.get("classification", {})
        sla_risk = run_state.get("sla_risk", {})
        haystack = self._tokens(
            " ".join(
                [
                    ticket.subject,
                    ticket.body,
                    ticket.priority,
                    ticket.customer_tier,
                    " ".join(ticket.tags),
                    classification.get("category", ""),
                    " ".join(sla_risk.get("reasons", [])),
                ]
            )
        )
        text = " ".join(sorted(haystack))
        scored = []
        for playbook in self.list_playbooks():
            score = 0.08
            reasons = []
            tag_hits = [tag for tag in playbook.tags if self._tag_matches(tag, text, haystack)]
            if tag_hits:
                score += min(0.42, 0.08 * len(tag_hits))
                reasons.append(f"Matched playbook tags: {', '.join(tag_hits[:5])}.")
            if classification.get("category") == playbook.category:
                score += 0.24
                reasons.append(f"Classification category is {playbook.category}.")
            if playbook.category in haystack:
                score += 0.12
                reasons.append(f"Ticket text references {playbook.category}.")
            if ticket.priority in {"urgent", "high"} and playbook.severity in {"high", "critical"}:
                score += 0.12
                reasons.append(f"Ticket priority is {ticket.priority}.")
            if sla_risk.get("level") == "high" and playbook.severity in {"high", "critical"}:
                score += 0.14
                reasons.append("High SLA risk favors urgent operational playbooks.")
            if ticket.customer_tier == "enterprise" and playbook.severity in {"high", "critical"}:
                score += 0.08
                reasons.append("Enterprise customer tier increases handoff rigor.")
            if not reasons:
                reasons.append("Low-signal fallback based on general support coverage.")

            confidence = round(min(score, 0.98), 2)
            scored.append(
                PlaybookRecommendation(
                    id=playbook.id,
                    title=playbook.title,
                    category=playbook.category,
                    tags=playbook.tags,
                    severity=playbook.severity,
                    match_reasons=reasons,
                    confidence=confidence,
                    checklist=playbook.checklist,
                    owner_roles=playbook.owner_roles,
                    escalation_policy=playbook.escalation_policy,
                    customer_update_template=playbook.customer_update_template,
                )
            )
        return sorted(scored, key=lambda item: (item.confidence, item.severity), reverse=True)[:top_n]

    async def export_remediation_checklist(
        self,
        run_id: str,
        playbook_id: str | None = None,
    ) -> dict[str, Any]:
        state = await self.store.load()
        raw_run = state["runs"].get(run_id)
        if raw_run is None:
            raise KeyError(run_id)
        run_state = raw_run.get("state", {})
        ticket = await self.ticket_service.get(raw_run["ticket_id"])
        if ticket is None:
            raise KeyError(raw_run["ticket_id"])

        recommendations = [
            PlaybookRecommendation(**item)
            for item in run_state.get("playbook_recommendations", [])
        ]
        if not recommendations:
            recommendations = self.recommend_for_ticket(ticket, run_state, top_n=5)
        selected = self._select_playbook(recommendations, playbook_id)
        approval = self._approval_for_run(state, run_id)

        checklist_id = f"checklist_{run_id}_{selected.id}"
        checklist = {
            "checklist_id": checklist_id,
            "run_id": run_id,
            "ticket": {
                "ticket_id": ticket.ticket_id,
                "subject": ticket.subject,
                "customer_tier": ticket.customer_tier,
                "priority": ticket.priority,
                "tags": ticket.tags,
            },
            "classification": run_state.get("classification", {}),
            "sla_risk": run_state.get("sla_risk", {}),
            "selected_playbook": selected.model_dump(mode="json"),
            "checklist": [
                {
                    "step": index + 1,
                    "title": step,
                    "owner_role": selected.owner_roles[index % len(selected.owner_roles)]
                    if selected.owner_roles
                    else "Support Lead",
                    "status": "pending",
                }
                for index, step in enumerate(selected.checklist)
            ],
            "owners": selected.owner_roles,
            "approval_status": {
                "approval_id": approval.approval_id if approval else run_state.get("approval_id"),
                "status": approval.status if approval else run_state.get("approval_status", "none"),
                "decided_by": approval.decided_by if approval else None,
                "decision_note": approval.decision_note if approval else None,
            },
            "next_update_template": selected.customer_update_template.format(ticket_id=ticket.ticket_id),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        markdown = self._markdown(checklist)
        json_path, markdown_path = self._write_files(checklist_id, checklist, markdown)
        return {
            "run_id": run_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "checklist": checklist,
            "markdown": markdown,
        }

    async def _resolve_ticket_context(
        self,
        ticket_id: str | None,
        ticket_payload: TicketCreate | None,
    ) -> tuple[Ticket, dict[str, Any]]:
        if ticket_id:
            ticket = await self.ticket_service.get(ticket_id)
            if ticket is None:
                raise KeyError(ticket_id)
            return ticket, await self._latest_run_state(ticket_id)
        if ticket_payload:
            return Ticket(**ticket_payload.model_dump()), {}
        raise ValueError("ticket_id or ticket payload is required")

    async def _latest_run_state(self, ticket_id: str) -> dict[str, Any]:
        state = await self.store.load()
        runs = [run for run in state["runs"].values() if run.get("ticket_id") == ticket_id]
        if not runs:
            return {}
        latest = sorted(runs, key=lambda item: item.get("started_at", ""))[-1]
        return latest.get("state", {})

    def _select_playbook(
        self,
        recommendations: list[PlaybookRecommendation],
        playbook_id: str | None,
    ) -> PlaybookRecommendation:
        if not recommendations:
            raise KeyError("no_playbook_recommendations")
        if playbook_id is None:
            return recommendations[0]
        for recommendation in recommendations:
            if recommendation.id == playbook_id:
                return recommendation
        for playbook in self.list_playbooks():
            if playbook.id == playbook_id:
                return PlaybookRecommendation(
                    id=playbook.id,
                    title=playbook.title,
                    category=playbook.category,
                    tags=playbook.tags,
                    severity=playbook.severity,
                    match_reasons=["Selected explicitly for remediation export."],
                    confidence=1.0,
                    checklist=playbook.checklist,
                    owner_roles=playbook.owner_roles,
                    escalation_policy=playbook.escalation_policy,
                    customer_update_template=playbook.customer_update_template,
                )
        raise KeyError(playbook_id)

    def _approval_for_run(self, state: dict[str, Any], run_id: str) -> Approval | None:
        approvals = [
            Approval(**raw)
            for raw in state["approvals"].values()
            if raw.get("run_id") == run_id
        ]
        return approvals[-1] if approvals else None

    def _write_files(
        self,
        checklist_id: str,
        checklist: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.checklists_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.checklists_dir / f"{checklist_id}.json"
        markdown_path = self.checklists_dir / f"{checklist_id}.md"
        json_path.write_text(json.dumps(checklist, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _markdown(self, checklist: dict[str, Any]) -> str:
        ticket = checklist["ticket"]
        playbook = checklist["selected_playbook"]
        classification = checklist["classification"]
        sla_risk = checklist["sla_risk"]
        approval = checklist["approval_status"]
        steps = [
            f"- [ ] Step {item['step']}: {item['title']} ({item['owner_role']})"
            for item in checklist["checklist"]
        ]
        reasons = [f"- {reason}" for reason in playbook.get("match_reasons", [])]
        return "\n".join(
            [
                f"# Remediation Checklist: {checklist['run_id']}",
                "",
                "## Ticket",
                f"- Ticket: {ticket['ticket_id']}",
                f"- Subject: {ticket['subject']}",
                f"- Tier: {ticket['customer_tier']}",
                f"- Priority: {ticket['priority']}",
                "",
                "## Classification and SLA",
                f"- Category: {classification.get('category', 'unknown')}",
                f"- Confidence: {classification.get('confidence', 'unknown')}",
                f"- SLA risk: {sla_risk.get('level', 'unknown')} ({sla_risk.get('score', 'unknown')})",
                "",
                "## Selected Playbook",
                f"- {playbook['title']} ({playbook['id']})",
                f"- Severity: {playbook['severity']}",
                f"- Confidence: {playbook['confidence']}",
                f"- Owners: {', '.join(checklist['owners'])}",
                f"- Escalation policy: {playbook['escalation_policy']}",
                "",
                "## Match Reasons",
                *reasons,
                "",
                "## Checklist",
                *steps,
                "",
                "## Approval Status",
                f"- Approval: {approval.get('approval_id')}",
                f"- Status: {approval.get('status')}",
                "",
                "## Next Customer Update",
                checklist["next_update_template"],
                "",
            ]
        )

    def _tag_matches(self, tag: str, text: str, tokens: set[str]) -> bool:
        normalized = tag.lower()
        return normalized in text if " " in normalized else normalized in tokens

    def _tokens(self, text: str) -> set[str]:
        normalized = re.sub(r"[^a-z0-9_ ]+", " ", text.lower())
        tokens = set(normalized.split())
        if "api" in tokens and "key" in tokens:
            tokens.add("api key")
        if "zero" in tokens and "downtime" in tokens:
            tokens.add("zero downtime")
        return tokens
