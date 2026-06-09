from app.core.storage import JsonStateStore


class MetricsService:
    def __init__(self, store: JsonStateStore):
        self.store = store

    async def record_node_metrics(self, node: str, latency_ms: float, tokens: int = 0, cost_usd: float = 0.0) -> None:
        def mutate(state):
            item = state["metrics"].setdefault("node_metrics", {}).setdefault(node, {"count": 0, "latency_ms": 0.0, "tokens": 0, "cost_usd": 0.0})
            item["count"] += 1
            item["latency_ms"] += latency_ms
            item["tokens"] += tokens
            item["cost_usd"] += cost_usd
            state["metrics"]["cost_usd"] = state["metrics"].get("cost_usd", 0.0) + cost_usd

        await self.store.update(mutate)

    async def agent_performance(self) -> dict:
        state = await self.store.load()
        runs = list(state["runs"].values())
        approvals = list(state["approvals"].values())
        outbox = list(state["outbox"].values())
        drills = list(state["drills"].values())
        nodes = {}
        total_node_count = 0
        total_latency_ms = 0.0
        total_tokens = 0
        total_cost_usd = state["metrics"].get("cost_usd", 0.0)
        for node, data in state["metrics"].get("node_metrics", {}).items():
            count = data.get("count") or 1
            total_node_count += data.get("count", 0)
            total_latency_ms += data.get("latency_ms", 0.0)
            total_tokens += data.get("tokens", 0)
            nodes[node] = {**data, "avg_latency_ms": round(data.get("latency_ms", 0.0) / count, 2)}
        run_count = len(runs)
        failure_count = len([r for r in runs if r.get("failure_state")])
        tool_failure_count = sum(
            1
            for events in state["traces"].values()
            for event in events
            if event.get("event_type") == "tool_call" and event.get("status") == "error"
        )
        outbox_by_action = {}
        for event in outbox:
            action = event.get("action_type", "unknown")
            outbox_by_action[action] = outbox_by_action.get(action, 0) + 1
        return {
            "run_count": run_count,
            "total_runs": run_count,
            "completed_runs": len([r for r in runs if r["status"] == "completed"]),
            "pending_approval_runs": len([r for r in runs if r["status"] in {"awaiting_approval", "pending_approval"}]),
            "approval_count": len(approvals),
            "pending_approvals": len([a for a in approvals if a["status"] == "pending"]),
            "outbox_dispatch_count": len(outbox),
            "outbox_dispatch_counts": outbox_by_action,
            "failure_count": failure_count,
            "tool_failure_count": tool_failure_count,
            "failure_drill_count": len(drills),
            "avg_node_latency_ms": round(total_latency_ms / total_node_count, 2) if total_node_count else 0.0,
            "avg_tokens_per_run": round(total_tokens / run_count, 2) if run_count else 0.0,
            "avg_cost_usd_per_run": round(total_cost_usd / run_count, 6) if run_count else 0.0,
            "estimated_cost_usd": round(total_cost_usd, 6),
            "node_metrics": nodes,
        }
