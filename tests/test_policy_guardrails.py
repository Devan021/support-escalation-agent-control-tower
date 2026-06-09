from pathlib import Path


def _token_headers(client):
    token = client.post("/auth/demo-token").json()["token"]
    return {"X-API-Key": token}


def _analyzed_run(client, headers, **ticket_overrides):
    payload = {
        "subject": "API key rotation question",
        "body": "How can we rotate API keys safely with zero downtime for production clients?",
        "priority": "normal",
        "customer_tier": "standard",
        "tags": ["api", "how-to"],
    }
    payload.update(ticket_overrides)
    ticket = client.post("/tickets/ingest", headers=headers, json=payload).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()
    return ticket, run


def _simulate(client, headers, run_id, **payload):
    body = {"run_id": run_id}
    body.update(payload)
    response = client.post("/policies/simulate", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _rule_ids(simulation):
    return {rule["rule_id"] for rule in simulation["matched_rules"]}


def test_policy_rule_external_reply_requires_approval(client):
    headers = _token_headers(client)
    _, run = _analyzed_run(client, headers)

    simulation = _simulate(
        client,
        headers,
        run["run_id"],
        requested_actions=["customer_reply"],
    )

    assert "external_reply_requires_approval" in _rule_ids(simulation)
    assert simulation["policy_decision"] == "requires_approval"
    assert simulation["required_approval_type"] == "support_lead"
    assert "customer_reply" in simulation["blocked_actions"]


def test_policy_rule_low_confidence_blocks_customer_reply(client):
    headers = _token_headers(client)
    _, run = _analyzed_run(client, headers)

    simulation = _simulate(
        client,
        headers,
        run["run_id"],
        modifiers={"confidence_override": 0.21},
        requested_actions=["customer_reply"],
    )

    assert "low_confidence" in _rule_ids(simulation)
    assert "customer_reply" in simulation["blocked_actions"]
    assert simulation["policy_inputs"]["qa_confidence"] < simulation["policy_inputs"][
        "low_confidence_threshold"
    ]


def test_policy_rule_high_or_critical_sla_pressure(client):
    headers = _token_headers(client)
    _, run = _analyzed_run(client, headers)

    simulation = _simulate(
        client,
        headers,
        run["run_id"],
        modifiers={"sla_pressure": "critical"},
        requested_actions=["jira_issue", "slack_alert", "engineering_escalation"],
    )

    assert "high_or_critical_sla_pressure" in _rule_ids(simulation)
    assert "incident_commander" in simulation["approval_chain"]
    assert {"jira_issue", "slack_alert", "engineering_escalation"} <= set(
        simulation["blocked_actions"]
    )


def test_policy_rule_enterprise_or_vip_customer_tier(client):
    headers = _token_headers(client)
    _, run = _analyzed_run(
        client,
        headers,
        subject="Enterprise implementation planning",
        body="Customer asks for implementation planning and internal account coordination.",
        customer_tier="enterprise",
        tags=["implementation"],
    )

    simulation = _simulate(
        client,
        headers,
        run["run_id"],
        requested_actions=["slack_alert"],
    )

    assert "enterprise_or_vip_customer" in _rule_ids(simulation)
    assert "support_manager" in simulation["approval_chain"]
    assert "slack_alert" in simulation["blocked_actions"]


def test_policy_rule_adapter_degraded_or_failing(client):
    headers = _token_headers(client)
    _, run = _analyzed_run(client, headers)

    simulation = _simulate(
        client,
        headers,
        run["run_id"],
        modifiers={"adapter_health": "failing"},
        requested_actions=["slack_alert"],
    )

    assert "adapter_degraded_or_failing" in _rule_ids(simulation)
    assert simulation["policy_decision"] == "blocked_pending_remediation"
    assert simulation["required_approval_type"] in {"ops_lead", "policy_admin"}
    assert "slack_alert" in simulation["blocked_actions"]


def test_policy_rule_replay_risk_above_threshold(client):
    headers = _token_headers(client)
    _, run = _analyzed_run(client, headers)

    simulation = _simulate(
        client,
        headers,
        run["run_id"],
        replay_risk_threshold=10,
        requested_actions=["jira_issue"],
    )

    assert "replay_risk_above_threshold" in _rule_ids(simulation)
    assert simulation["policy_decision"] == "blocked_pending_remediation"
    assert "jira_issue" in simulation["blocked_actions"]


def test_policy_rule_missing_or_conflicting_kb_context(client):
    headers = _token_headers(client)
    _, run = _analyzed_run(client, headers)

    simulation = _simulate(
        client,
        headers,
        run["run_id"],
        modifiers={"kb_context": "conflicting"},
        requested_actions=["customer_reply"],
    )

    assert "missing_or_conflicting_kb_context" in _rule_ids(simulation)
    assert "knowledge_owner" in simulation["approval_chain"]
    assert "customer_reply" in simulation["blocked_actions"]


def test_policy_simulate_fallback_bootstraps_latest_or_sample(client):
    headers = _token_headers(client)

    response = client.post("/policies/simulate", headers=headers)
    assert response.status_code == 200, response.text
    simulation = response.json()

    assert simulation["source_run_id"].startswith("run_")
    assert simulation["ticket_id"].startswith("tkt_")
    assert simulation["mode"] == "local-deterministic-policy-simulator"
    assert simulation["matched_rules"]
    assert simulation["recommended_operator_action"]


def test_policy_export_writes_policy_pack_markdown_and_json(client):
    headers = _token_headers(client)
    _, run = _analyzed_run(client, headers)

    response = client.post(
        "/policies/export",
        headers=headers,
        json={
            "run_id": run["run_id"],
            "modifiers": {
                "sla_pressure": "critical",
                "kb_context": "missing",
                "adapter_health": "degraded",
                "confidence_override": 0.3,
            },
        },
    )
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert "policy_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["simulated_policies"]
    assert pack["matched_rules"]
    assert pack["approval_matrix"]
    assert len(pack["sample_scenario_outcomes"]) >= 5
    assert len(pack["jd_skills_demonstrated"]) >= 5
    assert len(pack["interviewer_talking_points"]) == 5
    assert "# Policy Guardrail Pack" in markdown
    assert "## Approval Matrix" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "policy_pack_markdown" in saved
