from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.adapters.fake import AdapterError, FakeKnowledgeBaseAdapter
from app.core.storage import JsonStateStore
from app.models import AuditEvent, KnowledgeArticle
from app.services.trace import TraceService

if TYPE_CHECKING:
    from app.services.audit import AuditService
    from app.services.leadership import LeadershipScorecardService
    from app.services.tickets import TicketService


CATEGORY_TAGS = {
    "authentication": {"auth", "sso", "login", "oauth", "saml", "mfa", "outage"},
    "billing": {"billing", "invoice", "refund", "finance", "credit"},
    "api_integrations": {"api", "webhook", "latency", "5xx", "integration", "rotation"},
    "security_privacy": {"privacy", "data", "compliance", "security", "deletion", "export"},
    "incident": {"incident", "outage", "sla", "production", "blocked", "breach"},
    "how_to": {"how_to", "how-to", "rotation", "api", "key"},
    "general_support": {"reply", "support", "qa", "customer"},
}

HIGH_IMPACT_CATEGORIES = {"authentication", "api_integrations", "security_privacy", "incident"}

LOCAL_COMMANDS = [
    r".\.venv\Scripts\python.exe -m pytest -q",
    r".\.venv\Scripts\python.exe -m ruff check app tests dashboard scripts",
    r".\.venv\Scripts\python.exe -m app.evals.run_eval",
    r".\.venv\Scripts\python.exe scripts\demo_run.py",
    (
        r'rg "knowledge/quality-audit|knowledge/refresh-plan|Knowledge Quality|'
        r'kb_refresh_plans|KB refresh" app dashboard docs README.md tests scripts'
    ),
]


class KnowledgeRetrievalService:
    def __init__(self, adapter: FakeKnowledgeBaseAdapter, trace_service: TraceService, max_attempts: int):
        self.adapter = adapter
        self.trace_service = trace_service
        self.max_attempts = max_attempts

    async def search_with_retries(self, run_id: str, trace_id: str, ticket_id: str, query: str, tags: list[str]) -> tuple[list[KnowledgeArticle], list[dict], dict | None]:
        calls = []
        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            start = time.perf_counter()
            try:
                results = await self.adapter.search(query, tags, 3)
                latency = (time.perf_counter() - start) * 1000
                calls.append({"name": "internal_kb.search", "attempt": attempt, "status": "ok", "latency_ms": latency})
                await self.trace_service.tool_call(run_id, trace_id, ticket_id, "knowledge_retriever", "internal_kb.search", attempt, "ok", latency, f"Retrieved {len(results)} KB articles")
                return results, calls, None
            except AdapterError as exc:
                latency = (time.perf_counter() - start) * 1000
                last_error = str(exc)
                calls.append({"name": "internal_kb.search", "attempt": attempt, "status": "error", "latency_ms": latency, "message": last_error})
                await self.trace_service.tool_call(run_id, trace_id, ticket_id, "knowledge_retriever", "internal_kb.search", attempt, "error", latency, last_error)
        return [], calls, {"node": "knowledge_retriever", "error": last_error, "attempts": self.max_attempts}


class KnowledgeQualityService:
    """Deterministic KB quality auditor for local/mock support escalation evidence."""

    def __init__(
        self,
        store: JsonStateStore,
        tickets: TicketService,
        audit: AuditService,
        leadership: LeadershipScorecardService,
        kb_fixture_path: Path,
        refresh_plan_dir: Path,
        incident_narrative_dir: Path,
    ):
        self.store = store
        self.tickets = tickets
        self.audit = audit
        self.leadership = leadership
        self.kb_fixture_path = kb_fixture_path
        self.refresh_plan_dir = refresh_plan_dir
        self.incident_narrative_dir = incident_narrative_dir

    async def audit_quality(self) -> dict[str, Any]:
        await self.tickets.list()
        state = await self.store.load()
        articles = self._load_articles()
        ticket_types = self._ticket_types(state)
        article_quality = [self._article_quality(article) for article in articles]
        coverage = self._coverage(ticket_types, articles, state)
        freshness = self._freshness(article_quality)
        citations = self._citations(article_quality)
        conflicts = self._conflicts(article_quality, state)
        weak_or_missing = self._weak_or_missing(coverage, article_quality, conflicts)
        impacted_ticket_types = self._impacted_ticket_types(weak_or_missing, coverage, state)
        replay_signals = self._replay_kb_modifier_signals(state)
        incident_signals = self._incident_narrative_signals()
        leadership_signal = await self._leadership_signal()
        high_impact_gaps = [
            item
            for item in weak_or_missing
            if item["ticket_type"] in HIGH_IMPACT_CATEGORIES or item["impact"] == "high"
        ]
        risk_flags = self._risk_flags(
            freshness,
            citations,
            conflicts,
            high_impact_gaps,
            replay_signals,
            leadership_signal,
        )
        score = self._coverage_score(
            coverage,
            freshness,
            citations,
            conflicts,
            high_impact_gaps,
            replay_signals,
        )
        readiness_status = self._readiness_status(score, risk_flags)
        owner_recommendations = self._owner_recommendations(
            weak_or_missing,
            conflicts,
            impacted_ticket_types,
            leadership_signal,
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "local-deterministic-knowledge-quality-auditor",
            "kb_coverage_score": score,
            "readiness_status": readiness_status,
            "metrics": {
                "coverage": coverage["metrics"],
                "freshness": freshness,
                "citations": citations,
                "conflicts": {
                    "conflict_count": len(conflicts),
                    "conflicts": conflicts,
                },
                "retrieval_evidence": self._retrieval_metrics(state),
                "high_impact_gap_count": len(high_impact_gaps),
            },
            "weak_or_missing_articles": weak_or_missing,
            "impacted_ticket_types": impacted_ticket_types,
            "owner_recommendations": owner_recommendations,
            "risk_flags": risk_flags,
            "article_quality": article_quality,
            "evidence_sources": {
                "kb_fixture": str(self.kb_fixture_path),
                "workflow_retrieval_runs": coverage["workflow_retrieval_runs"],
                "ticket_type_sources": coverage["ticket_type_sources"],
                "replay_kb_context_modifiers": replay_signals,
                "policy_guardrail_signal": self._policy_guardrail_signal(),
                "incident_narrative_signal": incident_signals,
                "leadership_scorecard_signal": leadership_signal,
            },
            "local_commands": LOCAL_COMMANDS,
        }

    async def export_refresh_plan(self) -> dict[str, Any]:
        audit = await self.audit_quality()
        generated_at = datetime.now(timezone.utc)
        plan_id = f"kb_refresh_{generated_at.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        tasks = self._refresh_tasks(audit)
        plan = {
            "plan_id": plan_id,
            "generated_at": generated_at.isoformat(),
            "readiness_status": audit["readiness_status"],
            "kb_coverage_score": audit["kb_coverage_score"],
            "summary": self._plan_summary(audit, tasks),
            "article_refresh_tasks": tasks,
            "owners": sorted({task["owner"] for task in tasks}),
            "acceptance_criteria": self._acceptance_criteria(audit),
            "impacted_workflows": self._impacted_workflows(audit),
            "risk_flags": audit["risk_flags"],
            "source_audit": audit,
            "local_commands": LOCAL_COMMANDS,
            "jd_skills_demonstrated": self._jd_skills(),
            "interviewer_talking_points": self._talking_points(audit),
        }
        markdown = self._markdown(plan)
        json_path, markdown_path = self._write_plan(plan_id, plan, markdown)
        plan["artifact_paths"] = {
            "kb_refresh_plan_json": str(json_path),
            "kb_refresh_plan_markdown": str(markdown_path),
        }
        json_path.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
        await self.audit.record(
            AuditEvent(
                actor="knowledge-quality",
                action="knowledge.refresh_plan_exported",
                resource_type="kb_refresh_plan",
                resource_id=plan_id,
                metadata={"markdown_path": str(markdown_path), "json_path": str(json_path)},
            )
        )
        return {
            "plan_id": plan_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "readiness_status": audit["readiness_status"],
            "kb_coverage_score": audit["kb_coverage_score"],
            "plan": plan,
            "markdown": markdown,
        }

    def _load_articles(self) -> list[dict[str, Any]]:
        rows = json.loads(self.kb_fixture_path.read_text(encoding="utf-8"))
        return [dict(row) for row in rows]

    def _ticket_types(self, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        ticket_types: dict[str, dict[str, Any]] = {}
        for name, tags in CATEGORY_TAGS.items():
            ticket_types[name] = {
                "tags": set(tags),
                "ticket_count": 0,
                "run_count": 0,
                "sources": ["taxonomy"],
            }
        tickets = state["tickets"]
        for ticket in tickets.values():
            inferred = self._infer_ticket_type(ticket)
            ticket_types[inferred]["ticket_count"] += 1
            ticket_types[inferred]["sources"].append(f"ticket:{ticket.get('ticket_id')}")
            ticket_types[inferred]["tags"].update(tag.lower() for tag in ticket.get("tags", []))
        for run in state["runs"].values():
            category = run.get("state", {}).get("classification", {}).get("category")
            mapped = self._map_category(category)
            ticket_types[mapped]["run_count"] += 1
            ticket_types[mapped]["sources"].append(f"run:{run.get('run_id')}")
        return ticket_types

    def _infer_ticket_type(self, ticket: dict[str, Any]) -> str:
        text = f"{ticket.get('subject', '')} {ticket.get('body', '')} {' '.join(ticket.get('tags', []))}".lower()
        scores = {
            category: sum(1 for tag in tags if tag.replace("_", " ") in text or tag in text)
            for category, tags in CATEGORY_TAGS.items()
        }
        best = max(scores, key=scores.get)
        return best if scores[best] else "general_support"

    def _map_category(self, category: str | None) -> str:
        return {
            "bug": "api_integrations",
            "authentication": "authentication",
            "billing": "billing",
            "api_integrations": "api_integrations",
            "security_privacy": "security_privacy",
            "incident": "incident",
            "how_to": "how_to",
        }.get(category or "", "general_support")

    def _article_quality(self, article: dict[str, Any]) -> dict[str, Any]:
        article_id = article["article_id"]
        tags = {tag.lower() for tag in article.get("tags", [])}
        updated_at = article.get("updated_at") or article.get("last_reviewed_at")
        freshness_days = self._age_days(updated_at)
        citations = article.get("citations") or article.get("sources") or []
        has_inline_citation = bool(re.search(r"https?://|KB-\d+|runbook|policy", article.get("content", ""), re.I))
        missing_citations = not citations and not has_inline_citation
        matched_ticket_types = [
            category
            for category, category_tags in CATEGORY_TAGS.items()
            if tags & category_tags
        ] or ["general_support"]
        issues = []
        if freshness_days is None:
            issues.append("missing_review_date")
        elif freshness_days > 180:
            issues.append("stale_review_date")
        if missing_citations:
            issues.append("missing_citations")
        if len(article.get("content", "").split()) < 18:
            issues.append("thin_guidance")
        return {
            "article_id": article_id,
            "title": article["title"],
            "tags": sorted(tags),
            "matched_ticket_types": matched_ticket_types,
            "freshness_days": freshness_days,
            "freshness_status": self._freshness_status(freshness_days),
            "citation_count": len(citations) + (1 if has_inline_citation else 0),
            "missing_citations": missing_citations,
            "issues": issues,
        }

    def _age_days(self, value: str | None) -> int | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed).days

    def _freshness_status(self, freshness_days: int | None) -> str:
        if freshness_days is None:
            return "unknown"
        if freshness_days <= 90:
            return "fresh"
        if freshness_days <= 180:
            return "review_soon"
        return "stale"

    def _coverage(
        self,
        ticket_types: dict[str, dict[str, Any]],
        articles: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        type_rows = {}
        retrieval_article_ids = {
            item.get("article_id")
            for run in state["runs"].values()
            for item in run.get("state", {}).get("kb_results", [])
            if item.get("article_id")
        }
        for ticket_type, info in ticket_types.items():
            tags = info["tags"]
            matched = [
                article
                for article in articles
                if {tag.lower() for tag in article.get("tags", [])} & tags
            ]
            retrieved = [
                article["article_id"]
                for article in matched
                if article["article_id"] in retrieval_article_ids
            ]
            type_rows[ticket_type] = {
                "ticket_type": ticket_type,
                "ticket_count": info["ticket_count"],
                "run_count": info["run_count"],
                "article_ids": [article["article_id"] for article in matched],
                "retrieved_article_ids": retrieved,
                "status": "covered" if matched else "missing",
            }
        covered = sum(1 for item in type_rows.values() if item["status"] == "covered")
        required = len(type_rows)
        return {
            "ticket_types": type_rows,
            "metrics": {
                "required_ticket_types": required,
                "covered_ticket_types": covered,
                "coverage_percent": round((covered / required) * 100, 2) if required else 100.0,
                "retrieved_article_count": len(retrieval_article_ids),
            },
            "workflow_retrieval_runs": [
                {
                    "run_id": run.get("run_id"),
                    "ticket_id": run.get("ticket_id"),
                    "retrieved_article_ids": [
                        item.get("article_id") for item in run.get("state", {}).get("kb_results", [])
                    ],
                }
                for run in state["runs"].values()
                if run.get("state", {}).get("kb_results")
            ],
            "ticket_type_sources": {
                name: list(dict.fromkeys(str(source) for source in info["sources"]))[:8]
                for name, info in ticket_types.items()
            },
        }

    def _freshness(self, article_quality: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(article_quality) or 1
        counts = Counter(item["freshness_status"] for item in article_quality)
        fresh_or_review_soon = counts["fresh"] + counts["review_soon"]
        return {
            "fresh_article_count": counts["fresh"],
            "review_soon_article_count": counts["review_soon"],
            "stale_article_count": counts["stale"],
            "unknown_freshness_count": counts["unknown"],
            "freshness_percent": round((fresh_or_review_soon / total) * 100, 2),
        }

    def _citations(self, article_quality: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(article_quality) or 1
        cited = len([item for item in article_quality if not item["missing_citations"]])
        return {
            "cited_article_count": cited,
            "missing_citation_count": total - cited,
            "citation_percent": round((cited / total) * 100, 2),
        }

    def _conflicts(
        self,
        article_quality: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        articles = {item["article_id"]: item for item in self._load_articles()}
        conflicts = []
        for article in articles.values():
            content = article.get("content", "").lower()
            tags = {tag.lower() for tag in article.get("tags", [])}
            if "immediate escalation" in content and "approval" not in content:
                conflicts.append(
                    {
                        "conflict_id": "policy_vs_immediate_escalation",
                        "article_ids": [article["article_id"]],
                        "severity": "medium",
                        "reason": "Article recommends immediate escalation without citing approval guardrails.",
                        "ticket_types": sorted(self._types_for_tags(tags)),
                    }
                )
        for run in state["runs"].values():
            kb_results = run.get("state", {}).get("kb_results", [])
            for item in kb_results:
                text = f"{item.get('title', '')} {item.get('content', '')}".lower()
                if "conflict" in text or "older mitigation" in text:
                    conflicts.append(
                        {
                            "conflict_id": "workflow_retrieved_conflicting_guidance",
                            "article_ids": [item.get("article_id", "unknown")],
                            "severity": "high",
                            "reason": "Workflow retrieval evidence includes explicitly conflicting guidance.",
                            "ticket_types": [self._map_category(run.get("state", {}).get("classification", {}).get("category"))],
                            "run_id": run.get("run_id"),
                        }
                    )
        return conflicts

    def _types_for_tags(self, tags: set[str]) -> set[str]:
        return {
            category
            for category, category_tags in CATEGORY_TAGS.items()
            if tags & category_tags
        } or {"general_support"}

    def _weak_or_missing(
        self,
        coverage: dict[str, Any],
        article_quality: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        quality_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in article_quality:
            for ticket_type in item["matched_ticket_types"]:
                quality_by_type[ticket_type].append(item)
        conflict_types = {
            ticket_type
            for conflict in conflicts
            for ticket_type in conflict.get("ticket_types", [])
        }
        rows = []
        for ticket_type, item in coverage["ticket_types"].items():
            if item["status"] == "missing":
                rows.append(
                    {
                        "ticket_type": ticket_type,
                        "article_id": None,
                        "title": "Missing article",
                        "status": "missing",
                        "impact": self._impact(ticket_type, item["ticket_count"], item["run_count"]),
                        "reasons": ["No local KB article maps to this ticket type."],
                    }
                )
                continue
            weak_articles = [
                article
                for article in quality_by_type.get(ticket_type, [])
                if article["issues"] or ticket_type in conflict_types
            ]
            for article in weak_articles:
                reasons = list(article["issues"])
                if ticket_type in conflict_types:
                    reasons.append("potential_conflicting_guidance")
                rows.append(
                    {
                        "ticket_type": ticket_type,
                        "article_id": article["article_id"],
                        "title": article["title"],
                        "status": "weak",
                        "impact": self._impact(ticket_type, item["ticket_count"], item["run_count"]),
                        "reasons": list(dict.fromkeys(reasons)),
                    }
                )
        return sorted(
            rows,
            key=lambda row: ({"high": 0, "medium": 1, "low": 2}[row["impact"]], row["ticket_type"]),
        )

    def _impact(self, ticket_type: str, ticket_count: int, run_count: int) -> str:
        if ticket_type in HIGH_IMPACT_CATEGORIES or ticket_count + run_count >= 2:
            return "high"
        if ticket_count + run_count == 1:
            return "medium"
        return "low"

    def _impacted_ticket_types(
        self,
        weak_or_missing: list[dict[str, Any]],
        coverage: dict[str, Any],
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in weak_or_missing:
            by_type[item["ticket_type"]].append(item)
        rows = []
        for ticket_type, items in by_type.items():
            metrics = coverage["ticket_types"][ticket_type]
            affected_runs = [
                run.get("run_id")
                for run in state["runs"].values()
                if self._map_category(run.get("state", {}).get("classification", {}).get("category"))
                == ticket_type
            ]
            rows.append(
                {
                    "ticket_type": ticket_type,
                    "impact": max((item["impact"] for item in items), key={"low": 0, "medium": 1, "high": 2}.get),
                    "ticket_count": metrics["ticket_count"],
                    "run_count": metrics["run_count"],
                    "affected_run_ids": affected_runs[:8],
                    "article_ids": metrics["article_ids"],
                    "top_reasons": list(dict.fromkeys(reason for item in items for reason in item["reasons"]))[:5],
                }
            )
        return sorted(rows, key=lambda row: ({"high": 0, "medium": 1, "low": 2}[row["impact"]], row["ticket_type"]))

    def _retrieval_metrics(self, state: dict[str, Any]) -> dict[str, Any]:
        runs = list(state["runs"].values())
        with_kb = [run for run in runs if run.get("state", {}).get("kb_results")]
        missing_kb = [
            run.get("run_id")
            for run in runs
            if not run.get("state", {}).get("kb_results")
            or (run.get("state", {}).get("failure_state") or {}).get("node") == "knowledge_retriever"
        ]
        return {
            "run_count": len(runs),
            "runs_with_kb_results": len(with_kb),
            "runs_missing_kb_results": len(missing_kb),
            "missing_kb_run_ids": missing_kb[:8],
        }

    def _replay_kb_modifier_signals(self, state: dict[str, Any]) -> dict[str, Any]:
        run_count = len(state["runs"])
        missing_runs = self._retrieval_metrics(state)["runs_missing_kb_results"]
        return {
            "supported_modifiers": ["full", "missing", "conflicting"],
            "missing_context_run_count": missing_runs,
            "conflicting_context_policy": "Replay Lab inserts conflicting KB context to force operator review.",
            "risk_weight": min(25, missing_runs * 5 + (8 if run_count else 0)),
        }

    def _policy_guardrail_signal(self) -> dict[str, Any]:
        return {
            "rule_id": "missing_or_conflicting_kb_context",
            "owner": "knowledge_owner",
            "effect": "block_until_grounded",
            "customer_visible_actions": ["customer_reply", "zendesk_update"],
        }

    def _incident_narrative_signals(self) -> dict[str, Any]:
        latest = self._latest_file(self.incident_narrative_dir)
        if not latest:
            return {"latest_artifact_path": None, "uses_incident_narratives": False}
        return {
            "latest_artifact_path": str(latest),
            "uses_incident_narratives": True,
            "signal": "High-impact KB gaps are prioritized when incident narratives exist.",
        }

    async def _leadership_signal(self) -> dict[str, Any]:
        try:
            scorecard = await self.leadership.scorecard()
        except Exception as exc:
            return {"available": False, "error": str(exc)}
        relevant_flags = [
            flag
            for flag in scorecard.get("risk_flags", [])
            if any(term in flag for term in ["replay", "operator_readiness", "policy", "sla"])
        ]
        return {
            "available": True,
            "overall_score": scorecard["overall_score"],
            "readiness_status": scorecard["readiness_status"],
            "relevant_risk_flags": relevant_flags[:8],
            "recommended_actions": scorecard["recommended_actions"][:5],
        }

    def _risk_flags(
        self,
        freshness: dict[str, Any],
        citations: dict[str, Any],
        conflicts: list[dict[str, Any]],
        high_impact_gaps: list[dict[str, Any]],
        replay_signals: dict[str, Any],
        leadership_signal: dict[str, Any],
    ) -> list[str]:
        flags = []
        if freshness["freshness_percent"] < 70:
            flags.append("kb_freshness_below_threshold")
        if citations["citation_percent"] < 80:
            flags.append("missing_kb_citations")
        if conflicts:
            flags.append("conflicting_guidance_detected")
        if high_impact_gaps:
            flags.append("high_impact_kb_gaps")
        if replay_signals["missing_context_run_count"]:
            flags.append("workflow_runs_missing_kb_context")
        if leadership_signal.get("available") and leadership_signal.get("readiness_status") != "leadership_ready":
            flags.append("leadership_scorecard_has_readiness_risk")
        return list(dict.fromkeys(flags))

    def _coverage_score(
        self,
        coverage: dict[str, Any],
        freshness: dict[str, Any],
        citations: dict[str, Any],
        conflicts: list[dict[str, Any]],
        high_impact_gaps: list[dict[str, Any]],
        replay_signals: dict[str, Any],
    ) -> int:
        score = (
            coverage["metrics"]["coverage_percent"] * 0.45
            + freshness["freshness_percent"] * 0.20
            + citations["citation_percent"] * 0.20
            + max(0, 100 - replay_signals["risk_weight"]) * 0.15
        )
        score -= min(20, len(conflicts) * 7)
        score -= min(18, len(high_impact_gaps) * 2)
        return max(0, min(100, round(score)))

    def _readiness_status(self, score: int, risk_flags: list[str]) -> str:
        blocking = {"conflicting_guidance_detected", "high_impact_kb_gaps"}
        if score < 60 or blocking & set(risk_flags):
            return "not_ready_refresh_required"
        if score < 80 or risk_flags:
            return "review_ready_with_kb_risks"
        return "ready_for_agentic_escalation"

    def _owner_recommendations(
        self,
        weak_or_missing: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        impacted_ticket_types: list[dict[str, Any]],
        leadership_signal: dict[str, Any],
    ) -> list[dict[str, str]]:
        recommendations = []
        for item in impacted_ticket_types[:6]:
            owner = self._owner_for_type(item["ticket_type"])
            recommendations.append(
                {
                    "owner": owner,
                    "recommendation": (
                        f"Refresh {item['ticket_type']} KB coverage for "
                        f"{', '.join(item['top_reasons'][:3])}."
                    ),
                    "impact": item["impact"],
                }
            )
        if conflicts:
            recommendations.append(
                {
                    "owner": "Knowledge Owner",
                    "recommendation": "Resolve conflicting guidance against policy guardrails before customer-visible automation.",
                    "impact": "high",
                }
            )
        if weak_or_missing:
            recommendations.append(
                {
                    "owner": "Support Enablement",
                    "recommendation": "Add review dates and source citations to every weak article in the refresh plan.",
                    "impact": "medium",
                }
            )
        if leadership_signal.get("available") and leadership_signal.get("recommended_actions"):
            recommendations.append(
                {
                    "owner": "Support Operations",
                    "recommendation": leadership_signal["recommended_actions"][0],
                    "impact": "medium",
                }
            )
        return recommendations

    def _owner_for_type(self, ticket_type: str) -> str:
        return {
            "authentication": "Identity Support Lead",
            "billing": "Billing Operations Lead",
            "api_integrations": "Developer Support Lead",
            "security_privacy": "Security and Compliance Owner",
            "incident": "Incident Commander",
            "how_to": "Support Enablement",
            "general_support": "Support QA Lead",
        }.get(ticket_type, "Knowledge Owner")

    def _refresh_tasks(self, audit: dict[str, Any]) -> list[dict[str, Any]]:
        tasks = []
        seen = set()
        for item in audit["weak_or_missing_articles"]:
            key = (item["ticket_type"], item["article_id"] or "new")
            if key in seen:
                continue
            seen.add(key)
            task_id = f"kb_task_{len(tasks) + 1:02d}"
            article_id = item["article_id"] or f"NEW-{item['ticket_type'].upper()}"
            tasks.append(
                {
                    "task_id": task_id,
                    "article_id": article_id,
                    "title": item["title"],
                    "ticket_type": item["ticket_type"],
                    "owner": self._owner_for_type(item["ticket_type"]),
                    "priority": item["impact"],
                    "refresh_actions": self._refresh_actions(item),
                    "acceptance_criteria": [
                        "Article has an owner, last-reviewed date, and next-review cadence.",
                        "Article cites source-of-truth policy, runbook, or incident evidence.",
                        "Workflow retrieval returns the article for representative sample tickets.",
                        "Replay Lab missing/conflicting KB scenarios are acknowledged in operator guidance.",
                    ],
                    "impacted_workflows": self._workflows_for_type(item["ticket_type"]),
                }
            )
        return tasks

    def _refresh_actions(self, item: dict[str, Any]) -> list[str]:
        actions = []
        reasons = item["reasons"]
        if item["status"] == "missing":
            actions.append("Create a source-of-truth article for this ticket type.")
        if "missing_review_date" in reasons or "stale_review_date" in reasons:
            actions.append("Add a reviewed_at date and review cadence.")
        if "missing_citations" in reasons:
            actions.append("Add citations to policy, runbook, incident, or product source material.")
        if "potential_conflicting_guidance" in reasons:
            actions.append("Resolve conflict with approval policy and mark the current guidance authoritative.")
        if "thin_guidance" in reasons:
            actions.append("Expand symptoms, evidence to collect, escalation owner, and safe customer language.")
        return actions or ["Review article quality and confirm retrieval grounding."]

    def _workflows_for_type(self, ticket_type: str) -> list[str]:
        base = ["knowledge_retriever", "qa_evaluator", "human_approval", "policy_guardrails"]
        if ticket_type in {"authentication", "api_integrations", "incident"}:
            return [*base, "engineering_escalation_drafter", "incident_narrative"]
        if ticket_type == "security_privacy":
            return [*base, "customer_reply_drafter", "incident_narrative"]
        return [*base, "customer_reply_drafter"]

    def _acceptance_criteria(self, audit: dict[str, Any]) -> list[str]:
        return [
            "KB coverage score is at least 80 with no high-impact missing articles.",
            "Freshness is at least 70 percent and every high-impact article has a review date.",
            "Citation coverage is at least 80 percent with policy/runbook sources for customer-visible guidance.",
            "No unresolved conflict remains between KB text and policy guardrail requirements.",
            "Demo run prints KB readiness and the exported refresh plan path.",
        ]

    def _impacted_workflows(self, audit: dict[str, Any]) -> list[str]:
        workflows = set()
        for item in audit["impacted_ticket_types"]:
            workflows.update(self._workflows_for_type(item["ticket_type"]))
        return sorted(workflows)

    def _plan_summary(self, audit: dict[str, Any], tasks: list[dict[str, Any]]) -> str:
        return (
            f"KB readiness is `{audit['readiness_status']}` with coverage score "
            f"{audit['kb_coverage_score']} and {len(tasks)} owner-ready refresh tasks."
        )

    def _jd_skills(self) -> list[str]:
        return [
            "Knowledge quality evaluation for agentic support escalation readiness.",
            "FastAPI product endpoints with deterministic local/mock scoring and artifact export.",
            "Evidence-driven governance across workflow retrieval, replay, policy, incident, and KPI signals.",
            "Owner-ready operational planning with Markdown and JSON deliverables.",
            "Testable support leadership metrics for freshness, coverage, conflicts, citations, and gaps.",
        ]

    def _talking_points(self, audit: dict[str, Any]) -> list[str]:
        return [
            (
                f"The auditor reports KB readiness as `{audit['readiness_status']}` with score "
                f"{audit['kb_coverage_score']}."
            ),
            "It combines local KB snippets with actual workflow retrieval evidence rather than only static docs.",
            "Replay Lab missing/conflicting KB modes are represented as readiness risk before automation expansion.",
            "Policy guardrails and incident narratives turn KB issues into owner and workflow impact, not just lint.",
            "The refresh plan gives support leaders tasks, owners, acceptance criteria, commands, and interview evidence.",
        ]

    def _write_plan(
        self,
        plan_id: str,
        plan: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.refresh_plan_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.refresh_plan_dir / f"{plan_id}.json"
        markdown_path = self.refresh_plan_dir / f"{plan_id}.md"
        json_path.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _markdown(self, plan: dict[str, Any]) -> str:
        tasks = [
            (
                f"- {task['task_id']} | {task['priority']} | {task['owner']} | "
                f"{task['article_id']} | {task['ticket_type']}: "
                f"{'; '.join(task['refresh_actions'])}"
            )
            for task in plan["article_refresh_tasks"]
        ] or ["- No refresh tasks required."]
        owners = [f"- {owner}" for owner in plan["owners"]] or ["- None"]
        criteria = [f"- {item}" for item in plan["acceptance_criteria"]]
        workflows = [f"- {item}" for item in plan["impacted_workflows"]]
        commands = [f"- `{command}`" for command in plan["local_commands"]]
        skills = [f"- {skill}" for skill in plan["jd_skills_demonstrated"]]
        talking_points = [f"- {point}" for point in plan["interviewer_talking_points"]]
        risks = [f"- {flag}" for flag in plan["risk_flags"]] or ["- None"]
        return "\n".join(
            [
                f"# KB Refresh Plan: {plan['plan_id']}",
                "",
                "## Summary",
                plan["summary"],
                "",
                "## Readiness",
                f"- Status: {plan['readiness_status']}",
                f"- KB coverage score: {plan['kb_coverage_score']}",
                "",
                "## Article Refresh Tasks",
                *tasks,
                "",
                "## Owners",
                *owners,
                "",
                "## Acceptance Criteria",
                *criteria,
                "",
                "## Impacted Workflows",
                *workflows,
                "",
                "## Risk Flags",
                *risks,
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

    def _latest_file(self, directory: Path) -> Path | None:
        if not directory.exists():
            return None
        files = sorted(directory.glob("*.md"), key=lambda item: item.stat().st_mtime)
        return files[-1] if files else None
