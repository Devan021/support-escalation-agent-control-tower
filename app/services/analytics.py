import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.storage import JsonStateStore


class AnalyticsService:
    def __init__(self, store: JsonStateStore, reports_dir: Path, briefs_dir: Path):
        self.store = store
        self.reports_dir = reports_dir
        self.briefs_dir = briefs_dir

    async def ops_snapshot(self) -> dict[str, Any]:
        state = await self.store.load()
        tickets = list(state["tickets"].values())
        runs = list(state["runs"].values())
        approvals = list(state["approvals"].values())
        outbox = list(state["outbox"].values())
        drills = list(state["drills"].values())
        traces = state["traces"]
        node_metrics = state["metrics"].get("node_metrics", {})

        ticket_category_counts = Counter()
        sla_risk_counts = Counter()
        final_action_counts = Counter()
        failure_type_counts = Counter()
        ticket_latest_run: dict[str, dict[str, Any]] = {}

        for run in runs:
            workflow_state = run.get("state", {})
            category = workflow_state.get("classification", {}).get("category", "uncategorized")
            sla_level = workflow_state.get("sla_risk", {}).get("level", "unknown")
            ticket_category_counts[category] += 1
            sla_risk_counts[sla_level] += 1
            final_action_counts[run.get("final_action") or "none"] += 1
            failure_type_counts.update(self._failure_types(run))
            ticket_latest_run[run["ticket_id"]] = run

        for ticket in tickets:
            if ticket["ticket_id"] not in ticket_latest_run:
                ticket_category_counts["unanalyzed"] += 1

        approval_status_counts = Counter(item.get("status", "unknown") for item in approvals)
        outbox_destination_counts = Counter(item.get("destination", "unknown") for item in outbox)
        outbox_action_counts = Counter(item.get("action_type", "unknown") for item in outbox)
        ticket_status_counts = Counter(item.get("status", "unknown") for item in tickets)

        total_node_count = sum(item.get("count", 0) for item in node_metrics.values())
        total_latency_ms = sum(item.get("latency_ms", 0.0) for item in node_metrics.values())
        total_tokens = sum(item.get("tokens", 0) for item in node_metrics.values())
        total_cost_usd = state["metrics"].get("cost_usd", 0.0)
        run_count = len(runs)

        snapshot = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary_metrics": {
                "ticket_count": len(tickets),
                "run_count": run_count,
                "approval_count": len(approvals),
                "pending_approval_count": approval_status_counts.get("pending", 0),
                "outbox_dispatch_count": len(outbox),
                "failure_count": sum(failure_type_counts.values()),
                "drill_count": len(drills),
                "incident_brief_count": len(self._incident_brief_paths()),
            },
            "counts": {
                "ticket_category": dict(sorted(ticket_category_counts.items())),
                "ticket_status": dict(sorted(ticket_status_counts.items())),
                "sla_risk": dict(sorted(sla_risk_counts.items())),
                "final_action": dict(sorted(final_action_counts.items())),
                "approval_status": dict(sorted(approval_status_counts.items())),
                "outbox_destination": dict(sorted(outbox_destination_counts.items())),
                "outbox_action": dict(sorted(outbox_action_counts.items())),
                "failure_type": dict(sorted(failure_type_counts.items())),
            },
            "averages": {
                "latency_ms_per_node": round(total_latency_ms / total_node_count, 2)
                if total_node_count
                else 0.0,
                "latency_ms_per_run": round(total_latency_ms / run_count, 2) if run_count else 0.0,
                "tokens_per_run": round(total_tokens / run_count, 2) if run_count else 0.0,
                "cost_usd_per_run": round(total_cost_usd / run_count, 6) if run_count else 0.0,
            },
            "top_risky_tickets": self._top_risky_tickets(tickets, runs, approvals),
            "sla_queue_highlights": self._sla_queue_highlights(drills),
            "failure_drill_summary": self._failure_drill_summary(drills, traces),
            "outbox_dispatch_summary": self._outbox_summary(outbox),
            "incident_briefs": self._incident_brief_paths(),
        }
        snapshot["recommended_operational_actions"] = self._recommended_actions(snapshot)
        return snapshot

    async def export_weekly_review(self) -> dict[str, Any]:
        snapshot = await self.ops_snapshot()
        generated_at = datetime.now(timezone.utc)
        report_id = f"weekly_review_{generated_at.strftime('%Y%m%d_%H%M%S')}"
        review = {
            "report_id": report_id,
            "generated_at": generated_at.isoformat(),
            "summary_metrics": snapshot["summary_metrics"],
            "counts": snapshot["counts"],
            "averages": snapshot["averages"],
            "sla_queue_highlights": snapshot["sla_queue_highlights"],
            "failure_drill_summary": snapshot["failure_drill_summary"],
            "outbox_dispatch_summary": snapshot["outbox_dispatch_summary"],
            "incident_briefs": snapshot["incident_briefs"],
            "top_risky_tickets": snapshot["top_risky_tickets"],
            "next_actions": snapshot["recommended_operational_actions"],
        }
        markdown = self._weekly_markdown(review)
        json_path, markdown_path = self._write_report(report_id, review, markdown)
        return {
            "report_id": report_id,
            "format": "markdown+json",
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "review": review,
            "markdown": markdown,
        }

    def _top_risky_tickets(
        self,
        tickets: list[dict[str, Any]],
        runs: list[dict[str, Any]],
        approvals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tickets_by_id = {item["ticket_id"]: item for item in tickets}
        approvals_by_run = {item["run_id"]: item for item in approvals}
        rows = []
        for run in runs:
            ticket = tickets_by_id.get(run["ticket_id"], {})
            workflow_state = run.get("state", {})
            sla_risk = workflow_state.get("sla_risk", {})
            classification = workflow_state.get("classification", {})
            approval = approvals_by_run.get(run["run_id"])
            score = float(sla_risk.get("score", 0.0) or 0.0)
            rows.append(
                {
                    "ticket_id": run["ticket_id"],
                    "run_id": run["run_id"],
                    "subject": ticket.get("subject", "unknown"),
                    "customer_tier": ticket.get("customer_tier", "unknown"),
                    "priority": ticket.get("priority", "unknown"),
                    "category": classification.get("category", "uncategorized"),
                    "sla_risk_level": sla_risk.get("level", "unknown"),
                    "sla_risk_score": score,
                    "approval_status": approval.get("status", "none") if approval else "none",
                    "final_action": run.get("final_action") or "none",
                    "recommended_action": self._ticket_action(ticket, run, approval),
                }
            )
        return sorted(
            rows,
            key=lambda item: (
                item["sla_risk_score"],
                item["priority"] == "urgent",
                item["customer_tier"] == "enterprise",
            ),
            reverse=True,
        )[:5]

    def _ticket_action(
        self,
        ticket: dict[str, Any],
        run: dict[str, Any],
        approval: dict[str, Any] | None,
    ) -> str:
        sla_level = run.get("state", {}).get("sla_risk", {}).get("level")
        if approval and approval.get("status") == "pending":
            return "Review pending approval and dispatch the customer or engineering handoff."
        if run.get("failure_state"):
            return "Assign human validation because tool failure reduced confidence."
        if sla_level == "high":
            return "Confirm owner, mitigation path, and customer update cadence."
        if ticket.get("status") == "open":
            return "Analyze and route before the next queue review."
        return "Monitor through standard support follow-up."

    def _failure_types(self, run: dict[str, Any]) -> list[str]:
        failure = run.get("failure_state")
        if not failure:
            return []
        node = failure.get("node", "unknown")
        if node == "knowledge_retriever":
            return ["knowledge_retrieval_retry_exhausted"]
        return [f"{node}_failure"]

    def _sla_queue_highlights(self, drills: list[dict[str, Any]]) -> list[dict[str, Any]]:
        queues = [
            item
            for item in drills
            if item.get("drill_type") == "sla_breach_simulation"
            for item in item.get("queue", [])
        ]
        risk_rank = {"breached": 0, "critical": 1, "warning": 2, "watch": 3}
        return sorted(
            queues,
            key=lambda item: (risk_rank.get(item.get("risk_level"), 99), item.get("minutes_to_sla", 999)),
        )[:10]

    def _failure_drill_summary(
        self,
        drills: list[dict[str, Any]],
        traces: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        failure_drills = [item for item in drills if item.get("drill_type") == "tool_failure"]
        latest = failure_drills[-1] if failure_drills else None
        failed_tool_events = [
            event
            for events in traces.values()
            for event in events
            if event.get("event_type") == "tool_call" and event.get("status") == "error"
        ]
        return {
            "drill_count": len(failure_drills),
            "failed_tool_attempt_count": len(failed_tool_events),
            "latest_run_id": latest.get("run_id") if latest else None,
            "latest_ticket_id": latest.get("ticket_id") if latest else None,
            "latest_failure_count": latest.get("failure_count", 0) if latest else 0,
        }

    def _outbox_summary(self, outbox: list[dict[str, Any]]) -> dict[str, Any]:
        by_status = Counter(item.get("status", "unknown") for item in outbox)
        by_action = Counter(item.get("action_type", "unknown") for item in outbox)
        by_destination = Counter(item.get("destination", "unknown") for item in outbox)
        return {
            "dispatch_count": len(outbox),
            "by_status": dict(sorted(by_status.items())),
            "by_action": dict(sorted(by_action.items())),
            "top_destinations": dict(by_destination.most_common(5)),
        }

    def _incident_brief_paths(self) -> list[dict[str, str]]:
        if not self.briefs_dir.exists():
            return []
        rows = []
        for markdown_path in sorted(self.briefs_dir.glob("*.md")):
            run_id = markdown_path.stem
            json_path = self.briefs_dir / f"{run_id}.json"
            rows.append(
                {
                    "run_id": run_id,
                    "markdown_path": str(markdown_path),
                    "json_path": str(json_path) if json_path.exists() else "",
                }
            )
        return rows

    def _recommended_actions(self, snapshot: dict[str, Any]) -> list[str]:
        actions = []
        summary = snapshot["summary_metrics"]
        counts = snapshot["counts"]
        if summary["pending_approval_count"]:
            actions.append(
                f"Clear {summary['pending_approval_count']} pending approvals, starting with high SLA risk tickets."
            )
        if counts["sla_risk"].get("high", 0):
            actions.append("Review high-risk SLA tickets with support and engineering leads.")
        if summary["failure_count"]:
            actions.append("Review retry-exhausted failures and update KB/tool runbooks.")
        if summary["outbox_dispatch_count"]:
            actions.append("Audit dispatched Zendesk/Jira/Slack handoffs for owner response.")
        if not actions:
            actions.append("Continue monitoring queue health and run the weekly SLA simulator.")
        return actions

    def _write_report(
        self,
        report_id: str,
        review: dict[str, Any],
        markdown: str,
    ) -> tuple[Path, Path]:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.reports_dir / f"{report_id}.json"
        markdown_path = self.reports_dir / f"{report_id}.md"
        json_path.write_text(json.dumps(review, indent=2, default=str), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        return json_path, markdown_path

    def _weekly_markdown(self, review: dict[str, Any]) -> str:
        summary = review["summary_metrics"]
        averages = review["averages"]
        sla_rows = [
            (
                f"- {item['risk_level']}: {item['ticket_id']} "
                f"({item['minutes_to_sla']} min) - {item['recommended_action']}"
            )
            for item in review["sla_queue_highlights"]
        ] or ["- No SLA simulator queue has been recorded yet."]
        failure = review["failure_drill_summary"]
        outbox = review["outbox_dispatch_summary"]
        brief_rows = [
            f"- {item['run_id']}: {item['markdown_path']}" for item in review["incident_briefs"]
        ] or ["- No incident briefs exported yet."]
        risky_rows = [
            (
                f"- {item['ticket_id']} ({item['sla_risk_level']} "
                f"{item['sla_risk_score']}): {item['recommended_action']}"
            )
            for item in review["top_risky_tickets"]
        ] or ["- No analyzed risky tickets yet."]
        next_actions = [f"- {item}" for item in review["next_actions"]]

        return "\n".join(
            [
                f"# Weekly Ops Review: {review['report_id']}",
                "",
                "## Summary Metrics",
                f"- Tickets: {summary['ticket_count']}",
                f"- Runs: {summary['run_count']}",
                f"- Pending approvals: {summary['pending_approval_count']}",
                f"- Outbox dispatches: {summary['outbox_dispatch_count']}",
                f"- Failures: {summary['failure_count']}",
                f"- Average latency per run: {averages['latency_ms_per_run']} ms",
                f"- Average tokens per run: {averages['tokens_per_run']}",
                f"- Average cost per run: ${averages['cost_usd_per_run']:.6f}",
                "",
                "## SLA Queue Highlights",
                *sla_rows,
                "",
                "## Failure Drill Summary",
                f"- Drill count: {failure['drill_count']}",
                f"- Failed tool attempts: {failure['failed_tool_attempt_count']}",
                f"- Latest run: {failure['latest_run_id'] or 'none'}",
                "",
                "## Outbox Dispatch Summary",
                f"- Dispatch count: {outbox['dispatch_count']}",
                f"- By action: {json.dumps(outbox['by_action'], sort_keys=True)}",
                f"- By status: {json.dumps(outbox['by_status'], sort_keys=True)}",
                "",
                "## Incident Brief Links",
                *brief_rows,
                "",
                "## Top Risky Tickets",
                *risky_rows,
                "",
                "## Next Actions",
                *next_actions,
                "",
            ]
        )
