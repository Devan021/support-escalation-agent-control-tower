import asyncio
import json
import time
from pathlib import Path

from app.core.config import Settings
from app.models import TicketCreate
from app.services.factory import ServiceContainer


ROOT = Path(__file__).resolve().parents[2]


async def run_eval() -> None:
    dataset = json.loads((ROOT / "sample_data" / "eval_dataset.json").read_text(encoding="utf-8"))
    state_file = ROOT / "eval_control_tower_state.json"
    if state_file.exists():
        state_file.unlink()
    settings = Settings(
        state_file=state_file,
        api_keys="eval-key",
        demo_api_key="eval-key",
        max_tool_attempts=2,
    )
    container = ServiceContainer(settings)

    total = len(dataset)
    correct_classification = 0
    correct_routing = 0
    approval_pauses = 0
    tool_failures = 0
    started = time.perf_counter()

    for row in dataset:
        ticket = await container.tickets.ingest(TicketCreate(**row["ticket"]))
        run = await container.workflow.analyze_ticket(ticket.ticket_id)
        state = run.state
        if state["classification"]["category"] == row["expected_category"]:
            correct_classification += 1

        expected_escalation = row["expected_route"] == "engineering_escalation"
        actual_escalation = bool(state.get("drafts", {}).get("engineering_escalation"))
        if expected_escalation == actual_escalation:
            correct_routing += 1

        approval_pauses += 1 if run.status == "awaiting_approval" else 0
        tool_failures += 1 if run.failure_state else 0

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    metrics = await container.metrics.agent_performance()
    node_metrics = metrics.get("node_metrics", {})
    token_usage = sum(item.get("tokens", 0) for item in node_metrics.values())
    estimated_cost = metrics.get("estimated_cost_usd", 0.0)
    scenario_pack = await container.scenarios.export_eval_pack()
    scenario_summary = scenario_pack["eval_summary"]
    passed = (
        correct_classification == total
        and correct_routing == total
        and approval_pauses >= total
        and scenario_summary["status"] == "pass"
    )

    print(f"Number of eval tickets: {total}")
    print(f"Classification accuracy: {correct_classification}/{total}")
    print(f"SLA escalation routing accuracy: {correct_routing}/{total}")
    print(f"Approval-pause count: {approval_pauses}")
    print(f"Tool failure handling count: {tool_failures}")
    print(f"Average workflow latency: {round(elapsed_ms / total, 2)} ms")
    print(f"Token usage: {token_usage}")
    print(f"Estimated cost: ${estimated_cost:.6f}")
    print(f"Scenario Dataset scenarios: {scenario_summary['scenario_count']}")
    print(
        "Scenario Dataset classification accuracy: "
        f"{scenario_summary['classification_accuracy']['correct']}/"
        f"{scenario_summary['classification_accuracy']['total']}"
    )
    print(
        "Scenario Dataset SLA routing: "
        f"{scenario_summary['sla_routing']['correct']}/"
        f"{scenario_summary['sla_routing']['total']}"
    )
    print(f"Scenario Dataset Eval Pack: {scenario_pack['markdown_path']}")
    print(f"Pass/fail summary: {'PASS' if passed else 'FAIL'}")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(run_eval())
