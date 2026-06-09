import os
from typing import Any

import requests
import streamlit as st


API_BASE = os.getenv("CONTROL_TOWER_API_BASE_URL", "http://127.0.0.1:8000")
API_KEY = os.getenv("CONTROL_TOWER_API_KEY", "demo-control-tower-key")
HEADERS = {"x-api-key": API_KEY}


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    response = requests.request(
        method,
        f"{API_BASE}{path}",
        json=payload,
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


st.set_page_config(page_title="Escalation Control Tower", layout="wide")
st.title("Support Escalation Agent Control Tower")

health = requests.get(f"{API_BASE}/health", timeout=5).json()
st.caption(f"API: {API_BASE} | status: {health.get('status')}")

tabs = st.tabs(
    [
        "Ticket Queue",
        "Analyze Ticket",
        "Run Timeline",
        "Trace Inspector",
        "Approval Panel",
        "Outbox",
        "Reliability",
        "SLA Simulator",
        "Incident Brief",
        "Playbooks / Remediation",
        "Customer Health / Account Brief",
        "Ops Analytics",
        "SLO / Optimization",
        "Demo Scenario / Evidence Pack",
        "Metrics",
        "Audit Events",
        "Operator QA / Readiness Pack",
        "Replay Lab",
        "Policy Guardrails",
        "Incident Narrative",
        "Leadership Scorecard",
        "Knowledge Quality",
        "Launch Checklist",
        "Portfolio Pack",
        "Release Pack",
        "CI Doctor / Audit Pack",
        "Reviewer Quickstart",
        "Artifact Inventory",
        "UI Verification",
        "Final Handoff",
        "Git Readiness",
        "API Contract",
        "Runtime Demo",
        "Scenario Dataset",
        "On-Call Handoff",
        "Postmortem RCA",
    ]
)

with tabs[0]:
    col1, col2 = st.columns([1, 4])
    if col1.button("Load Samples", use_container_width=True):
        api("POST", "/tickets/ingest-samples")
        st.rerun()
    tickets = api("GET", "/tickets")
    col2.metric("Open tickets", len(tickets))
    st.dataframe(
        [
            {
                "ticket_id": item["ticket_id"],
                "subject": item["subject"],
                "priority": item["priority"],
                "tier": item["customer_tier"],
                "status": item["status"],
                "tags": ", ".join(item.get("tags", [])),
            }
            for item in tickets
        ],
        use_container_width=True,
        hide_index=True,
    )

with tabs[1]:
    tickets = api("GET", "/tickets")
    labels = {f"{item['subject']} | {item['ticket_id']}": item["ticket_id"] for item in tickets}
    if labels:
        selected = st.selectbox("Ticket", list(labels))
        if st.button("Analyze", type="primary"):
            run = api("POST", f"/tickets/{labels[selected]}/analyze")
            st.session_state["run_id"] = run["run_id"]
            st.success(f"Run created: {run['run_id']}")
    run_id = st.text_input("Run ID", value=st.session_state.get("run_id", ""))
    if run_id:
        st.json(api("GET", f"/runs/{run_id}"))

with tabs[2]:
    run_id = st.text_input("Timeline run ID", value=st.session_state.get("run_id", ""))
    if run_id:
        trace = api("GET", f"/runs/{run_id}/trace")
        for event in trace:
            st.markdown(
                f"**{event.get('node') or 'workflow'}** · `{event['event_type']}` · "
                f"`{event['status']}` · {round(event.get('latency_ms', 0), 2)} ms"
            )
            if event.get("message"):
                st.caption(event["message"])

with tabs[3]:
    run_id = st.text_input("Trace run ID", value=st.session_state.get("run_id", ""))
    if run_id:
        st.dataframe(api("GET", f"/runs/{run_id}/trace"), use_container_width=True, hide_index=True)

with tabs[4]:
    approvals = api("GET", "/approvals")
    st.dataframe(
        [
            {
                "approval_id": item["approval_id"],
                "run_id": item["run_id"],
                "status": item["status"],
                "reason": item["reason"],
            }
            for item in approvals
        ],
        use_container_width=True,
        hide_index=True,
    )
    if approvals:
        selected = st.selectbox("Pending approval", [f"{a['approval_id']} | {a['run_id']}" for a in approvals])
        approval = approvals[[f"{a['approval_id']} | {a['run_id']}" for a in approvals].index(selected)]
        st.text_area("Customer reply", approval["customer_reply"], height=160)
        if approval["engineering_escalation"]:
            st.text_area("Engineering escalation", approval["engineering_escalation"], height=220)
        note = st.text_input("Reviewer note", value="Reviewed in dashboard")
        left, right = st.columns(2)
        if left.button("Approve", type="primary", use_container_width=True):
            api("POST", f"/runs/{approval['run_id']}/approve", {"decided_by": "dashboard", "note": note})
            st.rerun()
        if right.button("Reject", use_container_width=True):
            api("POST", f"/runs/{approval['run_id']}/reject", {"decided_by": "dashboard", "note": note})
            st.rerun()

with tabs[5]:
    outbox = api("GET", "/integrations/outbox")
    st.metric("Recorded dispatches", len(outbox))
    st.dataframe(
        [
            {
                "created_at": item["created_at"],
                "action_type": item["action_type"],
                "destination": item["destination"],
                "status": item["status"],
                "run_id": item["run_id"],
                "ticket_id": item["ticket_id"],
            }
            for item in outbox
        ],
        use_container_width=True,
        hide_index=True,
    )
    if outbox:
        selected = st.selectbox(
            "Dispatch payload",
            [f"{item['action_type']} | {item['id']}" for item in outbox],
        )
        event = outbox[[f"{item['action_type']} | {item['id']}" for item in outbox].index(selected)]
        st.json(event)

with tabs[6]:
    if st.button("Run KB Failure Drill", type="primary"):
        drill = api("POST", "/drills/tool-failure")
        st.session_state["drill_run_id"] = drill["run"]["run_id"]
        st.success(f"Drill run created: {drill['run']['run_id']}")
    drill_run_id = st.text_input(
        "Failure drill run ID",
        value=st.session_state.get("drill_run_id", st.session_state.get("run_id", "")),
    )
    if drill_run_id:
        trace = api("GET", f"/runs/{drill_run_id}/trace")
        failures = [
            event
            for event in trace
            if event["event_type"] == "tool_call" and event["status"] == "error"
        ]
        c1, c2 = st.columns(2)
        c1.metric("Failed tool attempts", len(failures))
        c2.metric("Trace events", len(trace))
        for event in trace:
            st.markdown(
                f"**{event.get('node') or 'workflow'}** | `{event['event_type']}` | `{event['status']}`"
            )
            if event.get("metadata"):
                st.caption(event["metadata"])
            if event.get("message"):
                st.caption(event["message"])

with tabs[7]:
    if st.button("Run SLA Breach Simulation", type="primary"):
        simulation = api("POST", "/drills/sla-breach-simulation")
        st.session_state["sla_simulation"] = simulation
        if simulation["queue"]:
            st.session_state["run_id"] = simulation["queue"][0]["run_id"]
        st.success(f"Prioritized {len(simulation['queue'])} SLA-risk tickets")
    simulation = st.session_state.get("sla_simulation")
    if simulation:
        st.dataframe(simulation["queue"], use_container_width=True, hide_index=True)
        selected = st.selectbox(
            "Export brief for simulated run",
            [f"{item['risk_level']} | {item['run_id']}" for item in simulation["queue"]],
        )
        selected_run = simulation["queue"][
            [f"{item['risk_level']} | {item['run_id']}" for item in simulation["queue"]].index(
                selected
            )
        ]["run_id"]
        st.session_state["run_id"] = selected_run
        if st.button("Export Incident Brief", use_container_width=True):
            brief = api("POST", f"/runs/{selected_run}/incident-brief")
            st.session_state["incident_brief"] = brief
            st.success(f"Brief exported: {brief['markdown_path']}")

with tabs[8]:
    run_id = st.text_input("Brief run ID", value=st.session_state.get("run_id", ""))
    if st.button("Export Brief", type="primary", disabled=not run_id):
        brief = api("POST", f"/runs/{run_id}/incident-brief")
        st.session_state["incident_brief"] = brief
    brief = st.session_state.get("incident_brief")
    if brief:
        st.caption(f"Markdown: {brief['markdown_path']}")
        st.caption(f"JSON: {brief['json_path']}")
        st.download_button(
            "Download Markdown",
            data=brief["markdown"],
            file_name=f"{brief['run_id']}.md",
            mime="text/markdown",
        )
        st.markdown(brief["markdown"])
        with st.expander("Structured JSON"):
            st.json(brief["brief"])

with tabs[9]:
    run_id = st.text_input("Playbook run ID", value=st.session_state.get("run_id", ""))
    ticket_id = ""
    run = None
    if run_id:
        run = api("GET", f"/runs/{run_id}")
        ticket_id = run["ticket_id"]
        recommendations = run["state"].get("playbook_recommendations", [])
        if not recommendations:
            recommendations = api(
                "POST",
                "/playbooks/recommend",
                {"ticket_id": ticket_id, "top_n": 3},
            )["recommendations"]
        st.subheader("Recommended Playbooks")
        st.dataframe(
            [
                {
                    "rank": index + 1,
                    "playbook": item["title"],
                    "confidence": item["confidence"],
                    "severity": item["severity"],
                    "owners": ", ".join(item["owner_roles"]),
                    "reasons": " ".join(item["match_reasons"]),
                }
                for index, item in enumerate(recommendations)
            ],
            use_container_width=True,
            hide_index=True,
        )
        if recommendations:
            selected = st.selectbox(
                "Selected playbook",
                [f"{item['title']} | {item['id']}" for item in recommendations],
            )
            selected_playbook_id = recommendations[
                [f"{item['title']} | {item['id']}" for item in recommendations].index(selected)
            ]["id"]
            if st.button("Export Remediation Checklist", type="primary"):
                checklist = api(
                    "POST",
                    f"/runs/{run_id}/remediation-checklist",
                    {"playbook_id": selected_playbook_id},
                )
                st.session_state["remediation_checklist"] = checklist
                st.success(f"Checklist exported: {checklist['markdown_path']}")
    else:
        tickets = api("GET", "/tickets")
        labels = {f"{item['subject']} | {item['ticket_id']}": item["ticket_id"] for item in tickets}
        if labels:
            selected_ticket = st.selectbox("Ticket for recommendation", list(labels))
            if st.button("Recommend Playbooks", type="primary"):
                recs = api(
                    "POST",
                    "/playbooks/recommend",
                    {"ticket_id": labels[selected_ticket], "top_n": 3},
                )
                st.session_state["playbook_recommendations"] = recs
        if st.session_state.get("playbook_recommendations"):
            st.json(st.session_state["playbook_recommendations"])

    checklist = st.session_state.get("remediation_checklist")
    if checklist:
        st.caption(f"Markdown: {checklist['markdown_path']}")
        st.caption(f"JSON: {checklist['json_path']}")
        st.download_button(
            "Download Checklist",
            data=checklist["markdown"],
            file_name=f"{checklist['checklist']['checklist_id']}.md",
            mime="text/markdown",
        )
        st.markdown(checklist["markdown"])
        with st.expander("Checklist JSON"):
            st.json(checklist["checklist"])

with tabs[10]:
    health = api("GET", "/customers/health")
    customers = health["customers"]
    if customers:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Accounts", len(customers))
        c2.metric("Critical or at risk", sum(1 for item in customers if item["risk_level"] in {"critical", "at_risk"}))
        c3.metric("Pending approvals", sum(item["pending_approval_count"] for item in customers))
        c4.metric("High SLA risks", sum(item["high_sla_risk_count"] for item in customers))

        st.dataframe(customers, use_container_width=True, hide_index=True)
        selected = st.selectbox(
            "Account",
            [f"{item['account']} | {item['health_score']} | {item['risk_level']}" for item in customers],
        )
        account = customers[
            [f"{item['account']} | {item['health_score']} | {item['risk_level']}" for item in customers].index(
                selected
            )
        ]
        if st.button("Export Account Brief", type="primary"):
            brief = api("POST", f"/customers/{account['customer_id']}/account-brief")
            st.session_state["account_brief"] = brief
            st.success(f"Account brief exported: {brief['markdown_path']}")
        brief = st.session_state.get("account_brief")
        if brief:
            st.caption(f"Markdown: {brief['markdown_path']}")
            st.caption(f"JSON: {brief['json_path']}")
            st.download_button(
                "Download Account Brief",
                data=brief["markdown"],
                file_name=f"{brief['customer_id']}.md",
                mime="text/markdown",
            )
            st.markdown(brief["markdown"])
            with st.expander("Account Brief JSON"):
                st.json(brief["brief"])
    else:
        st.info("No customer health rows yet.")

with tabs[11]:
    snapshot = api("GET", "/analytics/ops-snapshot")
    summary = snapshot["summary_metrics"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tickets", summary["ticket_count"])
    c2.metric("Runs", summary["run_count"])
    c3.metric("Pending approvals", summary["pending_approval_count"])
    c4.metric("Failures", summary["failure_count"])
    r1, r2, r3 = st.columns(3)
    r1.metric("Outbox dispatches", summary["outbox_dispatch_count"])
    r2.metric("Avg latency/run", f"{snapshot['averages']['latency_ms_per_run']} ms")
    r3.metric("Avg cost/run", f"${snapshot['averages']['cost_usd_per_run']:.6f}")

    st.subheader("Top Risky Tickets")
    st.dataframe(snapshot["top_risky_tickets"], use_container_width=True, hide_index=True)
    st.subheader("Recommended Actions")
    for action in snapshot["recommended_operational_actions"]:
        st.markdown(f"- {action}")

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Counts")
        st.json(snapshot["counts"])
    with right:
        st.subheader("SLA Highlights")
        st.dataframe(snapshot["sla_queue_highlights"], use_container_width=True, hide_index=True)

    if st.button("Export Weekly Review", type="primary"):
        review = api("POST", "/analytics/weekly-review")
        st.session_state["weekly_review"] = review
        st.success(f"Weekly review exported: {review['markdown_path']}")
    review = st.session_state.get("weekly_review")
    if review:
        st.caption(f"Markdown: {review['markdown_path']}")
        st.caption(f"JSON: {review['json_path']}")
        st.download_button(
            "Download Weekly Review",
            data=review["markdown"],
            file_name=f"{review['report_id']}.md",
            mime="text/markdown",
        )
        with st.expander("Weekly Review Markdown", expanded=True):
            st.markdown(review["markdown"])
        with st.expander("Structured Snapshot"):
            st.json(snapshot)

with tabs[12]:
    slo = api("GET", "/ops/slo-budget")
    metrics = slo["metrics"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Overall SLO", slo["overall_status"].upper())
    c2.metric("Failures", metrics["failure_count"]["current_value"])
    c3.metric("Pending approvals", metrics["pending_approvals"]["current_value"])
    r1, r2, r3 = st.columns(3)
    r1.metric(
        "Workflow latency",
        f"{metrics['agent_workflow_latency_ms']['current_value']} ms/run",
    )
    r2.metric(
        "Token usage",
        f"{metrics['token_usage_per_run']['current_value']} tokens/run",
    )
    r3.metric(
        "Outbox delay",
        f"{metrics['outbox_dispatch_delay_minutes']['current_value']} min",
    )
    st.dataframe(
        [
            {
                "metric": metric,
                "status": item["status"],
                "current_value": item["current_value"],
                "unit": item["unit"],
                "pass_at_or_below": item["thresholds"]["pass_at_or_below"],
                "warn_at_or_below": item["thresholds"]["warn_at_or_below"],
                "recommendation": item["recommendation"],
            }
            for metric, item in metrics.items()
        ],
        use_container_width=True,
        hide_index=True,
    )

    if st.button("Export Optimization Report", type="primary"):
        report = api("POST", "/ops/optimization-report")
        st.session_state["optimization_report"] = report
        st.success(f"Optimization report exported: {report['markdown_path']}")
    report = st.session_state.get("optimization_report")
    if report:
        st.caption(f"Markdown: {report['markdown_path']}")
        st.caption(f"JSON: {report['json_path']}")
        st.download_button(
            "Download Optimization Report",
            data=report["markdown"],
            file_name=f"{report['report_id']}.md",
            mime="text/markdown",
        )
        st.markdown(report["markdown"])
        with st.expander("Optimization Report JSON"):
            st.json(report["report"])

with tabs[13]:
    left, right = st.columns(2)
    if left.button("Run Demo Scenario", type="primary", use_container_width=True):
        scenario = api("POST", "/demo/scenario-run")
        st.session_state["demo_scenario"] = scenario
        st.session_state["run_id"] = scenario["summary_metrics"]["run_id"]
        st.success(f"Scenario complete: {scenario['scenario_id']}")
    if right.button("Export Evidence Pack", use_container_width=True):
        pack = api("POST", "/demo/evidence-pack")
        st.session_state["demo_evidence_pack"] = pack
        st.session_state["demo_scenario"] = pack["scenario"]
        st.session_state["run_id"] = pack["scenario"]["summary_metrics"]["run_id"]
        st.success(f"Evidence pack exported: {pack['markdown_path']}")

    scenario = st.session_state.get("demo_scenario")
    if scenario:
        metrics = scenario["summary_metrics"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Run status", metrics["run_status"])
        c2.metric("Trace events", metrics["trace_event_count"])
        c3.metric("Outbox dispatches", metrics["outbox_dispatch_count"])
        c4.metric("SLO", metrics["slo_overall_status"].upper())
        st.subheader("Generated Artifacts")
        st.dataframe(
            [
                {"artifact": name, "path": path}
                for name, path in sorted(scenario["artifact_paths"].items())
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("Endpoints Exercised")
        st.dataframe(
            [{"endpoint": endpoint} for endpoint in scenario["endpoints_exercised"]],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Scenario JSON"):
            st.json(scenario)

    pack = st.session_state.get("demo_evidence_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Evidence Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(pack["markdown"])
        with st.expander("Evidence Pack JSON"):
            st.json(pack["pack"])

with tabs[14]:
    metrics = api("GET", "/metrics/agent-performance")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Runs", metrics["run_count"])
    c2.metric("Completed", metrics["completed_runs"])
    c3.metric("Pending approvals", metrics["pending_approvals"])
    c4.metric("Estimated cost", f"${metrics['estimated_cost_usd']:.6f}")
    r1, r2, r3 = st.columns(3)
    r1.metric("Outbox dispatches", metrics.get("outbox_dispatch_count", 0))
    r2.metric("Failure drills", metrics.get("failure_drill_count", 0))
    r3.metric("Tool failures", metrics.get("tool_failure_count", 0))
    st.json(metrics)

with tabs[15]:
    st.dataframe(api("GET", "/audit/events"), use_container_width=True, hide_index=True)

with tabs[16]:
    run_id = st.text_input("Operator QA run ID", value=st.session_state.get("run_id", ""))
    left, right = st.columns(2)
    if left.button("Run Runbook QA", type="primary", use_container_width=True):
        payload = {"run_id": run_id} if run_id else None
        qa = api("POST", "/ops/runbook-qa", payload)
        st.session_state["runbook_qa"] = qa
        st.session_state["run_id"] = qa["run_id"]
    if right.button("Export Readiness Pack", use_container_width=True):
        payload = {"run_id": run_id} if run_id else None
        pack = api("POST", "/ops/operator-readiness-pack", payload)
        st.session_state["operator_readiness_pack"] = pack
        st.session_state["runbook_qa"] = pack["pack"]["runbook_qa"]
        st.session_state["run_id"] = pack["pack"]["runbook_qa"]["run_id"]
        st.success(f"Readiness Pack exported: {pack['markdown_path']}")

    qa = st.session_state.get("runbook_qa")
    if qa:
        c1, c2, c3 = st.columns(3)
        c1.metric("Readiness score", qa["score"])
        c2.metric("Status", qa["status"].upper())
        c3.metric("Missing sections", len(qa["missing_sections"]))
        st.subheader("Required Sections")
        st.dataframe(
            [
                {
                    "section": item["label"],
                    "present": item["present"],
                    "evidence": item["evidence"],
                }
                for item in qa["sections"].values()
            ],
            use_container_width=True,
            hide_index=True,
        )
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Recommended Fixes")
            for fix in qa["recommended_fixes"]:
                st.markdown(f"- {fix}")
        with col2:
            st.subheader("Warnings")
            for warning in qa["warnings"] or ["None"]:
                st.markdown(f"- {warning}")
        st.subheader("Linked Artifacts")
        st.dataframe(
            [
                {"artifact": name, "path": path}
                for name, path in sorted(qa["linked_artifact_paths"].items())
            ],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Runbook QA JSON"):
            st.json(qa)

    pack = st.session_state.get("operator_readiness_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Readiness Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(pack["markdown"])
        with st.expander("Readiness Pack JSON"):
            st.json(pack["pack"])

with tabs[17]:
    run_id = st.text_input("Replay run ID", value=st.session_state.get("run_id", ""))
    c1, c2, c3 = st.columns(3)
    sla_pressure = c1.selectbox("SLA pressure", ["normal", "high", "critical"], index=1)
    kb_context = c2.selectbox("KB context", ["full", "missing", "conflicting"], index=0)
    adapter_health = c3.selectbox("Adapter health", ["healthy", "degraded", "failing"], index=1)
    p1, p2 = st.columns(2)
    approval_policy = p1.selectbox(
        "Approval policy",
        ["standard", "strict", "auto_internal_only"],
    )
    confidence_enabled = p2.checkbox("Override confidence")
    confidence_override = p2.slider("Confidence", 0.0, 1.0, 0.45, 0.01) if confidence_enabled else None
    replay_payload = {
        "run_id": run_id or None,
        "modifiers": {
            "sla_pressure": sla_pressure,
            "kb_context": kb_context,
            "adapter_health": adapter_health,
            "confidence_override": confidence_override,
            "approval_policy": approval_policy,
        },
    }
    left, right = st.columns(2)
    if left.button("Run Replay", type="primary", use_container_width=True):
        path = f"/runs/{run_id}/replay-lab" if run_id else "/replay-lab/run"
        payload = {"modifiers": replay_payload["modifiers"]} if run_id else replay_payload
        replay = api("POST", path, payload)
        st.session_state["replay_lab"] = replay
        st.session_state["run_id"] = replay["source_run_id"]
    if right.button("Export Replay Report", use_container_width=True):
        report = api("POST", "/replay-lab/report", replay_payload)
        st.session_state["replay_lab_report"] = report
        st.session_state["replay_lab"] = report["report"]["comparison"]
        st.success(f"Replay report exported: {report['markdown_path']}")

    replay = st.session_state.get("replay_lab")
    if replay:
        comparison = replay["comparison"]
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Risk score", comparison["risk_score"])
        r2.metric("Changed decisions", len(comparison["changed_decisions"]))
        r3.metric("Replay SLA", replay["replay"]["sla_risk"]["level"])
        r4.metric("Approval", "required" if replay["replay"]["approval_required"] else "not required")
        st.subheader("Recommended Operator Action")
        st.info(comparison["recommended_operator_action"])
        st.subheader("Original vs Replay")
        st.dataframe(
            [
                {
                    "decision": "classification",
                    "original": replay["original"]["classification"]["category"],
                    "replay": replay["replay"]["classification"]["category"],
                },
                {
                    "decision": "SLA risk",
                    "original": replay["original"]["sla_risk"]["level"],
                    "replay": replay["replay"]["sla_risk"]["level"],
                },
                {
                    "decision": "final action",
                    "original": replay["original"]["final_action"],
                    "replay": replay["replay"]["final_action"],
                },
                {
                    "decision": "tool attempts",
                    "original": replay["original"]["tool_attempts"]["count"],
                    "replay": replay["replay"]["tool_attempts"]["count"],
                },
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("Changed Decisions")
        st.dataframe(comparison["changed_decisions"], use_container_width=True, hide_index=True)
        st.subheader("Risk Flags")
        st.write(", ".join(comparison["risk_flags"]) or "None")
        with st.expander("Replay Lab JSON"):
            st.json(replay)

    report = st.session_state.get("replay_lab_report")
    if report:
        st.caption(f"Markdown: {report['markdown_path']}")
        st.caption(f"JSON: {report['json_path']}")
        st.download_button(
            "Download Replay Report",
            data=report["markdown"],
            file_name=f"{report['report_id']}.md",
            mime="text/markdown",
        )
        st.markdown(report["markdown"])

with tabs[18]:
    run_id = st.text_input("Policy run ID", value=st.session_state.get("run_id", ""))
    c1, c2, c3 = st.columns(3)
    sla_pressure = c1.selectbox(
        "Policy SLA pressure",
        ["normal", "high", "critical"],
        index=1,
    )
    kb_context = c2.selectbox("Policy KB context", ["full", "missing", "conflicting"], index=0)
    adapter_health = c3.selectbox(
        "Policy adapter health",
        ["healthy", "degraded", "failing"],
        index=1,
    )
    p1, p2, p3 = st.columns(3)
    approval_policy = p1.selectbox(
        "Policy mode",
        ["standard", "strict", "auto_internal_only"],
    )
    replay_risk_threshold = p2.slider("Replay risk threshold", 0, 100, 70, 5)
    confidence_override = p3.slider("Confidence override", 0.0, 1.0, 0.46, 0.01)
    actions = st.multiselect(
        "Requested actions",
        [
            "customer_reply",
            "zendesk_update",
            "jira_issue",
            "slack_alert",
            "engineering_escalation",
        ],
        default=[
            "customer_reply",
            "zendesk_update",
            "jira_issue",
            "slack_alert",
            "engineering_escalation",
        ],
    )
    policy_payload = {
        "run_id": run_id or None,
        "modifiers": {
            "sla_pressure": sla_pressure,
            "kb_context": kb_context,
            "adapter_health": adapter_health,
            "confidence_override": confidence_override,
            "approval_policy": approval_policy,
        },
        "requested_actions": actions,
        "replay_risk_threshold": replay_risk_threshold,
    }
    left, right = st.columns(2)
    if left.button("Simulate Policy", type="primary", use_container_width=True):
        simulation = api("POST", "/policies/simulate", policy_payload)
        st.session_state["policy_simulation"] = simulation
        st.session_state["run_id"] = simulation["source_run_id"]
    if right.button("Export Policy Pack", use_container_width=True):
        pack = api("POST", "/policies/export", policy_payload)
        st.session_state["policy_pack"] = pack
        st.session_state["policy_simulation"] = pack["pack"]["primary_simulation"]
        st.session_state["run_id"] = pack["pack"]["primary_simulation"]["source_run_id"]
        st.success(f"Policy pack exported: {pack['markdown_path']}")

    simulation = st.session_state.get("policy_simulation")
    if simulation:
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Decision", simulation["policy_decision"])
        s2.metric("Approval", simulation["required_approval_type"])
        s3.metric("Blocked", len(simulation["blocked_actions"]))
        s4.metric("Replay risk", simulation["replay_summary"]["risk_score"])
        st.subheader("Recommended Operator Action")
        st.info(simulation["recommended_operator_action"])
        st.subheader("Matched Rules")
        st.dataframe(simulation["matched_rules"], use_container_width=True, hide_index=True)
        st.subheader("Action Split")
        a1, a2 = st.columns(2)
        with a1:
            st.caption("Blocked actions")
            st.write(", ".join(simulation["blocked_actions"]) or "None")
        with a2:
            st.caption("Allowed actions")
            st.write(", ".join(simulation["allowed_actions"]) or "None")
        st.subheader("Approval Matrix")
        st.dataframe(simulation["approval_matrix"], use_container_width=True, hide_index=True)
        with st.expander("Policy Simulation JSON"):
            st.json(simulation)

    pack = st.session_state.get("policy_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Policy Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(pack["markdown"])

with tabs[19]:
    run_id = st.text_input("Incident narrative run ID", value=st.session_state.get("run_id", ""))
    left, right = st.columns(2)
    narrative_payload = {"run_id": run_id} if run_id else None
    if left.button("Build Customer Impact Timeline", type="primary", use_container_width=True):
        timeline = api("POST", "/incidents/timeline", narrative_payload)
        st.session_state["incident_timeline"] = timeline
        st.session_state["run_id"] = timeline["run_id"]
    if right.button("Export Executive Narrative", use_container_width=True):
        narrative = api("POST", "/incidents/executive-narrative", narrative_payload)
        st.session_state["executive_incident_narrative"] = narrative
        st.session_state["incident_timeline"] = narrative["narrative"]
        st.session_state["run_id"] = narrative["run_id"]
        st.success(f"Narrative exported: {narrative['markdown_path']}")

    timeline = st.session_state.get("incident_timeline")
    if timeline:
        if "timeline" in timeline and "events" not in timeline:
            timeline_rows = timeline["timeline"]
            impact = timeline["customer_impact"]
            policy = timeline["policy_guardrail_decision"]
            replay = timeline["replay_risk"]
            owner_actions = timeline["owner_actions"]
            unresolved = timeline["unresolved_risks"]
            artifacts = timeline["evidence_artifact_links"]
            run_display = timeline["run_id"]
            impact_status = timeline["impact_status"]
        else:
            timeline_rows = timeline["events"]
            impact = timeline["customer_impact_summary"]
            policy = timeline["policy_annotations"]
            replay = timeline["replay_annotations"]
            owner_actions = timeline["owner_next_steps"]
            unresolved = timeline["unresolved_risks"]
            artifacts = timeline["evidence_artifact_links"]
            run_display = timeline["run_id"]
            impact_status = timeline["impact_status"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Run", run_display)
        c2.metric("Impact status", impact_status)
        c3.metric("Policy", policy["policy_decision"])
        c4.metric("Replay risk", replay["risk_score"])
        st.subheader("Customer Impact")
        st.json(impact)
        st.subheader("Customer Impact Timeline")
        st.dataframe(
            [
                {
                    "sequence": item["sequence"],
                    "timestamp": item["timestamp"],
                    "phase": item["phase"],
                    "visibility": item["visibility"],
                    "actor": item["actor"],
                    "summary": item["summary"],
                }
                for item in timeline_rows
            ],
            use_container_width=True,
            hide_index=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Owner Actions")
            st.dataframe(owner_actions, use_container_width=True, hide_index=True)
        with c2:
            st.subheader("Unresolved Risks")
            st.dataframe(unresolved, use_container_width=True, hide_index=True)
        st.subheader("Policy and Replay Annotations")
        st.json({"policy": policy, "replay": replay})
        st.subheader("Evidence Artifacts")
        st.dataframe(
            [{"artifact": name, "path": path} for name, path in sorted(artifacts.items())],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Timeline JSON"):
            st.json(timeline)

    narrative = st.session_state.get("executive_incident_narrative")
    if narrative:
        st.caption(f"Markdown: {narrative['markdown_path']}")
        st.caption(f"JSON: {narrative['json_path']}")
        st.download_button(
            "Download Executive Narrative",
            data=narrative["markdown"],
            file_name=f"{narrative['narrative_id']}.md",
            mime="text/markdown",
        )
        st.markdown(narrative["markdown"])

with tabs[20]:
    left, right = st.columns(2)
    if left.button("Refresh Scorecard", type="primary", use_container_width=True):
        st.session_state["leadership_scorecard"] = api("GET", "/leadership/scorecard")
    if right.button("Export Review Pack", use_container_width=True):
        review = api("POST", "/leadership/review-pack")
        st.session_state["leadership_review_pack"] = review
        st.session_state["leadership_scorecard"] = review["review"]["scorecard"]
        st.success(f"Leadership review exported: {review['markdown_path']}")

    scorecard = st.session_state.get("leadership_scorecard") or api(
        "GET",
        "/leadership/scorecard",
    )
    st.session_state["leadership_scorecard"] = scorecard
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Overall score", scorecard["overall_score"])
    c2.metric("Readiness", scorecard["readiness_status"])
    c3.metric("Runs", scorecard["sample_window"]["run_count"])
    c4.metric("Outbox", scorecard["sample_window"]["outbox_dispatch_count"])

    st.subheader("Automation KPI Categories")
    st.dataframe(
        [
            {
                "category": name,
                "score": category["score"],
                "status": category["status"],
                "risk_flags": ", ".join(category["risk_flags"]),
            }
            for name, category in scorecard["kpi_categories"].items()
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.subheader("Trend-ish Local Values")
    st.json(scorecard["trendish_local_values"])
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Top Risks")
        for risk in scorecard["risk_flags"] or ["None"]:
            st.markdown(f"- {risk}")
    with col2:
        st.subheader("Recommended Actions")
        for action in scorecard["recommended_actions"]:
            st.markdown(f"- {action}")
    st.subheader("Local Evidence Links")
    st.dataframe(
        [{"artifact": name, "path": path} for name, path in sorted(scorecard["artifact_links"].items())],
        use_container_width=True,
        hide_index=True,
    )

    review = st.session_state.get("leadership_review_pack")
    if review:
        st.caption(f"Markdown: {review['markdown_path']}")
        st.caption(f"JSON: {review['json_path']}")
        st.download_button(
            "Download Leadership Review",
            data=review["markdown"],
            file_name=f"{review['review_id']}.md",
            mime="text/markdown",
        )
        st.markdown(review["markdown"])
        with st.expander("Leadership Review JSON"):
            st.json(review["review"])

with tabs[21]:
    left, right = st.columns(2)
    if left.button("Run Knowledge Quality Audit", type="primary", use_container_width=True):
        st.session_state["knowledge_quality_audit"] = api("GET", "/knowledge/quality-audit")
    if right.button("Export KB Refresh Plan", use_container_width=True):
        plan = api("POST", "/knowledge/refresh-plan")
        st.session_state["kb_refresh_plan"] = plan
        st.session_state["knowledge_quality_audit"] = plan["plan"]["source_audit"]
        st.success(f"KB refresh plan exported: {plan['markdown_path']}")

    audit = st.session_state.get("knowledge_quality_audit") or api("GET", "/knowledge/quality-audit")
    st.session_state["knowledge_quality_audit"] = audit
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("KB coverage score", audit["kb_coverage_score"])
    c2.metric("Readiness", audit["readiness_status"])
    c3.metric("Freshness", f"{audit['metrics']['freshness']['freshness_percent']}%")
    c4.metric("Citation coverage", f"{audit['metrics']['citations']['citation_percent']}%")

    st.subheader("Knowledge Quality Metrics")
    st.json(audit["metrics"])
    st.subheader("Weak or Missing Articles")
    st.dataframe(audit["weak_or_missing_articles"], use_container_width=True, hide_index=True)
    st.subheader("Impacted Ticket Types")
    st.dataframe(audit["impacted_ticket_types"], use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Risk Flags")
        for flag in audit["risk_flags"] or ["None"]:
            st.markdown(f"- {flag}")
    with col2:
        st.subheader("Owner Recommendations")
        for item in audit["owner_recommendations"]:
            st.markdown(f"- **{item['owner']}**: {item['recommendation']}")

    st.subheader("Evidence Sources")
    st.json(audit["evidence_sources"])

    plan = st.session_state.get("kb_refresh_plan")
    if plan:
        st.caption(f"Markdown: {plan['markdown_path']}")
        st.caption(f"JSON: {plan['json_path']}")
        st.download_button(
            "Download KB Refresh Plan",
            data=plan["markdown"],
            file_name=f"{plan['plan_id']}.md",
            mime="text/markdown",
        )
        st.markdown(plan["markdown"])
        with st.expander("KB Refresh Plan JSON"):
            st.json(plan["plan"])

with tabs[22]:
    smoke = st.session_state.get("smoke_matrix") or api("GET", "/ops/smoke-matrix")
    st.session_state["smoke_matrix"] = smoke
    summary = smoke["readiness_summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Launch readiness", summary["status"].upper())
    c2.metric("Smoke checks", summary["total_checks"])
    c3.metric("Protected checks", summary["protected_checks"])
    c4.metric("Artifact checks", summary["artifact_writing_checks"])

    st.subheader("Smoke Matrix")
    st.dataframe(
        [
            {
                "endpoint": row["endpoint"],
                "expected_status": row["expected_status"],
                "requires_api_key": row["requires_api_key"],
                "artifact": row["artifact_expectation"]["path"],
                "curl": row["sample_commands"]["curl"],
            }
            for row in smoke["matrix"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    left, right = st.columns(2)
    if left.button("Refresh Smoke Matrix", use_container_width=True):
        st.session_state["smoke_matrix"] = api("GET", "/ops/smoke-matrix")
        st.rerun()
    if right.button("Export Launch Checklist", type="primary", use_container_width=True):
        checklist = api("POST", "/ops/launch-checklist")
        st.session_state["launch_checklist"] = checklist
        st.success(f"Launch checklist exported: {checklist['markdown_path']}")

    checklist = st.session_state.get("launch_checklist")
    if checklist:
        st.caption(f"Markdown: {checklist['markdown_path']}")
        st.caption(f"JSON: {checklist['json_path']}")
        st.download_button(
            "Download Launch Checklist",
            data=checklist["markdown"],
            file_name=f"{checklist['checklist_id']}.md",
            mime="text/markdown",
        )
        st.subheader("Generated Artifacts")
        st.dataframe(
            checklist["checklist"]["generated_artifacts"],
            use_container_width=True,
            hide_index=True,
        )
        st.markdown(checklist["markdown"])
        with st.expander("Launch Checklist JSON"):
            st.json(checklist["checklist"])

with tabs[23]:
    left, right = st.columns(2)
    if left.button("Refresh Portfolio Evidence", type="primary", use_container_width=True):
        st.session_state["portfolio_evidence"] = api("GET", "/portfolio/evidence-index")
    if right.button("Export Interview Pack", use_container_width=True):
        pack = api("POST", "/portfolio/interview-pack")
        st.session_state["portfolio_interview_pack"] = pack
        st.session_state["portfolio_evidence"] = pack["pack"]["evidence_index"]
        st.success(f"Interview Pack exported: {pack['markdown_path']}")

    evidence = st.session_state.get("portfolio_evidence") or api("GET", "/portfolio/evidence-index")
    st.session_state["portfolio_evidence"] = evidence
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Evidence score", evidence["evidence_score"])
    c2.metric("Skill areas", evidence["evidence_count"])
    c3.metric("Covered", evidence["covered_skill_count"])
    c4.metric("Local/mock", "yes" if evidence["local_mock_only"] else "no")

    st.subheader("Skill Coverage")
    st.dataframe(
        [
            {
                "skill": item["jd_skill"],
                "status": item["coverage_status"],
                "score": item["item_score"],
                "endpoints": ", ".join(item["endpoints"]),
                "proof paths": ", ".join(item["local_proof_paths"]),
            }
            for item in evidence["jd_skill_evidence"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Local Verification Commands")
    for command in evidence["verification_commands"]:
        st.code(command)

    st.subheader("Artifact Inventory")
    st.dataframe(
        [
            {
                "artifact": item["name"],
                "directory": item["directory"],
                "producer": item["producer"],
                "latest": item["latest_path"],
            }
            for item in evidence["artifact_inventory"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    pack = st.session_state.get("portfolio_interview_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Interview Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.subheader("Technical Talking Points")
        for point in pack["pack"]["technical_talking_points"]:
            st.markdown(f"- {point}")
        st.markdown(pack["markdown"])
        with st.expander("Interview Pack JSON"):
            st.json(pack["pack"])

with tabs[24]:
    left, right = st.columns(2)
    if left.button("Refresh Release Gate", type="primary", use_container_width=True):
        st.session_state["release_gate"] = api("GET", "/release/quality-gate")
    if right.button("Export Publish Pack", use_container_width=True):
        publish_pack = api("POST", "/release/publish-pack")
        st.session_state["release_publish_pack"] = publish_pack
        st.session_state["release_gate"] = publish_pack["pack"]["quality_gate"]
        st.success(f"Publish Pack exported: {publish_pack['markdown_path']}")

    gate = st.session_state.get("release_gate") or api("GET", "/release/quality-gate")
    st.session_state["release_gate"] = gate
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gate status", gate["status"])
    c2.metric("Score", gate["score"])
    c3.metric("Blockers", len(gate["blockers"]))
    c4.metric("Warnings", len(gate["warnings"]))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Blockers")
        for blocker in gate["blockers"] or ["None"]:
            st.markdown(f"- {blocker}")
    with col2:
        st.subheader("Warnings")
        for warning in gate["warnings"] or ["None"]:
            st.markdown(f"- {warning}")

    st.subheader("Verification Commands")
    for item in gate["verification_checklist"]:
        st.code(item["command"])
        st.caption(item["expected"])

    st.subheader("Coverage")
    st.dataframe(
        [
            {"area": name, "status": item["status"]}
            for name, item in gate["coverage"].items()
        ],
        use_container_width=True,
        hide_index=True,
    )

    publish_pack = st.session_state.get("release_publish_pack")
    if publish_pack:
        st.caption(f"Markdown: {publish_pack['markdown_path']}")
        st.caption(f"JSON: {publish_pack['json_path']}")
        st.download_button(
            "Download Publish Pack",
            data=publish_pack["markdown"],
            file_name=f"{publish_pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(publish_pack["markdown"])
        with st.expander("Publish Pack JSON"):
            st.json(publish_pack["pack"])

with tabs[25]:
    left, right = st.columns(2)
    if left.button("Refresh CI Doctor", type="primary", use_container_width=True):
        st.session_state["ci_doctor"] = api("GET", "/ops/ci-doctor")
    if right.button("Export Audit Pack", use_container_width=True):
        audit_pack = api("POST", "/ops/audit-pack")
        st.session_state["audit_pack"] = audit_pack
        st.session_state["ci_doctor"] = audit_pack["pack"]["ci_doctor"]
        st.success(f"Audit Pack exported: {audit_pack['markdown_path']}")

    doctor = st.session_state.get("ci_doctor") or api("GET", "/ops/ci-doctor")
    st.session_state["ci_doctor"] = doctor
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Doctor status", doctor["status"])
    c2.metric("Score", doctor["score"])
    c3.metric("Blockers", len(doctor["blockers"]))
    c4.metric("Secret findings", doctor["secret_scan_summary"]["finding_count"])

    st.subheader("CI Doctor Checks")
    st.dataframe(
        [
            {
                "check": item["label"],
                "status": item["status"],
            }
            for item in doctor["checks"].values()
        ],
        use_container_width=True,
        hide_index=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Local Verification Commands")
        for command in doctor["local_verification_commands"]:
            st.code(command)
    with col2:
        st.subheader("Publish-Safety Checklist")
        st.dataframe(doctor["publish_safety_checklist"], use_container_width=True, hide_index=True)

    st.subheader("Dependency Inventory")
    st.json(doctor["dependency_inventory"])

    st.subheader("Secret Scan Summary")
    st.json(doctor["secret_scan_summary"])

    audit_pack = st.session_state.get("audit_pack")
    if audit_pack:
        st.caption(f"Markdown: {audit_pack['markdown_path']}")
        st.caption(f"JSON: {audit_pack['json_path']}")
        st.download_button(
            "Download Audit Pack",
            data=audit_pack["markdown"],
            file_name=f"{audit_pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(audit_pack["markdown"])
        with st.expander("Audit Pack JSON"):
            st.json(audit_pack["pack"])

with tabs[26]:
    left, right = st.columns(2)
    if left.button("Refresh Reviewer Quickstart", type="primary", use_container_width=True):
        st.session_state["reviewer_quickstart"] = api("GET", "/reviewer/quickstart")
    if right.button("Export Walkthrough Pack", use_container_width=True):
        pack = api("POST", "/reviewer/walkthrough-pack")
        st.session_state["reviewer_walkthrough_pack"] = pack
        st.session_state["reviewer_quickstart"] = pack["pack"]["quickstart"]
        st.success(f"Walkthrough Pack exported: {pack['markdown_path']}")

    quickstart = st.session_state.get("reviewer_quickstart") or api("GET", "/reviewer/quickstart")
    st.session_state["reviewer_quickstart"] = quickstart
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", quickstart["status"])
    c2.metric("Proof entries", quickstart["artifact_proof_count"])
    c3.metric("Endpoints", len(quickstart["endpoint_walkthrough_order"]))
    c4.metric("Local/mock", "yes" if quickstart["local_mock_only"] else "no")

    st.subheader("Local Setup")
    for command in quickstart["local_setup_commands"]:
        st.code(command)
    st.subheader("One-Command Demo")
    st.code(quickstart["one_command_demo"])

    st.subheader("Verification Commands")
    for command, expected in zip(
        quickstart["verification_commands"],
        quickstart["expected_outputs"],
        strict=False,
    ):
        st.code(command)
        st.caption(expected)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Endpoint Walkthrough")
        st.dataframe(
            [{"order": index + 1, "endpoint": endpoint} for index, endpoint in enumerate(quickstart["endpoint_walkthrough_order"])],
            use_container_width=True,
            hide_index=True,
        )
    with col2:
        st.subheader("Agent Workflow")
        st.dataframe(
            [
                {
                    "step": item["step"],
                    "reviewer_focus": item["reviewer_focus"],
                    "proof": ", ".join(item["proof"]),
                }
                for item in quickstart["agent_workflow_walkthrough"]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Artifact Proof Map")
    st.dataframe(
        [
            {
                "artifact": item["name"],
                "directory": item["directory"],
                "producer": item["producer"],
                "latest": ", ".join(item["latest_paths"]) or "not generated yet",
            }
            for item in quickstart["artifact_proof_map"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Role-Specific Reviewer Notes")
    st.json(quickstart["role_specific_reviewer_notes"])

    pack = st.session_state.get("reviewer_walkthrough_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Walkthrough Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(pack["markdown"])
        with st.expander("Walkthrough Pack JSON"):
            st.json(pack["pack"])

with tabs[27]:
    left, right = st.columns(2)
    if left.button("Refresh Artifact Inventory", type="primary", use_container_width=True):
        st.session_state["artifact_inventory"] = api("GET", "/artifacts/inventory")
    if right.button("Export README Checklist Pack", use_container_width=True):
        pack = api("POST", "/artifacts/readme-checklist")
        st.session_state["readme_checklist_pack"] = pack
        st.session_state["artifact_inventory"] = api("GET", "/artifacts/inventory")
        st.success(f"README Checklist exported: {pack['markdown_path']}")

    inventory = st.session_state.get("artifact_inventory") or api("GET", "/artifacts/inventory")
    st.session_state["artifact_inventory"] = inventory
    artifacts = inventory["artifacts"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Artifact dirs", inventory.get("artifact_count", len(artifacts)))
    c2.metric("Generated dirs", inventory.get("generated_artifact_directory_count", 0))
    c3.metric("Missing dirs", inventory.get("missing_artifact_directory_count", 0))
    c4.metric("Local/mock", "yes" if inventory.get("local_mock_only", True) else "no")

    st.subheader("Artifact Inventory")
    st.dataframe(
        [
            {
                "artifact": item["name"],
                "directory": item["directory"],
                "producer": item["producer"],
                "latest": item["latest_path"],
                "freshness": item["freshness"]["status"],
                "ignored": item["ignored_status"]["ignored_by_default"],
                "purpose": item["reviewer_purpose"],
            }
            for item in artifacts
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Local Commands")
    commands = inventory.get("local_commands", {})
    if commands.get("demo"):
        st.code(commands["demo"])
    for command in commands.get("verify", []):
        st.code(command)

    pack = st.session_state.get("readme_checklist_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download README Checklist",
            data=pack["markdown"],
            file_name=f"{pack['checklist_id']}.md",
            mime="text/markdown",
        )
        st.markdown(pack["markdown"])
        with st.expander("README Checklist JSON"):
            st.json(pack["pack"])

with tabs[28]:
    left, right = st.columns(2)
    if left.button("Refresh Dashboard Smoke", type="primary", use_container_width=True):
        st.session_state["dashboard_smoke"] = api("GET", "/ui/dashboard-smoke")
    if right.button("Export UI Verification Pack", use_container_width=True):
        pack = api("POST", "/ui/verification-pack")
        st.session_state["ui_verification_pack"] = pack
        st.session_state["dashboard_smoke"] = pack["pack"]["dashboard_smoke"]
        st.success(f"UI Verification exported: {pack['markdown_path']}")

    smoke = st.session_state.get("dashboard_smoke") or api("GET", "/ui/dashboard-smoke")
    st.session_state["dashboard_smoke"] = smoke
    summary = smoke["summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Dashboard smoke", smoke["status"].upper())
    c2.metric("Checks", summary["total_checks"])
    c3.metric("Failed", summary["failed_checks"])
    c4.metric("Views", summary["view_count"])

    st.subheader("Expected Views")
    st.dataframe(
        [
            {
                "view": item["label"],
                "present": item["present"],
                "position": item["position"],
            }
            for item in smoke["expected_views"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Endpoint References")
    st.dataframe(
        [
            {
                "endpoint": item["endpoint"],
                "dashboard_reference": item["dashboard_reference_present"],
                "api_route": item["route_present"],
                "purpose": item["purpose"],
            }
            for item in smoke["endpoint_references"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Generated Artifact Tabs")
    st.dataframe(
        [
            {
                "tab": item["tab_label"],
                "producer": item["producer_endpoint"],
                "artifact": item["artifact_directory"],
                "present": item["tab_present"],
            }
            for item in smoke["generated_artifact_tabs"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Local Run Commands")
    commands = smoke["local_run_commands"]
    st.code(commands["api"])
    st.code(commands["dashboard"])
    st.code(commands["dashboard_smoke"])

    pack = st.session_state.get("ui_verification_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download UI Verification Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(pack["markdown"])
        with st.expander("UI Verification JSON"):
            st.json(pack["pack"])

with tabs[29]:
    left, right = st.columns(2)
    if left.button("Refresh Final Audit", type="primary", use_container_width=True):
        st.session_state["final_audit"] = api("GET", "/handoff/final-audit")
    if right.button("Export Final Handoff Pack", use_container_width=True):
        pack = api("POST", "/handoff/final-pack")
        st.session_state["final_handoff_pack"] = pack
        st.session_state["final_audit"] = pack["pack"]["final_audit"]
        st.success(f"Final Handoff exported: {pack['markdown_path']}")

    audit = st.session_state.get("final_audit") or api("GET", "/handoff/final-audit")
    st.session_state["final_audit"] = audit
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Final audit", audit["status"])
    c2.metric("Score", audit["score"])
    c3.metric("Blockers", len(audit["blockers"]))
    c4.metric("Warnings", len(audit["warnings"]))

    st.subheader("README Consistency Checks")
    st.dataframe(
        [
            {
                "check": name,
                "status": item["status"],
                "detail": item["label"],
            }
            for name, item in audit["checks"].items()
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Endpoint Inventory Summary")
    st.json(audit["endpoint_inventory_summary"])

    st.subheader("Dashboard Smoke Summary")
    st.json(audit["dashboard_smoke_summary"])

    pack = st.session_state.get("final_handoff_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Final Handoff Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.subheader("End-to-End Verification Order")
        st.dataframe(pack["pack"]["end_to_end_verification_order"], use_container_width=True, hide_index=True)
        st.markdown(pack["markdown"])
        with st.expander("Final Handoff JSON"):
            st.json(pack["pack"])

with tabs[30]:
    left, right = st.columns(2)
    if left.button("Refresh Git Readiness", type="primary", use_container_width=True):
        st.session_state["git_readiness"] = api("GET", "/git/readiness")
    if right.button("Export Push Plan", use_container_width=True):
        pack = api("POST", "/git/push-plan")
        st.session_state["git_push_plan"] = pack
        st.session_state["git_readiness"] = pack["pack"]["readiness"]
        st.success(f"Push Plan exported: {pack['markdown_path']}")

    readiness = st.session_state.get("git_readiness") or api("GET", "/git/readiness")
    st.session_state["git_readiness"] = readiness
    summary = readiness["summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Readiness", readiness["status"])
    c2.metric("Branch", readiness["current_branch"] or "unknown")
    c3.metric("Changed", summary["changed_count"])
    c4.metric("Ignored", summary["ignored_count"])

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Branch Hygiene")
        st.json(readiness["git"])
    with col2:
        st.subheader("Required Publish Checks")
        st.json(
            {
                "github_actions_workflow": readiness["github_actions_workflow"],
                "readme_final_handoff_mention": readiness["readme_final_handoff_mention"],
                "env_example": readiness["env_example"],
            }
        )

    st.subheader("Changed File Groups")
    st.dataframe(
        [
            {
                "group": group,
                "count": len(paths),
                "paths": ", ".join(paths[:8]),
            }
            for group, paths in readiness["changed_file_groups"].items()
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Generated Artifact Directories")
    st.dataframe(
        [
            {
                "directory": item["directory"],
                "exists": item["exists"],
                "ignored": item["ignored"],
                "file_count": item["file_count"],
            }
            for item in readiness["generated_artifact_directories"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Suspicious Large / Generated Files")
    st.dataframe(
        [
            {
                "path": item["path"],
                "state": item["state"],
                "size_bytes": item["size_bytes"],
                "reasons": ", ".join(item["reasons"]),
            }
            for item in readiness["suspicious_large_or_generated_files"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Recommended Commit Groups")
    st.dataframe(
        [
            {
                "group": item["group"],
                "message": item["suggested_commit_message"],
                "path_count": len(item["paths"]),
                "review_note": item["review_note"],
            }
            for item in readiness["recommended_commit_groups"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Dirty Worktree Guidance")
    for item in readiness["dirty_worktree_guidance"]:
        st.markdown(f"- {item}")

    st.subheader("Verification Commands")
    for command in readiness["verification_commands"]:
        st.code(command)

    pack = st.session_state.get("git_push_plan")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Push Plan",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(pack["markdown"])
        with st.expander("Push Plan JSON"):
            st.json(pack["pack"])

with tabs[31]:
    left, right = st.columns(2)
    if left.button("Refresh Contract Audit", type="primary", use_container_width=True):
        st.session_state["api_contract_audit"] = api("GET", "/api/contract-audit")
    if right.button("Export Reviewer Collection", use_container_width=True):
        collection = api("POST", "/api/reviewer-collection")
        st.session_state["api_reviewer_collection"] = collection
        st.session_state["api_contract_audit"] = collection["collection"]["contract_audit"]
        st.success(f"Reviewer Collection exported: {collection['markdown_path']}")

    audit = st.session_state.get("api_contract_audit") or api("GET", "/api/contract-audit")
    st.session_state["api_contract_audit"] = audit
    summary = audit["summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Contract", audit["status"])
    c2.metric("OpenAPI routes", summary["openapi_route_count"])
    c3.metric("Protected", summary["auth_protected_endpoint_count"])
    c4.metric("Docs warnings", summary["missing_docs_warning_count"])

    st.subheader("OpenAPI")
    st.json(audit["openapi"])

    st.subheader("Docs / API Coverage")
    st.dataframe(
        audit["docs_api_coverage"]["important_endpoint_coverage"],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Dashboard Smoke Alignment")
    st.json(audit["dashboard_smoke_alignment"])

    st.subheader("Generated Artifact Endpoint Coverage")
    st.dataframe(
        audit["generated_artifact_endpoint_coverage"],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Demo Flow Endpoint Coverage")
    st.dataframe(
        audit["demo_flow_endpoint_coverage"]["endpoints"],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Endpoint Inventory")
    st.dataframe(audit["endpoint_inventory"], use_container_width=True, hide_index=True)

    st.subheader("Verification Commands")
    for command in audit["verification_commands"]:
        st.code(command)

    st.subheader("Local-Only Limitations")
    for limitation in audit["local_only_limitations"]:
        st.markdown(f"- {limitation}")

    collection = st.session_state.get("api_reviewer_collection")
    if collection:
        st.caption(f"Markdown: {collection['markdown_path']}")
        st.caption(f"JSON: {collection['json_path']}")
        st.download_button(
            "Download Reviewer Collection",
            data=collection["markdown"],
            file_name=f"{collection['collection_id']}.md",
            mime="text/markdown",
        )
        st.markdown(collection["markdown"])
        with st.expander("Reviewer Collection JSON"):
            st.json(collection["collection"])

with tabs[32]:
    left, right = st.columns(2)
    if left.button("Refresh Runtime Readiness", type="primary", use_container_width=True):
        st.session_state["runtime_demo_readiness"] = api("GET", "/runtime/demo-readiness")
    if right.button("Export Runtime Demo Pack", use_container_width=True):
        pack = api("POST", "/runtime/demo-pack")
        st.session_state["runtime_demo_pack"] = pack
        st.session_state["runtime_demo_readiness"] = pack["pack"]["readiness"]
        st.success(f"Runtime Demo Pack exported: {pack['markdown_path']}")

    readiness = st.session_state.get("runtime_demo_readiness") or api("GET", "/runtime/demo-readiness")
    st.session_state["runtime_demo_readiness"] = readiness
    summary = readiness["summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Runtime", readiness["status"])
    c2.metric("Checks", summary["total_checks"])
    c3.metric("Warnings", summary["warning_checks"])
    c4.metric("Failed", summary["failed_checks"])

    st.subheader("Start Commands")
    commands = readiness["run_commands"]
    for command in commands["start"]:
        st.code(command)
    st.code(commands["runtime_check"])
    st.code(commands["demo_run"])

    st.subheader("Expected Ports")
    st.dataframe(readiness["expected_ports"], use_container_width=True, hide_index=True)

    st.subheader("Dependency Checks")
    st.dataframe(
        [
            {
                "dependency": item["name"],
                "status": item["status"],
                "declared": item["source_declared"],
                "importable": item["import_available"],
                "note": item["note"],
            }
            for item in readiness["dependency_checks"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Read-Only Port Checks")
    st.dataframe(
        [
            {
                "service": item["name"],
                "port": item["port"],
                "status": item["status"],
                "listening": item["listening"],
                "note": item["note"],
            }
            for item in readiness["process_port_checks"]["socket_connect_checks"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Health URLs")
    for url in readiness["health_urls"]:
        st.code(url)

    st.subheader("Known Limitations")
    for limitation in readiness["known_limitations"]:
        st.markdown(f"- {limitation}")

    pack = st.session_state.get("runtime_demo_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Runtime Demo Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(pack["markdown"])
        with st.expander("Runtime Demo Pack JSON"):
            st.json(pack["pack"])

with tabs[33]:
    left, right = st.columns(2)
    if left.button("Refresh Scenario Catalog", type="primary", use_container_width=True):
        st.session_state["scenario_catalog"] = api("GET", "/scenarios/catalog")
    if right.button("Export Scenario Eval Pack", use_container_width=True):
        pack = api("POST", "/scenarios/eval-pack")
        st.session_state["scenario_eval_pack"] = pack
        st.session_state["scenario_catalog"] = {
            "coverage_summary": pack["pack"]["coverage_summary"],
            "scenario_count": pack["pack"]["scenario_count"],
            "scenarios": pack["pack"]["scenario_results"],
        }
        st.success(f"Scenario Eval Pack exported: {pack['markdown_path']}")

    catalog = st.session_state.get("scenario_catalog") or api("GET", "/scenarios/catalog")
    st.session_state["scenario_catalog"] = catalog
    coverage = catalog["coverage_summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Scenarios", catalog["scenario_count"])
    c2.metric("Domains", coverage["domain_count"])
    c3.metric("Escalations", coverage["escalation_expected_count"])
    c4.metric("Failure paths", coverage["failure_state_expected_count"])

    st.subheader("Scenario Catalog")
    st.dataframe(
        [
            {
                "scenario_id": item["scenario_id"],
                "domain": item["domain"],
                "customer": item.get("customer") or "",
                "category": item.get("expected_outcomes", item.get("expected", {})).get(
                    "classification_category"
                ),
                "sla": item.get("expected_outcomes", item.get("expected", {})).get("sla_level"),
                "approval": item.get("expected_outcomes", item.get("expected", {})).get(
                    "approval_pause"
                ),
                "escalation": item.get("expected_outcomes", item.get("expected", {})).get(
                    "engineering_escalation"
                ),
            }
            for item in catalog["scenarios"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Scenario Coverage")
    st.json(coverage)

    pack = st.session_state.get("scenario_eval_pack")
    if pack:
        summary = pack["eval_summary"]
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Eval status", summary["status"].upper())
        s2.metric("Passed", summary["passed_scenario_count"])
        s3.metric("Classification", f"{summary['classification_accuracy']['accuracy_percent']}%")
        s4.metric("SLA routing", f"{summary['sla_routing']['accuracy_percent']}%")
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Scenario Eval Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.subheader("Scenario Results")
        st.dataframe(pack["pack"]["scenario_results"], use_container_width=True, hide_index=True)
        st.markdown(pack["markdown"])
        with st.expander("Scenario Eval Pack JSON"):
            st.json(pack["pack"])

with tabs[34]:
    left, right = st.columns(2)
    if left.button("Refresh On-Call Summary", type="primary", use_container_width=True):
        st.session_state["on_call_handoff"] = api("GET", "/handoff/on-call-summary")
    if right.button("Export Customer Communications Pack", use_container_width=True):
        pack = api("POST", "/handoff/customer-comms-pack")
        st.session_state["customer_comms_pack"] = pack
        st.session_state["on_call_handoff"] = pack["pack"]["on_call_handoff_summary"]
        st.success(f"Customer Communications exported: {pack['markdown_path']}")

    summary = st.session_state.get("on_call_handoff") or api("GET", "/handoff/on-call-summary")
    st.session_state["on_call_handoff"] = summary
    readiness = summary["customer_communication_readiness"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Severity", summary["severity"].upper())
    c2.metric("Status", summary["status"])
    c3.metric("SLA", summary["sla"]["risk_level"])
    c4.metric("Communication readiness", readiness["status"])

    st.subheader("Owners")
    st.json(summary["owners"])

    st.subheader("Customer Updates")
    st.dataframe(
        [
            {
                "type": item["type"],
                "status": item["status"],
                "subject": item["subject"],
                "requires_approval": item["requires_approval"],
            }
            for item in summary["latest_drafts"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Approval and Guardrail Status")
    st.json(summary["approval_and_guardrail_status"])

    st.subheader("Risk / Gap Checklist")
    st.dataframe(summary["risk_gap_checklist"], use_container_width=True, hide_index=True)

    st.subheader("Trace Links")
    st.json(summary["trace_links"])

    pack = st.session_state.get("customer_comms_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download Customer Communications Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.subheader("Scenario Coverage")
        st.dataframe(pack["pack"]["scenario_coverage"]["scenarios"], use_container_width=True, hide_index=True)
        st.markdown(pack["markdown"])
        with st.expander("Customer Communications JSON"):
            st.json(pack["pack"])

with tabs[35]:
    left, right = st.columns(2)
    if left.button("Refresh Postmortem RCA", type="primary", use_container_width=True):
        st.session_state["postmortem_rca"] = api("GET", "/incidents/postmortem-summary")
    if right.button("Export RCA Pack", use_container_width=True):
        pack = api("POST", "/incidents/rca-pack")
        st.session_state["rca_pack"] = pack
        st.session_state["postmortem_rca"] = pack["pack"]["postmortem_summary"]
        st.success(f"RCA Pack exported: {pack['markdown_path']}")

    summary = st.session_state.get("postmortem_rca") or api("GET", "/incidents/postmortem-summary")
    st.session_state["postmortem_rca"] = summary
    readiness = summary["readiness_summary"]
    root = summary["root_cause_category"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Severity", summary["severity"].upper())
    c2.metric("RCA readiness", readiness["status"])
    c3.metric("Root cause", root["category"])
    c4.metric("Open actions", readiness["open_corrective_action_count"])

    st.subheader("Incident Summary")
    st.json(summary["incident_summary"])

    st.subheader("Root Cause")
    st.json(root)

    st.subheader("Corrective Action Tracking")
    st.dataframe(summary["corrective_actions"], use_container_width=True, hide_index=True)

    st.subheader("Customer Follow-up State")
    st.json(summary["customer_follow_up_state"])

    st.subheader("Trace Links")
    st.json(summary["trace_links"])

    st.subheader("Scenario Coverage")
    st.dataframe(summary["scenario_coverage"]["scenarios"], use_container_width=True, hide_index=True)

    st.subheader("Proof Commands")
    for command in summary["local_proof_commands"]:
        st.code(command)

    pack = st.session_state.get("rca_pack")
    if pack:
        st.caption(f"Markdown: {pack['markdown_path']}")
        st.caption(f"JSON: {pack['json_path']}")
        st.download_button(
            "Download RCA Pack",
            data=pack["markdown"],
            file_name=f"{pack['pack_id']}.md",
            mime="text/markdown",
        )
        st.markdown(pack["markdown"])
        with st.expander("RCA Pack JSON"):
            st.json(pack["pack"])
