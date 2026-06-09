from pathlib import Path


def test_on_call_summary_bootstraps_run_and_reports_readiness(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.get("/handoff/on-call-summary", headers=headers)
    assert response.status_code == 200, response.text
    summary = response.json()

    assert summary["title"] == "On-Call Handoff Summary"
    assert summary["run_id"].startswith("run_")
    assert summary["ticket_id"].startswith("tkt_")
    assert summary["trace_id"].startswith("trc_")
    assert summary["severity"] in {"sev1", "sev2", "sev3", "sev4"}
    assert summary["sla_deadline"]
    assert summary["trace_links"]["trace"] == f"/runs/{summary['run_id']}/trace"
    assert summary["customer_communication_readiness"]["communication readiness"]
    assert summary["approval_and_guardrail_status"]["approval_id"].startswith("apr_")
    assert summary["risk_gap_checklist"]
    assert len(summary["latest_drafts"]) >= 3
    assert summary["engineering_incident_ticket_summary"]["trace_id"] == summary["trace_id"]


def test_customer_comms_pack_writes_markdown_json_and_scenario_coverage(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.post("/handoff/customer-comms-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    coverage = pack["scenario_coverage"]

    assert "customer_comms_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert "# Customer Communications Simulation Pack" in exported["markdown"]
    assert "## Approval Checklist" in exported["markdown"]
    assert "## SLA / Customer Impact Timeline" in exported["markdown"]
    assert exported["scenario_count"] >= 5
    assert coverage["coverage_status"] == "pass"
    assert all(coverage["required_path_coverage"]["required_paths"].values())
    domains = {item["domain"] for item in coverage["scenarios"]}
    assert {"outage", "webhook_api", "billing", "data_export_privacy"} <= domains
    assert coverage["required_path_coverage"]["low_confidence_count"] >= 1
    assert coverage["required_path_coverage"]["tool_retry_count"] >= 1
    assert coverage["required_path_coverage"]["failure_state_count"] >= 1
    assert pack["approval_checklist"]
    assert pack["trace_ids"]
    assert any("customer_comms_packs" in command for command in pack["local_proof_commands"])


def test_customer_comms_pack_preserves_approval_pause_and_guardrails(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "Need help ???",
            "body": "Something looks odd.",
            "customer": "Greyline Media",
            "priority": "low",
            "customer_tier": "standard",
            "tags": [],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()

    summary = client.get("/handoff/on-call-summary", headers=headers).json()

    assert summary["run_id"] == run["run_id"]
    assert summary["status"] == "pending_approval"
    assert summary["customer_communication_readiness"]["status"] in {
        "blocked_guardrail_review",
        "pending_approval",
    }
    assert summary["approval_and_guardrail_status"]["pending_approval_count"] >= 1
    assert "low_confidence" in {
        item["risk"] for item in summary["risk_gap_checklist"]
    }
    assert summary["approval_and_guardrail_status"]["policy_decision"] in {
        "requires_approval",
        "blocked_pending_remediation",
    }


def test_dashboard_smoke_includes_on_call_handoff(client):
    token = client.post("/auth/demo-token").json()["token"]
    headers = {"X-API-Key": token}

    response = client.get("/ui/dashboard-smoke", headers=headers)
    assert response.status_code == 200, response.text
    smoke = response.json()

    views = {item["label"]: item for item in smoke["expected_views"]}
    endpoints = {item["endpoint"]: item for item in smoke["endpoint_references"]}
    artifacts = {item["artifact_directory"]: item for item in smoke["generated_artifact_tabs"]}

    assert smoke["status"] == "pass"
    assert views["On-Call Handoff"]["present"] is True
    assert endpoints["GET /handoff/on-call-summary"]["dashboard_reference_present"] is True
    assert endpoints["GET /handoff/on-call-summary"]["route_present"] is True
    assert endpoints["POST /handoff/customer-comms-pack"]["dashboard_reference_present"] is True
    assert endpoints["POST /handoff/customer-comms-pack"]["route_present"] is True
    assert artifacts["data/customer_comms_packs"]["tab_present"] is True
