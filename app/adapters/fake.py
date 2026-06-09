import asyncio
import json
from pathlib import Path
from typing import Any

from app.models import KnowledgeArticle, Ticket


class AdapterError(RuntimeError):
    pass


class LocalMockLlmProvider:
    async def draft_customer_reply(self, ticket: Ticket, context: list[KnowledgeArticle]) -> dict[str, Any]:
        await asyncio.sleep(0)
        titles = ", ".join(a.title for a in context[:2]) or "our internal runbook"
        text = (
            f"Hi, thanks for reaching out about '{ticket.subject}'. "
            f"We found relevant guidance in {titles}. A support specialist is reviewing this "
            "before any customer-impacting action is taken."
        )
        return {"text": text, "tokens": max(40, len(text.split()) + len(ticket.body.split())), "cost_usd": 0.0}

    async def draft_engineering_escalation(
        self,
        ticket: Ticket,
        classification: dict[str, Any],
        sla_risk: dict[str, Any],
        context: list[KnowledgeArticle],
    ) -> dict[str, Any]:
        await asyncio.sleep(0)
        refs = ", ".join(a.article_id for a in context[:3]) or "none"
        text = (
            f"Escalation for {ticket.ticket_id}: {ticket.subject}\n"
            f"Category: {classification.get('category')} | SLA risk: {sla_risk.get('level')}\n"
            f"Customer tier: {ticket.customer_tier}; priority: {ticket.priority}\n"
            f"Relevant KB: {refs}\nImpact: {ticket.body[:500]}"
        )
        return {"text": text, "tokens": max(55, len(text.split())), "cost_usd": 0.0}


class FakeZendeskAdapter:
    async def update_ticket(self, ticket_id: str, status: str, comment: str | None = None) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"adapter": "zendesk", "ticket_id": ticket_id, "status": status, "comment": comment}


class FakeJiraAdapter:
    async def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"adapter": "jira", "issue_key": "ESC-101", "title": title, "body": body, "labels": labels or []}


class FakeSlackAdapter:
    async def post_message(self, channel: str, text: str | dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"adapter": "slack", "channel": channel, "message_ts": "1710000000.000100", "text": text}


class FakeKnowledgeBaseAdapter:
    def __init__(self, fixture_path: Path):
        self.fixture_path = fixture_path
        self._seen: dict[str, int] = {}

    async def search(self, query: str, tags: list[str], limit: int = 3) -> list[KnowledgeArticle]:
        await asyncio.sleep(0)
        text = query.lower()
        fixture_markers = f"{text} {' '.join(tags).lower()}"
        if "force-kb-failure" in fixture_markers:
            raise AdapterError("Forced internal KB outage for retry testing")
        if "transient-kb-failure" in fixture_markers and self._seen.get(query, 0) < 1:
            self._seen[query] = self._seen.get(query, 0) + 1
            raise AdapterError("Transient internal KB timeout")
        rows = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        terms = {term for term in text.replace("/", " ").split() if len(term) > 2}
        tag_terms = {tag.lower() for tag in tags}
        articles = []
        for row in rows:
            haystack = f"{row['title']} {row['content']} {' '.join(row.get('tags', []))}".lower()
            score = sum(1 for term in terms if term in haystack) + 2 * sum(
                1 for tag in tag_terms if tag in haystack
            )
            if score:
                articles.append(KnowledgeArticle(**row, score=float(score)))
        return sorted(articles or [KnowledgeArticle(**row, score=0.2) for row in rows[:limit]], key=lambda x: x.score, reverse=True)[:limit]
