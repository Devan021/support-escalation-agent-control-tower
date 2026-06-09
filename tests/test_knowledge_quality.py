from pathlib import Path


def _headers(client):
    token = client.post("/auth/demo-token").json()["token"]
    return {"X-API-Key": token}


def test_knowledge_quality_audit_returns_coverage_score(client):
    headers = _headers(client)

    response = client.get("/knowledge/quality-audit", headers=headers)
    assert response.status_code == 200, response.text
    audit = response.json()

    assert audit["mode"] == "local-deterministic-knowledge-quality-auditor"
    assert 0 <= audit["kb_coverage_score"] <= 100
    assert audit["readiness_status"] in {
        "not_ready_refresh_required",
        "review_ready_with_kb_risks",
        "ready_for_agentic_escalation",
    }
    assert audit["metrics"]["coverage"]["required_ticket_types"] >= 5
    assert audit["metrics"]["coverage"]["covered_ticket_types"] >= 5
    assert "Knowledge Quality" not in audit["local_commands"][0]


def test_knowledge_quality_detects_conflicts_and_missing_citations(client):
    headers = _headers(client)

    audit = client.get("/knowledge/quality-audit", headers=headers).json()

    assert audit["metrics"]["citations"]["missing_citation_count"] >= 1
    assert audit["metrics"]["conflicts"]["conflict_count"] >= 1
    assert "missing_kb_citations" in audit["risk_flags"]
    assert "conflicting_guidance_detected" in audit["risk_flags"]
    assert any(
        "potential_conflicting_guidance" in item["reasons"]
        for item in audit["weak_or_missing_articles"]
    )


def test_knowledge_quality_endpoint_uses_workflow_retrieval_evidence(client):
    headers = _headers(client)
    ticket = client.post(
        "/tickets/ingest",
        headers=headers,
        json={
            "subject": "Webhook 5xx regression with SLA risk",
            "body": "Webhook deliveries return 5xx errors after a production regression.",
            "priority": "high",
            "customer_tier": "enterprise",
            "tags": ["webhook", "api", "regression"],
        },
    ).json()
    run = client.post(f"/tickets/{ticket['ticket_id']}/analyze", headers=headers).json()

    audit = client.get("/knowledge/quality-audit", headers=headers).json()
    retrieval_runs = audit["evidence_sources"]["workflow_retrieval_runs"]

    assert any(item["run_id"] == run["run_id"] for item in retrieval_runs)
    assert audit["metrics"]["retrieval_evidence"]["runs_with_kb_results"] >= 1
    assert any(item["ticket_type"] == "api_integrations" for item in audit["impacted_ticket_types"])


def test_kb_refresh_plan_exports_markdown_and_json(client):
    headers = _headers(client)

    response = client.post("/knowledge/refresh-plan", headers=headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    plan = exported["plan"]
    markdown = exported["markdown"]

    assert "kb_refresh_plans" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert plan["article_refresh_tasks"]
    assert plan["owners"]
    assert plan["acceptance_criteria"]
    assert plan["impacted_workflows"]
    assert len(plan["jd_skills_demonstrated"]) >= 5
    assert len(plan["interviewer_talking_points"]) == 5
    assert "# KB Refresh Plan" in markdown
    assert "## Article Refresh Tasks" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "kb_refresh_plan_markdown" in saved
