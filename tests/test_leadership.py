from pathlib import Path


def _headers(client):
    token = client.post("/auth/demo-token").json()["token"]
    return {"X-API-Key": token}


def test_leadership_scorecard_returns_kpi_categories(client):
    headers = _headers(client)
    scenario = client.post("/demo/scenario-run", headers=headers).json()

    response = client.get("/leadership/scorecard", headers=headers)
    assert response.status_code == 200, response.text
    scorecard = response.json()

    expected_categories = {
        "automation_safety",
        "approval_health",
        "sla_risk",
        "escalation_quality",
        "retry_failure_behavior",
        "policy_blocks",
        "replay_risk",
        "customer_impact",
        "operator_readiness",
    }
    assert scorecard["mode"] == "local-deterministic-automation-kpi-scorecard"
    assert set(scorecard["kpi_categories"]) == expected_categories
    assert 0 <= scorecard["overall_score"] <= 100
    assert scorecard["readiness_status"] in {
        "leadership_ready",
        "review_ready_with_risks",
        "needs_attention",
    }
    assert scorecard["sample_window"]["run_count"] >= 1
    assert scorecard["trendish_local_values"]["replay_risk_score"] >= 0
    assert scorecard["trendish_local_values"]["policy_decision"]
    assert scorecard["kpi_categories"]["operator_readiness"]["local_values"][
        "readiness_score"
    ] >= 0
    for category in scorecard["kpi_categories"].values():
        assert 0 <= category["score"] <= 100
        assert category["status"] in {"healthy", "watch", "risk"}
        assert "local_values" in category
        assert category["recommended_actions"]
    assert "incident_narratives_latest" in scorecard["artifact_links"]
    assert scorecard["kpi_definitions"]["automation_safety"]
    assert scenario["summary_metrics"]["run_id"].startswith("run_")


def test_leadership_scorecard_surfaces_risk_flags(client):
    headers = _headers(client)
    client.post("/drills/tool-failure", headers=headers)
    client.post("/drills/sla-breach-simulation", headers=headers)

    scorecard = client.get("/leadership/scorecard", headers=headers).json()
    joined_flags = " ".join(scorecard["risk_flags"])

    assert "approval_health:pending_approvals" in scorecard["risk_flags"]
    assert "retry_failure_behavior:tool_retry_errors_recorded" in scorecard["risk_flags"]
    assert "sla_risk:high_sla_risk_tickets" in scorecard["risk_flags"]
    assert "pending" in joined_flags
    assert scorecard["kpi_categories"]["retry_failure_behavior"]["local_values"][
        "tool_failure_count"
    ] >= 3
    assert scorecard["recommended_actions"]


def test_leadership_review_pack_exports_markdown_and_json(client):
    headers = _headers(client)
    client.post("/demo/evidence-pack", headers=headers)

    response = client.post("/leadership/review-pack", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    review = exported["review"]
    markdown = exported["markdown"]

    assert exported["readiness_status"] == review["scorecard"]["readiness_status"]
    assert "leadership_reviews" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert review["scorecard"]["kpi_categories"]["automation_safety"]["score"] >= 0
    assert review["kpi_definitions"]["replay_risk"]
    assert review["local_evidence_links"]
    assert review["recommended_next_actions"]
    assert len(review["jd_skills_demonstrated"]) >= 5
    assert len(review["interviewer_talking_points"]) == 5
    assert "# Leadership Review Pack" in markdown
    assert "## Automation KPI Scorecard" in markdown
    assert "## Local Commands" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "leadership_review_markdown" in saved
