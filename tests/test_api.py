from pathlib import Path


def test_auth_and_health(client):
    assert client.get("/health").status_code == 200
    assert client.get("/tickets").status_code == 401
    token = client.post("/auth/demo-token").json()["token"]
    response = client.get("/tickets", headers={"X-API-Key": token})
    assert response.status_code == 200
    assert len(response.json()) >= 5


def test_analyze_trace_and_approval(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    ticket = client.get("/tickets", headers=headers).json()[0]
    run = client.post(f"/tickets/{ticket['id']}/analyze", headers=headers).json()
    assert run["status"] == "awaiting_approval"
    trace = client.get(f"/runs/{run['id']}/trace", headers=headers).json()
    assert {event["node_name"] for event in trace} >= {
        "intake_classifier",
        "sla_risk_scorer",
        "knowledge_retriever",
        "customer_reply_drafter",
        "engineering_escalation_drafter",
        "qa_evaluator",
        "human_approval",
    }
    approvals = client.get("/approvals", headers=headers).json()
    assert approvals
    approved = client.post(
        f"/runs/{run['id']}/approve",
        headers=headers,
        json={"reviewer": "lead", "reviewer_notes": "ship it"},
    ).json()
    assert approved["status"] == "completed"


def test_metrics_and_audit(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    assert "run_count" in client.get("/metrics/agent-performance", headers=headers).json()
    assert isinstance(client.get("/audit/events", headers=headers).json(), list)


def test_approval_dispatch_writes_outbox(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "Enterprise SSO outage blocking all agents",
            "body": "SAML SSO login is down for all agents. Production outage and SLA breach risk.",
            "priority": "urgent",
            "customer_tier": "enterprise",
            "tags": ["auth", "sso", "outage"],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()

    approved = client.post(
        f"/runs/{run['run_id']}/approve",
        headers=headers,
        json={"decided_by": "lead", "note": "dispatch"},
    ).json()
    assert approved["status"] == "completed"

    outbox = client.get("/integrations/outbox", headers=headers).json()
    run_events = [event for event in outbox if event["run_id"] == run["run_id"]]
    assert {event["action_type"] for event in run_events} >= {
        "customer_reply",
        "zendesk_update",
        "engineering_escalation",
        "jira_issue",
        "slack_alert",
    }
    assert all(event["status"] == "dispatched" for event in run_events)
    assert all(event["destination"] and event["payload"] for event in run_events)
    detail = client.get(f"/integrations/outbox/{run_events[0]['id']}", headers=headers).json()
    assert detail["id"] == run_events[0]["id"]


def test_playbook_recommendation_ranks_matching_playbook(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "Enterprise SSO outage blocking all agents",
            "body": "SAML SSO login is down for all agents. Production outage and SLA breach risk.",
            "priority": "urgent",
            "customer_tier": "enterprise",
            "tags": ["auth", "sso", "outage"],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()

    assert run["state"]["playbook_recommendations"][0]["id"] == "pb_sso_outage"
    response = client.post(
        "/playbooks/recommend",
        headers=headers,
        json={"ticket_id": ticket["ticket_id"], "top_n": 3},
    )
    assert response.status_code == 200, response.text
    recommendations = response.json()["recommendations"]

    assert recommendations[0]["id"] == "pb_sso_outage"
    assert recommendations[0]["confidence"] >= recommendations[1]["confidence"]
    assert recommendations[0]["match_reasons"]
    assert recommendations[0]["checklist"]
    assert "Incident Commander" in recommendations[0]["owner_roles"]


def test_remediation_checklist_export_writes_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "Webhook regression returns 5xx",
            "body": "Webhook deliveries are failing with 500 errors after a production regression.",
            "priority": "high",
            "customer_tier": "enterprise",
            "tags": ["webhook", "api", "regression"],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()

    response = client.post(f"/runs/{run['run_id']}/remediation-checklist", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    checklist = exported["checklist"]
    markdown = exported["markdown"]

    assert checklist["run_id"] == run["run_id"]
    assert checklist["selected_playbook"]["id"] == "pb_webhook_regression"
    assert checklist["classification"]["category"] == "bug"
    assert checklist["sla_risk"]["level"] in {"medium", "high"}
    assert checklist["approval_status"]["status"] == "pending"
    assert checklist["checklist"][0]["status"] == "pending"
    assert checklist["owners"]
    assert ticket["ticket_id"] in checklist["next_update_template"]
    assert "# Remediation Checklist" in markdown
    assert "## Selected Playbook" in markdown
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()


def test_failure_drill_retries_and_pauses_for_review(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    drill = client.post("/drills/tool-failure", headers=headers).json()
    run = drill["run"]
    failures = drill["failure_timeline"]

    assert drill["drill"]["drill_type"] == "tool_failure"
    assert run["status"] == "awaiting_approval"
    assert run["failure_state"]["attempts"] == 3
    assert len(failures) == 3
    assert {event["metadata"]["attempt"] for event in failures} == {1, 2, 3}
    assert drill["approval"]["status"] == "pending"
    assert "Knowledge retrieval failed after retries." in run["state"]["qa"]["findings"]

    metrics = client.get("/metrics/agent-performance", headers=headers).json()
    assert metrics["failure_drill_count"] >= 1
    assert metrics["tool_failure_count"] >= 3


def test_sla_breach_simulation_prioritizes_queue(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/drills/sla-breach-simulation", headers=headers)
    assert response.status_code == 200, response.text
    queue = response.json()["queue"]

    assert len(queue) == 4
    assert [item["risk_level"] for item in queue] == [
        "breached",
        "critical",
        "warning",
        "watch",
    ]
    assert [item["minutes_to_sla"] for item in queue] == [-12, 8, 45, 95]
    for item in queue:
        assert item["ticket_id"].startswith("tkt_")
        assert item["customer_tier"] in {"enterprise", "pro", "standard"}
        assert item["recommended_action"]
        assert item["run_id"].startswith("run_")
        assert item["approval_id"].startswith("apr_")


def test_incident_brief_export_contains_handoff_sections(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    simulation = client.post("/drills/sla-breach-simulation", headers=headers).json()
    run_id = simulation["queue"][0]["run_id"]

    response = client.post(f"/runs/{run_id}/incident-brief", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    brief = exported["brief"]
    markdown = exported["markdown"]

    assert brief["run_id"] == run_id
    assert brief["customer_impact"]["customer_tier"] == "enterprise"
    assert brief["classification"]["category"] in {"authentication", "incident"}
    assert brief["sla_risk"]["level"] == "high"
    assert brief["kb_citations"]
    assert brief["customer_reply_draft"]
    assert brief["engineering_escalation_draft"]
    assert brief["approval_status"]["status"] == "pending"
    assert brief["trace_summary"]["event_count"] >= 16
    assert brief["outbox_status"]["status"] == "pending_approval_no_dispatch"
    assert brief["recommended_next_steps"]
    assert "## Customer Impact" in markdown
    assert "## Engineering Escalation Draft" in markdown
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()


def test_ops_snapshot_and_weekly_review_export(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    failure_drill = client.post("/drills/tool-failure", headers=headers).json()
    simulation = client.post("/drills/sla-breach-simulation", headers=headers).json()
    run_id = simulation["queue"][0]["run_id"]
    brief = client.post(f"/runs/{run_id}/incident-brief", headers=headers).json()
    approved = client.post(
        f"/runs/{run_id}/approve",
        headers=headers,
        json={"decided_by": "lead", "note": "weekly review dispatch"},
    ).json()

    snapshot_response = client.get("/analytics/ops-snapshot", headers=headers)
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot = snapshot_response.json()

    assert snapshot["summary_metrics"]["ticket_count"] >= 5
    assert snapshot["summary_metrics"]["run_count"] >= 5
    assert snapshot["summary_metrics"]["pending_approval_count"] >= 1
    assert snapshot["counts"]["ticket_category"]
    assert snapshot["counts"]["sla_risk"]["high"] >= 1
    assert snapshot["counts"]["final_action"][approved["final_action"]] >= 1
    assert snapshot["counts"]["approval_status"]["approved"] >= 1
    assert snapshot["counts"]["outbox_destination"]
    assert snapshot["counts"]["failure_type"]["knowledge_retrieval_retry_exhausted"] >= 1
    assert snapshot["averages"]["latency_ms_per_run"] > 0
    assert snapshot["averages"]["tokens_per_run"] > 0
    assert snapshot["top_risky_tickets"]
    assert snapshot["recommended_operational_actions"]
    assert snapshot["sla_queue_highlights"][0]["risk_level"] == "breached"
    assert snapshot["failure_drill_summary"]["latest_run_id"] == failure_drill["run"]["run_id"]
    assert snapshot["outbox_dispatch_summary"]["dispatch_count"] >= 1
    assert snapshot["incident_briefs"][0]["markdown_path"] == brief["markdown_path"]

    review_response = client.post("/analytics/weekly-review", headers=headers)
    assert review_response.status_code == 200, review_response.text
    exported = review_response.json()
    review = exported["review"]
    markdown = exported["markdown"]

    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert review["summary_metrics"]["run_count"] == snapshot["summary_metrics"]["run_count"]
    assert review["failure_drill_summary"]["drill_count"] >= 1
    assert review["outbox_dispatch_summary"]["dispatch_count"] >= 1
    assert review["incident_briefs"][0]["run_id"] == run_id
    assert review["next_actions"]
    assert "# Weekly Ops Review" in markdown
    assert "## SLA Queue Highlights" in markdown
    assert "## Failure Drill Summary" in markdown
    assert "## Outbox Dispatch Summary" in markdown
    assert "## Incident Brief Links" in markdown


def test_slo_budget_and_optimization_report(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    drill = client.post("/drills/tool-failure", headers=headers).json()
    simulation = client.post("/drills/sla-breach-simulation", headers=headers).json()
    run_id = simulation["queue"][0]["run_id"]
    client.post(
        f"/runs/{run_id}/approve",
        headers=headers,
        json={"decided_by": "lead", "note": "dispatch for optimization report"},
    )

    slo_response = client.get("/ops/slo-budget", headers=headers)
    assert slo_response.status_code == 200, slo_response.text
    slo = slo_response.json()
    expected_metrics = {
        "agent_workflow_latency_ms",
        "token_usage_per_run",
        "cost_usd_per_run",
        "failure_count",
        "pending_approvals",
        "outbox_dispatch_delay_minutes",
    }

    assert slo["overall_status"] in {"pass", "warn", "fail"}
    assert set(slo["metrics"]) == expected_metrics
    for metric in expected_metrics:
        item = slo["metrics"][metric]
        assert item["status"] in {"pass", "warn", "fail"}
        assert "current_value" in item
        assert item["thresholds"]["pass_at_or_below"] <= item["thresholds"]["warn_at_or_below"]
        assert item["recommendation"]
    assert slo["metrics"]["failure_count"]["current_value"] >= 1
    assert slo["metrics"]["pending_approvals"]["current_value"] >= 1

    report_response = client.post("/ops/optimization-report", headers=headers)
    assert report_response.status_code == 200, report_response.text
    exported = report_response.json()
    report = exported["report"]
    markdown = exported["markdown"]

    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert "optimization_reports" in exported["markdown_path"]
    assert report["slo_statuses"]["failure_count"]["current_value"] >= 1
    assert report["top_slow_nodes"]
    assert report["high_token_nodes"]
    assert report["failure_hotspots"][0]["node"] == "knowledge_retriever"
    assert any(item["run_id"] == drill["run"]["run_id"] for item in report["approval_bottlenecks"])
    assert report["recommended_fixes"]
    assert "## SLO Statuses" in markdown
    assert "## Top Slow Nodes" in markdown
    assert "## High-Token Nodes" in markdown
    assert "## Failure Hotspots" in markdown
    assert "## Approval Bottlenecks" in markdown
    assert "## Recommended Fixes" in markdown


def test_smoke_matrix_and_launch_checklist_export(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    smoke_response = client.get("/ops/smoke-matrix", headers=headers)
    assert smoke_response.status_code == 200, smoke_response.text
    smoke = smoke_response.json()

    assert smoke["readiness_summary"]["status"] == "ready"
    assert smoke["readiness_summary"]["label"] == "launch readiness"
    assert smoke["readiness_summary"]["local_mock_only"] is True
    endpoints = {row["endpoint"] for row in smoke["matrix"]}
    assert "GET /ops/smoke-matrix" in endpoints
    assert "POST /ops/launch-checklist" in endpoints
    assert "POST /demo/evidence-pack" in endpoints
    launch_row = next(row for row in smoke["matrix"] if row["endpoint"] == "POST /ops/launch-checklist")
    assert launch_row["expected_status"] == 200
    assert launch_row["artifact_expectation"]["path"] == "data/launch_checklists"
    assert "curl.exe" in launch_row["sample_commands"]["curl"]
    assert "Invoke-RestMethod" in launch_row["sample_commands"]["powershell"]

    export_response = client.post("/ops/launch-checklist", headers=headers)
    assert export_response.status_code == 200, export_response.text
    exported = export_response.json()
    checklist = exported["checklist"]
    markdown = exported["markdown"]

    assert "launch_checklists" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert checklist["demo_command"] == r".\.venv\Scripts\python.exe scripts\demo_run.py"
    assert len(checklist["api_smoke_matrix"]) == smoke["readiness_summary"]["total_checks"]
    assert len(checklist["interviewer_talking_points"]) == 5
    assert len(checklist["jd_skills_demonstrated"]) >= 5
    assert any(item["directory"] == "data/demo_packs" for item in checklist["generated_artifacts"])
    assert "# Launch Checklist" in markdown
    assert "## API Smoke Matrix" in markdown
    assert "## Troubleshooting Notes" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "POST /ops/launch-checklist" in saved


def test_portfolio_evidence_index_maps_required_skills(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.get("/portfolio/evidence-index", headers=headers)
    assert response.status_code == 200, response.text
    index = response.json()

    assert index["portfolio_title"] == "Portfolio Evidence Index"
    assert index["local_mock_only"] is True
    assert index["fresh_clone_ready"] is True
    assert index["evidence_score"] == 100
    assert index["evidence_count"] >= 10
    assert len(index["jd_skill_evidence"]) == index["evidence_count"]
    skill_ids = {item["skill_id"] for item in index["jd_skill_evidence"]}
    assert {
        "stateful_agent_workflow",
        "human_approval",
        "fake_integrations",
        "retry_failure_handling",
        "observability_metrics",
        "launch_readiness",
        "kb_quality",
        "policy_guardrails",
        "replay_lab",
        "leadership_incident_artifacts",
    } <= skill_ids
    endpoints = {
        endpoint
        for item in index["jd_skill_evidence"]
        for endpoint in item["endpoints"]
    }
    assert "POST /portfolio/interview-pack" not in endpoints
    assert "POST /replay-lab/report" in endpoints
    assert "POST /policies/export" in endpoints
    assert any("portfolio_packs" in item["directory"] for item in index["artifact_inventory"])
    assert any("evidence score" in command for command in index["verification_commands"])


def test_portfolio_interview_pack_exports_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/portfolio/interview-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["evidence_score"] == 100
    assert exported["evidence_count"] >= 10
    assert "portfolio_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert len(pack["three_minute_demo_script"]) == 5
    assert 8 <= len(pack["technical_talking_points"]) <= 10
    assert pack["architecture_walkthrough"]
    assert pack["failure_mode_story"]["proof"]
    assert pack["metrics_eval_summary"]["portfolio_evidence_count"] == exported["evidence_count"]
    assert pack["resume_github_readme_bullets"]
    assert "Portfolio Evidence" in markdown
    assert "Interview Pack" in markdown
    assert "## 3-Minute Demo Script" in markdown
    assert "## Failure Mode Story" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "portfolio/evidence-index" in saved
    assert "portfolio_interview_pack_markdown" in saved


def test_release_quality_gate_returns_publish_readiness(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.get("/release/quality-gate", headers=headers)
    assert response.status_code == 200, response.text
    gate = response.json()

    assert gate["title"] == "Release Candidate Quality Gate"
    assert gate["mode"] == "local-deterministic-release-candidate-gate"
    assert gate["status"] in {"ready", "ready_with_warnings"}
    assert gate["score"] >= 90
    assert gate["blockers"] == []
    assert set(gate["coverage"]) == {"ci", "docs", "tests", "eval", "demo", "api", "artifacts"}
    assert gate["coverage"]["api"]["checks"]["quality_gate_route"] is True
    assert gate["coverage"]["api"]["checks"]["publish_pack_route"] is True
    assert gate["coverage"]["artifacts"]["release_pack_directory"] == "data/release_packs"
    assert gate["publish_readiness"]["ready_to_commit"] is True
    assert gate["publish_readiness"]["ready_to_push"] is True
    assert gate["local_only_notes"]
    endpoints = {item["endpoint"] for item in gate["endpoint_inventory"]}
    assert "GET /release/quality-gate" in endpoints
    assert "POST /release/publish-pack" in endpoints
    commands = [item["command"] for item in gate["verification_checklist"]]
    assert any("pytest" in command for command in commands)
    assert any("release/quality-gate" in command for command in commands)


def test_release_publish_pack_exports_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/release/publish-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["gate_status"] in {"ready", "ready_with_warnings"}
    assert exported["gate_score"] >= 90
    assert "release_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["title"] == "Release Candidate Publish Pack"
    assert pack["quality_gate"]["title"] == "Release Candidate Quality Gate"
    assert pack["release_summary"]
    assert len(pack["verification_commands"]) == 6
    assert len(pack["expected_outputs"]) == 6
    assert pack["screenshots_manual_verification_placeholders"]
    assert pack["github_repo_checklist"]
    assert pack["commit_push_readiness_notes"]
    assert pack["recruiter_review_notes"]
    assert pack["known_limitations"]
    assert "GET /release/quality-gate" in {item["endpoint"] for item in pack["endpoint_inventory"]}
    assert any(item["directory"] == "data/release_packs" for item in pack["artifact_inventory"])
    assert "# Release Candidate Publish Pack" in markdown
    assert "## Release Gate" in markdown
    assert "## Verification Commands" in markdown
    assert "## GitHub Repo Checklist" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "release_publish_pack_markdown" in saved
    assert "release/quality-gate" in saved


def test_reviewer_quickstart_returns_runnable_review_path(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.get("/reviewer/quickstart", headers=headers)
    assert response.status_code == 200, response.text
    quickstart = response.json()

    assert quickstart["title"] == "Reviewer Quickstart"
    assert quickstart["status"] == "ready"
    assert quickstart["local_mock_only"] is True
    assert quickstart["auth"]["demo_token_endpoint"] == "POST /auth/demo-token"
    assert quickstart["one_command_demo"] == r".\.venv\Scripts\python.exe scripts\demo_run.py"
    assert "POST /reviewer/walkthrough-pack" in quickstart["endpoint_walkthrough_order"]
    assert "POST /demo/evidence-pack" in quickstart["endpoint_walkthrough_order"]
    assert len(quickstart["agent_workflow_walkthrough"]) >= 6
    assert quickstart["artifact_proof_count"] == len(quickstart["artifact_proof_map"])
    assert any(item["directory"] == "data/reviewer_packs" for item in quickstart["artifact_proof_map"])
    assert any("reviewer/quickstart" in command for command in quickstart["verification_commands"])
    assert any("proof tour" in expected for expected in quickstart["expected_outputs"])
    assert set(quickstart["role_specific_reviewer_notes"]) == {
        "recruiter",
        "engineering_manager",
        "senior_engineer",
    }


def test_reviewer_walkthrough_pack_exports_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/reviewer/walkthrough-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["quickstart_status"] == "ready"
    assert exported["artifact_proof_count"] >= 10
    assert "reviewer_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["title"] == "Reviewer Walkthrough Pack"
    assert pack["recruiter_friendly_story"]
    assert pack["engineer_deep_dive_path"]
    assert pack["command_checklist"]
    assert pack["api_workflow_proof_tour"][0]["tour_name"] == "reviewer proof tour"
    assert pack["artifacts_to_inspect"]
    assert pack["limitations"]
    assert "GET /reviewer/quickstart" in pack["github_readme_blurb"]
    assert "# Reviewer Walkthrough Pack" in markdown
    assert "## Recruiter-Friendly Story" in markdown
    assert "## API / Workflow Proof Tour" in markdown
    assert "## GitHub README Blurb" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "reviewer_walkthrough_pack_markdown" in saved
    assert "reviewer/walkthrough-pack" in saved


def test_artifact_inventory_returns_reviewer_artifact_map(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    client.post("/reviewer/walkthrough-pack", headers=headers)
    response = client.get("/artifacts/inventory", headers=headers)
    assert response.status_code == 200, response.text
    inventory = response.json()

    assert inventory["title"] == "Artifact Inventory"
    assert inventory["local_mock_only"] is True
    assert inventory["artifact_count"] >= 18
    assert inventory["artifact_index_directory"].endswith("artifact_indexes")
    assert inventory["freshness_notes"]
    directories = {item["directory"] for item in inventory["artifacts"]}
    assert "data/artifact_indexes" in directories
    assert "data/reviewer_packs" in directories
    reviewer_pack = next(item for item in inventory["artifacts"] if item["directory"] == "data/reviewer_packs")
    assert reviewer_pack["producer_endpoint"] == "POST /reviewer/walkthrough-pack"
    assert reviewer_pack["ignored_status"]["ignored_by_default"] is True
    assert "reviewer" in reviewer_pack["reviewer_purpose"].lower()
    assert reviewer_pack["latest_files"]
    assert reviewer_pack["freshness"]["status"] == "generated"
    artifact_index = next(item for item in inventory["artifacts"] if item["directory"] == "data/artifact_indexes")
    assert artifact_index["producer_endpoint"] == "POST /artifacts/readme-checklist"
    assert "README" in artifact_index["name"]
    assert any("artifacts/inventory" in command for command in inventory["local_commands"]["verify"])


def test_readme_checklist_pack_exports_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/artifacts/readme-checklist", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["artifact_count"] >= 18
    assert "artifact_indexes" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["title"] == "README Checklist Pack"
    assert pack["readme_badge_suggestions"]
    assert pack["readme_checklist_suggestions"]
    assert pack["reviewer_proof_checklist"]
    assert pack["cleanup_and_regeneration_notes"]
    assert any(item["directory"] == "data/artifact_indexes" for item in pack["artifact_inventory"])
    assert any(item["proof"] == "Artifact Inventory endpoint" for item in pack["reviewer_proof_checklist"])
    assert "# README Checklist Pack" in markdown
    assert "## Artifact Inventory" in markdown
    assert "## Reviewer Proof Checklist" in markdown
    assert "## Cleanup and Regeneration Notes" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "readme_checklist_markdown" in saved
    assert "artifacts/readme-checklist" in saved


def test_dashboard_smoke_reports_ui_source_wiring(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.get("/ui/dashboard-smoke", headers=headers)
    assert response.status_code == 200, response.text
    smoke = response.json()

    assert smoke["title"] == "Dashboard Smoke"
    assert smoke["mode"] == "local-deterministic-dashboard-source-smoke"
    assert smoke["status"] == "pass"
    assert smoke["local_mock_only"] is True
    assert smoke["summary"]["failed_checks"] == 0
    labels = {item["label"] for item in smoke["expected_views"] if item["present"]}
    assert "UI Verification" in labels
    endpoints = {item["endpoint"]: item for item in smoke["endpoint_references"]}
    assert endpoints["GET /ui/dashboard-smoke"]["dashboard_reference_present"] is True
    assert endpoints["GET /ui/dashboard-smoke"]["route_present"] is True
    assert endpoints["POST /ui/verification-pack"]["dashboard_reference_present"] is True
    assert endpoints["POST /ui/verification-pack"]["route_present"] is True
    artifact_tabs = {item["tab_label"]: item for item in smoke["generated_artifact_tabs"]}
    assert artifact_tabs["UI Verification"]["artifact_directory"] == "data/ui_verification"
    assert artifact_tabs["UI Verification"]["endpoint_reference_present"] is True
    assert smoke["local_run_commands"]["dashboard"] == (
        r".\.venv\Scripts\streamlit.exe run dashboard\streamlit_app.py"
    )
    assert any("browser" in item.lower() for item in smoke["limitations"])


def test_ui_verification_pack_exports_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/ui/verification-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["status"] == "pass"
    assert "ui_verification" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["title"] == "UI Verification Pack"
    assert pack["dashboard_smoke"]["status"] == "pass"
    assert pack["streamlit_run_command"] == (
        r".\.venv\Scripts\streamlit.exe run dashboard\streamlit_app.py"
    )
    assert pack["reviewer_checklist"]
    assert pack["screenshot_placeholders"]
    assert pack["troubleshooting"]
    assert pack["limitations"]
    assert "Dashboard Smoke" in markdown
    assert "## Screenshot Placeholders" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "ui_verification_markdown" in saved
    assert "ui/dashboard-smoke" in saved


def test_final_handoff_audit_checks_docs_demo_and_artifacts(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.get("/handoff/final-audit", headers=headers)
    assert response.status_code == 200, response.text
    audit = response.json()

    assert audit["title"] == "README Consistency Final Audit"
    assert audit["mode"] == "local-deterministic-readme-consistency-audit"
    assert audit["status"] == "ready"
    assert audit["score"] == 100
    assert audit["blockers"] == []
    expected_checks = {
        "readme_endpoint_mentions",
        "docs_api_coverage",
        "architecture_evaluation_workflow_coverage",
        "demo_output_claims",
        "scripts_present",
        "dashboard_smoke_script_present",
        "generated_artifact_directory_docs",
        "local_mock_azure_limitation_clarity",
    }
    assert set(audit["checks"]) == expected_checks
    assert all(check["status"] == "pass" for check in audit["checks"].values())
    assert "GET /handoff/final-audit" in audit["endpoint_inventory_summary"]["final_handoff_endpoints"]
    assert "POST /handoff/final-pack" in audit["endpoint_inventory_summary"]["final_handoff_endpoints"]
    assert audit["artifact_inventory_summary"]["final_handoff_directory"] == "data/final_handoff"
    assert audit["artifact_inventory_summary"]["final_handoff_defined"] is True
    assert audit["dashboard_smoke_summary"]["failed_checks"] == 0
    assert audit["local_only_notes"]


def test_final_handoff_pack_exports_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/handoff/final-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["status"] == "ready"
    assert exported["score"] == 100
    assert "final_handoff" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["title"] == "Final Handoff Pack"
    assert pack["final_audit"]["title"] == "README Consistency Final Audit"
    assert pack["exact_clone_run_commands"][0].startswith("git clone")
    assert len(pack["end_to_end_verification_order"]) == 7
    assert pack["endpoint_inventory_summary"]["implemented_endpoint_count"] >= 55
    assert pack["artifact_inventory_summary"]["final_handoff_directory"] == "data/final_handoff"
    assert pack["dashboard_smoke_summary"]["failed_checks"] == 0
    assert "GET /handoff/final-audit" in pack["recruiter_facing_final_readme_blurb"]
    assert "# Final Handoff Pack" in markdown
    assert "## README Consistency Checks" in markdown
    assert "## End-to-End Verification Order" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "final_handoff_markdown" in saved
    assert "handoff/final-pack" in saved


def test_git_readiness_reports_branch_hygiene_and_publish_checks(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.get("/git/readiness", headers=headers)
    assert response.status_code == 200, response.text
    readiness = response.json()

    assert readiness["title"] == "GitHub Push Readiness + Branch Hygiene"
    assert readiness["mode"] == "local-read-only-git-inspection"
    assert readiness["status"] in {"ready", "review_required", "blocked"}
    assert readiness["git"]["detected"] is True
    assert "tracked_count" in readiness["tracked_untracked_modified_ignored_summary"]
    assert "source_doc_test_dashboard_files_changed" in readiness
    assert "source" in readiness["source_doc_test_dashboard_files_changed"]
    assert any(item["directory"] == "data/git_packs" for item in readiness["generated_artifact_directories"])
    assert readiness["github_actions_workflow"]["present"] is True
    assert readiness["readme_final_handoff_mention"]["mentions_final_handoff"] is True
    assert readiness["env_example"]["present"] is True
    assert readiness["dirty_worktree_guidance"]
    assert readiness["recommended_commit_groups"]
    assert any("git/readiness" in command for command in readiness["verification_commands"])


def test_git_push_plan_exports_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/git/push-plan", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["status"] in {"ready", "review_required", "blocked"}
    assert "git_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["title"] == "GitHub Push Readiness + Branch Hygiene Pack"
    assert pack["readiness"]["title"] == "GitHub Push Readiness + Branch Hygiene"
    assert any("git status --porcelain" in command for command in pack["non_destructive_review_commands"])
    assert pack["suggested_commit_grouping"]
    assert pack["do_not_commit_generated_artifact_notes"]
    assert pack["pre_push_verification_checklist"]
    assert pack["repo_limitations"]
    assert "GitHub Push Readiness" in pack["recruiter_github_readme_publish_blurb"]
    assert "# GitHub Push Readiness + Branch Hygiene Pack" in markdown
    assert "## Non-Destructive Review Commands" in markdown
    assert "## Pre-Push Verification Checklist" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "git_push_plan_markdown" in saved
    assert "git/readiness" in saved


def test_api_contract_audit_and_reviewer_collection_export(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    audit_response = client.get("/api/contract-audit", headers=headers)
    assert audit_response.status_code == 200, audit_response.text
    audit = audit_response.json()

    assert audit["status"] in {"ready", "ready_with_warnings"}
    assert audit["summary"]["openapi_route_count"] >= 40
    assert audit["summary"]["auth_protected_endpoint_count"] >= 35
    assert audit["openapi"]["route_count"] == audit["summary"]["openapi_route_count"]
    assert audit["dashboard_smoke_alignment"]["api_contract_view_present"] is True
    assert audit["dashboard_smoke_alignment"]["api_contract_endpoint_checks"]
    assert "GET /api/contract-audit" in {
        item["endpoint"]
        for item in audit["docs_api_coverage"]["important_endpoint_coverage"]
        if item["source"] == "docs/api.md"
    }
    assert any(
        item["producer"] == "POST /api/reviewer-collection"
        and item["artifact_directory"] == "data/api_contracts"
        for item in audit["generated_artifact_endpoint_coverage"]
    )
    assert "POST /api/reviewer-collection" in {
        item["endpoint"] for item in audit["demo_flow_endpoint_coverage"]["endpoints"]
    }

    collection_response = client.post("/api/reviewer-collection", headers=headers)
    assert collection_response.status_code == 200, collection_response.text
    exported = collection_response.json()
    collection = exported["collection"]
    markdown = exported["markdown"]

    assert "api_contracts" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert collection["title"] == "API Contract Reviewer Collection"
    assert collection["endpoint_inventory_by_domain"]["api"]
    assert collection["demo_token_flow"][0]["step"] == "Fetch demo token"
    assert any("X-API-Key" in row["curl"] for row in collection["sample_commands_by_domain"]["api"])
    assert any("dashboard_smoke.py" in command for command in collection["one_command_verification_order"])
    assert collection["recruiter_explanation"]
    assert collection["engineer_explanation"]
    assert "# API Contract Reviewer Collection" in markdown
    assert "## Generated Artifact Endpoints" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "api_reviewer_collection" in saved
    assert "OpenAPI" in saved


def test_ci_doctor_reports_publish_safety_checks(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.get("/ops/ci-doctor", headers=headers)
    assert response.status_code == 200, response.text
    doctor = response.json()

    assert doctor["title"] == "CI Doctor"
    assert doctor["mode"] == "local-deterministic-ci-doctor"
    assert doctor["status"] in {"ready", "ready_with_warnings", "blocked"}
    assert doctor["score"] >= 90
    expected_checks = {
        "pytest_command",
        "ruff_command",
        "eval_command",
        "demo_command",
        "github_actions_workflow",
        "docker_compose",
        "env_example",
        "readme_required_sections",
        "docs_presence",
        "generated_artifact_ignores",
        "dependency_files",
        "local_mock_provider_notes",
        "secret_scan",
    }
    assert set(doctor["checks"]) == expected_checks
    assert doctor["checks"]["pytest_command"]["details"]["command"] == r".\.venv\Scripts\python.exe -m pytest -q"
    assert "docker-compose.yml" in doctor["checks"]["docker_compose"]["details"]["file"]
    assert doctor["checks"]["generated_artifact_ignores"]["details"]["data_ignored"] is True
    assert doctor["dependency_inventory"]["required_files_present"] is True
    assert any(
        dependency.startswith("fastapi")
        for dependency in doctor["dependency_inventory"]["pyproject"]["dependencies"]
    )
    assert doctor["secret_scan_summary"]["label"] == "secret scan"
    assert doctor["secret_scan_summary"]["scanned_file_count"] > 0
    assert doctor["local_mock_provider_notes"]["external_services_required"] is False
    assert any("ops/audit-pack" in command for command in doctor["local_verification_commands"])
    assert any(item["item"] == "Review suspicious secret-pattern scan" for item in doctor["publish_safety_checklist"])


def test_audit_pack_exports_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/ops/audit-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["doctor_score"] >= 90
    assert "audit_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["ci_doctor"]["title"] == "CI Doctor"
    assert pack["dependency_inventory"]["required_files_present"] is True
    assert pack["secret_scan_summary"]["label"] == "secret scan"
    assert pack["publish_safety_checklist"]
    assert pack["remediation_notes"]
    assert len(pack["recruiter_interviewer_explanation"]) == 5
    assert "Local CI Doctor + Dependency/Secrets Audit Pack" in pack["title"]
    assert "# Audit Pack" in markdown
    assert "## CI Doctor" in markdown
    assert "## Dependency Inventory" in markdown
    assert "## Secret Scan Summary" in markdown
    assert "## Publish-Safety Checklist" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "audit_pack_markdown" in saved
    assert "ops/ci-doctor" in saved


def test_demo_scenario_runner_returns_artifacts_and_metrics(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/demo/scenario-run", headers=headers)
    assert response.status_code == 200, response.text
    scenario = response.json()
    metrics = scenario["summary_metrics"]

    assert scenario["mode"] == "local-deterministic"
    assert metrics["run_status"] == "completed"
    assert metrics["final_action"] == "customer_reply_sent+engineering_ticket_created"
    assert metrics["trace_event_count"] >= 16
    assert metrics["outbox_dispatch_count"] >= 5
    assert metrics["failure_drill_failed_attempts"] == 3
    assert metrics["sla_simulation_ticket_count"] == 4
    assert metrics["slo_overall_status"] in {"pass", "warn", "fail"}
    assert "POST /demo/scenario-run" not in scenario["endpoints_exercised"]
    assert "POST /runs/{run_id}/incident-brief" in scenario["endpoints_exercised"]
    assert "POST /ops/optimization-report" in scenario["endpoints_exercised"]
    assert scenario["links"]["trace"] == f"/runs/{metrics['run_id']}/trace"
    for path in scenario["artifact_paths"].values():
        assert Path(path).exists()


def test_demo_evidence_pack_writes_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/demo/evidence-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert "demo_packs" in exported["markdown_path"]
    assert pack["summary"]
    assert pack["summary_metrics"]["run_status"] == "completed"
    assert pack["summary_metrics"]["outbox_dispatch_count"] >= 5
    assert "POST /drills/tool-failure" in pack["api_endpoints_exercised"]
    assert "POST /analytics/weekly-review" in pack["api_endpoints_exercised"]
    assert "interview_talking_points" in pack
    assert len(pack["interview_talking_points"]) >= 4
    assert "weekly_review_markdown" in pack["artifact_paths"]
    assert "evidence_pack_markdown" in pack["artifact_paths"]
    assert "# Demo Evidence Pack" in markdown
    assert "## API Endpoints Exercised" in markdown
    assert "## Interview Talking Points" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "evidence_pack_markdown" in saved


def test_runbook_qa_bootstraps_sample_and_passes(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/ops/runbook-qa", headers=headers)
    assert response.status_code == 200, response.text
    qa = response.json()

    assert qa["status"] == "pass"
    assert qa["pass"] is True
    assert qa["score"] >= 85
    assert qa["missing_sections"] == []
    assert qa["sections"]["ticket_summary"]["present"] is True
    assert qa["sections"]["outbox_dispatches"]["present"] is True
    assert qa["sections"]["failure_drill_result"]["present"] is True
    assert "incident_brief_markdown" in qa["linked_artifact_paths"]
    assert "remediation_checklist_markdown" in qa["linked_artifact_paths"]
    assert "weekly_review_markdown" in qa["linked_artifact_paths"]
    assert "account_brief_markdown" in qa["linked_artifact_paths"]
    assert "optimization_report_markdown" in qa["linked_artifact_paths"]
    for path in qa["linked_artifact_paths"].values():
        assert Path(path).exists()


def test_runbook_qa_detects_missing_dispatch_and_failure_drill(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "Enterprise SSO outage awaiting approval",
            "body": "SAML SSO is down for production agents and SLA breach risk is high.",
            "customer": "Northstar Health",
            "priority": "urgent",
            "customer_tier": "enterprise",
            "tags": ["auth", "sso", "outage"],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()

    response = client.post(
        "/ops/runbook-qa",
        headers=headers,
        json={"run_id": run["run_id"]},
    )
    assert response.status_code == 200, response.text
    qa = response.json()

    assert qa["status"] == "fail"
    assert qa["pass"] is False
    assert "outbox_dispatches" in qa["missing_sections"]
    assert "failure_drill_result" in qa["missing_sections"]
    assert qa["sections"]["approval_state"]["present"] is True
    assert any("outbox" in fix.lower() for fix in qa["recommended_fixes"])
    assert any("tool-failure" in fix.lower() for fix in qa["recommended_fixes"])


def test_operator_readiness_pack_exports_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/ops/operator-readiness-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["readiness_status"] == "pass"
    assert exported["readiness_score"] >= 85
    assert "operator_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["runbook_qa"]["status"] == "pass"
    assert pack["critical_metrics"]["ops_summary"]["run_count"] >= 2
    assert "POST /ops/runbook-qa" in pack["endpoint_list"]
    assert "POST /ops/operator-readiness-pack" in pack["endpoint_list"]
    assert pack["local_demo_command"] == r".\.venv\Scripts\python.exe scripts\demo_run.py"
    assert len(pack["jd_skills_demonstrated"]) >= 5
    assert len(pack["interviewer_talking_points"]) == 5
    assert "operator_pack_markdown" in pack["artifact_paths"]
    assert "# Operator Readiness Pack" in markdown
    assert "## JD Skills Demonstrated" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "operator_pack_markdown" in saved


def test_customer_health_scores_account_risk(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "Northstar SSO production outage",
            "body": "SAML SSO is down in production and the SLA breach is near.",
            "customer": "Northstar Health",
            "customer_email": "ops@northstar.example",
            "priority": "urgent",
            "customer_tier": "enterprise",
            "tags": ["auth", "sso", "outage"],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()

    response = client.get("/customers/health", headers=headers)
    assert response.status_code == 200, response.text
    customers = response.json()["customers"]
    northstar = next(item for item in customers if item["customer_id"] == "northstar-health")

    assert northstar["account"] == "Northstar Health"
    assert northstar["ticket_count"] >= 1
    assert northstar["pending_count"] >= 1
    assert northstar["high_sla_risk_count"] >= 1
    assert northstar["pending_approval_count"] >= 1
    assert northstar["recommended_playbook_count"] >= 1
    assert 0 <= northstar["health_score"] < 100
    assert northstar["risk_level"] in {"at_risk", "critical"}
    assert northstar["recommended_action"]
    assert run["status"] == "awaiting_approval"


def test_account_brief_export_writes_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "Atlas webhook regression returns 5xx",
            "body": "Webhook delivery returns 5xx after a production regression and SLA breach risk.",
            "customer": "Atlas Logistics",
            "customer_email": "dev@atlas.example",
            "priority": "urgent",
            "customer_tier": "enterprise",
            "tags": ["webhook", "api", "regression"],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()

    response = client.post("/customers/atlas-logistics/account-brief", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    brief = exported["brief"]
    markdown = exported["markdown"]

    assert exported["customer_id"] == "atlas-logistics"
    assert brief["customer_health"]["account"] == "Atlas Logistics"
    assert brief["customer_health"]["high_sla_risk_count"] >= 1
    assert any(item["ticket_id"] == ticket["ticket_id"] for item in brief["active_tickets"])
    assert any(item["run_id"] == run["run_id"] for item in brief["recent_runs"])
    assert brief["recommended_playbooks"]
    assert brief["pending_approvals"]
    assert brief["outbox_summary"]["dispatch_count"] == 0
    assert brief["next_actions"]
    assert "# Account Brief: Atlas Logistics" in markdown
    assert "## Customer Health" in markdown
    assert "## Active Tickets" in markdown
    assert "## Recommended Playbooks" in markdown
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()


def test_replay_lab_detects_changed_decisions(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "API key rotation question",
            "body": "How can we rotate API keys safely with zero downtime?",
            "priority": "normal",
            "customer_tier": "standard",
            "tags": ["api"],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()
    approved = client.post(
        f"/runs/{run['run_id']}/approve",
        headers=headers,
        json={"decided_by": "lead", "note": "baseline approved"},
    ).json()

    response = client.post(
        f"/runs/{approved['run_id']}/replay-lab",
        headers=headers,
        json={
            "modifiers": {
                "sla_pressure": "critical",
                "kb_context": "conflicting",
                "adapter_health": "healthy",
                "confidence_override": 0.41,
                "approval_policy": "strict",
            }
        },
    )
    assert response.status_code == 200, response.text
    replay = response.json()

    changed = {item["decision"] for item in replay["comparison"]["changed_decisions"]}
    assert {"classification_confidence", "sla_risk", "final_action"} <= changed
    assert replay["replay"]["sla_risk"]["level"] == "high"
    assert replay["replay"]["classification"]["confidence"] == 0.41
    assert replay["replay"]["approval_required"] is True
    assert "decision_changed" in replay["comparison"]["risk_flags"]
    assert replay["comparison"]["risk_score"] >= 75
    assert replay["comparison"]["recommended_operator_action"]


def test_replay_lab_degraded_and_failing_paths(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    degraded = client.post(
        "/replay-lab/run",
        headers=headers,
        json={
            "modifiers": {
                "sla_pressure": "high",
                "kb_context": "full",
                "adapter_health": "degraded",
                "approval_policy": "standard",
            }
        },
    ).json()
    assert degraded["replay"]["tool_attempts"]["count"] == 2
    assert degraded["replay"]["tool_attempts"]["failed"] == 1
    assert "adapter_degraded" in degraded["comparison"]["risk_flags"]

    failing = client.post(
        "/replay-lab/run",
        headers=headers,
        json={
            "run_id": degraded["source_run_id"],
            "modifiers": {
                "sla_pressure": "critical",
                "kb_context": "missing",
                "adapter_health": "failing",
                "confidence_override": 0.2,
                "approval_policy": "standard",
            },
        },
    ).json()
    assert failing["replay"]["failure_state"]["node"] == "knowledge_retriever"
    assert failing["replay"]["tool_attempts"]["failed"] == 3
    assert "adapter_failure" in failing["comparison"]["risk_flags"]
    assert failing["replay"]["final_action"] == "awaiting_human_approval"


def test_replay_lab_fallback_endpoint_bootstraps_sample(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/replay-lab/run", headers=headers)
    assert response.status_code == 200, response.text
    replay = response.json()

    assert replay["source_run_id"].startswith("run_")
    assert replay["ticket_id"].startswith("tkt_")
    assert replay["mode"] == "local-deterministic-counterfactual"
    assert replay["original"]["classification"]["category"]
    assert replay["replay"]["estimates"]["tokens"] > 0


def test_replay_lab_report_export_writes_markdown_and_json(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post(
        "/replay-lab/report",
        headers=headers,
        json={
            "modifiers": {
                "sla_pressure": "critical",
                "kb_context": "missing",
                "adapter_health": "failing",
                "confidence_override": 0.25,
                "approval_policy": "strict",
            }
        },
    )
    assert response.status_code == 200, response.text
    exported = response.json()
    report = exported["report"]
    markdown = exported["markdown"]

    assert "replay_reports" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert report["comparison"]["comparison"]["risk_flags"]
    assert len(report["jd_skills_demonstrated"]) >= 5
    assert len(report["interviewer_talking_points"]) == 5
    assert "# Replay Lab Report" in markdown
    assert "## Change Risk Summary" in markdown
    assert "## Local Verification Commands" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "replay_report_markdown" in saved
