from datetime import datetime
from pathlib import Path


def _headers(client):
    token = client.post("/auth/demo-token").json()["token"]
    return {"X-API-Key": token}


def _approved_incident_run(client, headers):
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "Northstar SSO production outage",
            "body": "SAML SSO is down for all production support agents with SLA breach risk.",
            "customer": "Northstar Health",
            "customer_email": "ops@northstar.example",
            "priority": "urgent",
            "customer_tier": "enterprise",
            "tags": ["auth", "sso", "outage"],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()
    approved = client.post(
        f"/runs/{run['run_id']}/approve",
        headers=headers,
        json={"decided_by": "incident-lead", "note": "approved for narrative test"},
    ).json()
    return ticket, approved


def _event_times(events):
    return [datetime.fromisoformat(event["timestamp"]) for event in events]


def test_incident_timeline_returns_ordered_customer_impact_story(client):
    headers = _headers(client)
    _, run = _approved_incident_run(client, headers)

    response = client.post(
        "/incidents/timeline",
        headers=headers,
        json={"run_id": run["run_id"]},
    )
    assert response.status_code == 200, response.text
    timeline = response.json()
    phases = {event["phase"] for event in timeline["events"]}

    assert timeline["run_id"] == run["run_id"]
    assert timeline["fallback_used"] == "supplied_run"
    assert timeline["customer_impact_summary"]["account"] == "Northstar Health"
    assert timeline["customer_impact_summary"]["sla_risk"]["level"] == "high"
    assert _event_times(timeline["events"]) == sorted(_event_times(timeline["events"]))
    assert [event["sequence"] for event in timeline["events"]] == list(
        range(1, len(timeline["events"]) + 1)
    )
    assert {
        "ticket_intake",
        "triage_classification",
        "human_approval_decided",
        "customer_reply_sent",
        "engineering_ticket_created",
        "policy_guardrail_decision",
        "replay_risk_review",
        "remediation_plan",
    } <= phases
    assert timeline["internal_actions"]
    assert timeline["external_actions"]
    assert "incident_brief_markdown" in timeline["evidence_artifact_links"]
    assert "replay_report_markdown" in timeline["evidence_artifact_links"]


def test_incident_timeline_fallback_bootstraps_sample(client):
    headers = _headers(client)

    response = client.post("/incidents/timeline", headers=headers)
    assert response.status_code == 200, response.text
    timeline = response.json()

    assert timeline["fallback_used"] == "sample_bootstrap"
    assert timeline["run_id"].startswith("run_")
    assert timeline["ticket_id"].startswith("tkt_")
    assert timeline["impact_status"]
    assert any(event["phase"] == "ticket_intake" for event in timeline["events"])
    assert timeline["external_actions"]


def test_incident_timeline_policy_and_replay_annotations(client):
    headers = _headers(client)
    _, run = _approved_incident_run(client, headers)

    timeline = client.post(
        "/incidents/timeline",
        headers=headers,
        json={"run_id": run["run_id"]},
    ).json()

    policy = timeline["policy_annotations"]
    replay = timeline["replay_annotations"]
    assert policy["policy_decision"] in {"requires_approval", "blocked_pending_remediation"}
    assert policy["matched_rule_ids"]
    assert policy["blocked_actions"]
    assert replay["risk_score"] >= 70
    assert replay["risk_flags"]
    assert replay["changed_decisions"]
    assert timeline["unresolved_risks"]
    assert timeline["owner_next_steps"]


def test_incident_endpoints_return_404_for_unknown_run(client):
    headers = _headers(client)

    timeline = client.post(
        "/incidents/timeline",
        headers=headers,
        json={"run_id": "run_missing"},
    )
    narrative = client.post(
        "/incidents/executive-narrative",
        headers=headers,
        json={"run_id": "run_missing"},
    )

    assert timeline.status_code == 404
    assert narrative.status_code == 404


def test_executive_incident_narrative_exports_markdown_and_json(client):
    headers = _headers(client)
    _, run = _approved_incident_run(client, headers)

    response = client.post(
        "/incidents/executive-narrative",
        headers=headers,
        json={"run_id": run["run_id"]},
    )
    assert response.status_code == 200, response.text
    exported = response.json()
    narrative = exported["narrative"]
    markdown = exported["markdown"]

    assert exported["impact_status"] == narrative["impact_status"]
    assert "incident_narratives" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert "# Executive Incident Narrative" in markdown
    assert "## Customer Impact Timeline" in markdown
    assert "## Policy Guardrail Decision" in markdown
    assert "## Replay Risk" in markdown
    assert len(narrative["interviewer_talking_points"]) == 5
    assert len(narrative["jd_skills_demonstrated"]) >= 5
    assert "incident_narrative_markdown" in Path(exported["json_path"]).read_text(encoding="utf-8")
