from pathlib import Path


def _analyze(client, headers, payload):
    ticket = client.post("/tickets/ingest", headers=headers, json=payload).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()
    return ticket, run


def test_postmortem_summary_returns_root_cause_actions_and_trace_links(client, auth_headers):
    ticket, run = _analyze(
        client,
        auth_headers,
        {
            "subject": "Webhook 500 regression after release",
            "body": "Webhook deliveries return 500 errors after production deploy with SLA concern.",
            "customer": "Atlas Logistics",
            "priority": "high",
            "customer_tier": "enterprise",
            "tags": ["webhook", "api", "regression"],
        },
    )

    response = client.get("/incidents/postmortem-summary", headers=auth_headers)
    assert response.status_code == 200, response.text
    summary = response.json()

    assert summary["title"] == "Postmortem RCA Summary"
    assert summary["run_id"] == run["run_id"]
    assert summary["ticket_id"] == ticket["ticket_id"]
    assert summary["root_cause_category"]["category"] == "product_or_api_incident"
    assert summary["severity"] in {"sev2", "sev3"}
    assert summary["timeline"]
    assert summary["contributing_factors"]
    assert summary["approval_comms_status"]["pending_approval_count"] >= 1
    assert summary["trace_links"]["trace"] == f"/runs/{run['run_id']}/trace"
    assert summary["corrective_actions"]
    assert summary["customer_follow_up_state"]["status"] == "pending_approval"
    assert summary["readiness_summary"]["open_corrective_action_count"] >= 1


def test_rca_pack_exports_markdown_json_and_reviewer_artifacts(client, auth_headers):
    _ticket, run = _analyze(
        client,
        auth_headers,
        {
            "subject": "Data export request includes deleted records",
            "body": "A regulated customer asked whether their data export includes deleted records and privacy handling.",
            "customer": "Evergreen Bank",
            "priority": "normal",
            "customer_tier": "standard",
            "tags": ["privacy", "data", "export", "compliance"],
        },
    )

    response = client.post("/incidents/rca-pack", headers=auth_headers, json={"run_id": run["run_id"]})
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert "rca_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["title"] == "Postmortem RCA + Corrective Action Tracking Pack"
    assert pack["postmortem_summary"]["root_cause_category"]["category"] == "privacy_data_handling"
    assert pack["trace_audit_evidence"]["trace_link"] == f"/runs/{run['run_id']}/trace"
    assert pack["action_owners"]
    assert pack["due_dates"]
    assert pack["customer_follow_up_state"]["next_step"]
    assert pack["reviewer_artifacts"]["export_endpoint"] == "POST /incidents/rca-pack"
    assert "# Postmortem RCA + Corrective Action Tracking Pack" in markdown
    assert "## Corrective Action Tracking" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "rca_pack_markdown" in saved
    assert "root cause" in saved


def test_rca_classifies_required_root_cause_scenarios(client, auth_headers):
    scenarios = [
        (
            {
                "subject": "Production login loop for all care coordinators",
                "body": "All users cannot login. Production outreach is blocked and this is an outage.",
                "customer": "Northstar Health",
                "priority": "urgent",
                "customer_tier": "enterprise",
                "tags": ["login", "incident", "outage", "sla"],
            },
            "product_or_api_incident",
        ),
        (
            {
                "subject": "Webhook API outage with local KB retrieval failure drill",
                "body": "Webhook deliveries are returning 5xx and support needs grounded escalation.",
                "customer": "Pinnacle Freight",
                "priority": "high",
                "customer_tier": "enterprise",
                "tags": ["webhook", "api", "regression", "force-kb-failure"],
            },
            "tool_failure_retry_exhausted",
        ),
        (
            {
                "subject": "Data export request includes deleted records question",
                "body": "Please verify deletion, export, privacy, and compliance handling before we answer.",
                "customer": "Evergreen Bank",
                "priority": "normal",
                "customer_tier": "standard",
                "tags": ["privacy", "data", "export", "compliance"],
            },
            "privacy_data_handling",
        ),
        (
            {
                "subject": "Renewal risk invoice credit dispute before QBR",
                "body": "The account is threatening renewal churn because billing shows duplicate seats and asks about refund options.",
                "customer": "SummitCloud Legal",
                "priority": "high",
                "customer_tier": "enterprise",
                "tags": ["billing", "invoice", "renewal", "refund", "sla"],
            },
            "billing_customer_risk",
        ),
        (
            {
                "subject": "Need help ???",
                "body": "Something looks odd.",
                "customer": "Greyline Media",
                "priority": "low",
                "customer_tier": "standard",
                "tags": [],
            },
            "ambiguous_low_confidence",
        ),
    ]

    for payload, expected_category in scenarios:
        _ticket, run = _analyze(client, auth_headers, payload)
        exported = client.post(
            "/incidents/rca-pack",
            headers=auth_headers,
            json={"run_id": run["run_id"]},
        ).json()
        summary = exported["pack"]["postmortem_summary"]
        assert summary["root_cause_category"]["category"] == expected_category
        assert summary["corrective_actions"]


def test_rca_pack_scenario_coverage_and_dashboard_api_smoke_wiring(client, auth_headers):
    exported = client.post("/incidents/rca-pack", headers=auth_headers).json()
    coverage = exported["pack"]["scenario_coverage"]

    assert exported["coverage_status"] == "pass"
    assert coverage["scenario_count"] >= 5
    assert all(coverage["required_paths"].values())
    assert {
        "product_or_api_incident",
        "tool_failure_retry_exhausted",
        "privacy_data_handling",
        "billing_customer_risk",
        "ambiguous_low_confidence",
    } <= set(coverage["root_cause_counts"])

    smoke = client.get("/ui/dashboard-smoke", headers=auth_headers).json()
    assert smoke["status"] == "pass"
    assert any(item["label"] == "Postmortem RCA" and item["present"] for item in smoke["expected_views"])
    assert any(
        item["endpoint"] == "GET /incidents/postmortem-summary"
        and item["dashboard_reference_present"]
        and item["route_present"]
        for item in smoke["endpoint_references"]
    )
    assert any(
        item["producer_endpoint"] == "POST /incidents/rca-pack"
        and item["tab_present"]
        and item["endpoint_reference_present"]
        for item in smoke["generated_artifact_tabs"]
    )

    contract = client.get("/api/contract-audit", headers=auth_headers).json()
    assert "GET /incidents/postmortem-summary" in {item["endpoint"] for item in contract["endpoint_inventory"]}
    assert any(
        item["producer"] == "POST /incidents/rca-pack"
        and item["artifact_directory"] == "data/rca_packs"
        for item in contract["generated_artifact_endpoint_coverage"]
    )

    inventory = client.get("/artifacts/inventory", headers=auth_headers).json()
    assert any(item["directory"] == "data/rca_packs" for item in inventory["artifacts"])
