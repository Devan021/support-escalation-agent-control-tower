from pathlib import Path


def test_scenario_catalog_returns_enterprise_coverage(client, auth_headers):
    response = client.get("/scenarios/catalog", headers=auth_headers)
    assert response.status_code == 200, response.text
    catalog = response.json()

    assert catalog["title"] == "Scenario Dataset Catalog"
    assert catalog["scenario_count"] >= 8
    assert "scenario-catalog" in catalog["mode"]
    coverage = catalog["coverage_summary"]
    assert "scenario coverage" in coverage
    assert all(coverage["required_domains_present"].values())
    assert coverage["failure_state_expected_count"] >= 1
    assert coverage["tool_retry_expected_count"] >= 1
    assert coverage["low_confidence_review_expected_count"] >= 1
    assert {item["domain"] for item in catalog["scenarios"]} >= {
        "security",
        "billing",
        "data_export_privacy",
        "outage",
        "webhook_api",
        "enterprise_onboarding",
        "renewal_risk",
        "low_confidence_ambiguity",
    }


def test_scenario_eval_pack_exports_markdown_json_and_passes(client, auth_headers):
    response = client.post("/scenarios/eval-pack", headers=auth_headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    summary = exported["eval_summary"]
    pack = exported["pack"]

    assert exported["status"] == "pass"
    assert summary["scenario_count"] >= 8
    assert summary["classification_accuracy"]["accuracy_percent"] == 100
    assert summary["sla_routing"]["accuracy_percent"] == 100
    assert summary["approval_pause_coverage"]["accuracy_percent"] == 100
    assert summary["escalation_coverage"]["accuracy_percent"] == 100
    assert summary["low_confidence_review_coverage"]["accuracy_percent"] == 100
    assert summary["failure_state_coverage"]["accuracy_percent"] == 100
    assert summary["tool_retry_coverage"]["accuracy_percent"] == 100
    assert summary["represented_outcome_counts"]["failure_state_actual_count"] >= 1
    assert summary["represented_outcome_counts"]["tool_retry_actual_count"] >= 1
    assert "scenario_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert "Scenario Dataset Eval Coverage Pack" in exported["markdown"]
    assert "Failure/tool-retry coverage" in exported["markdown"]
    assert pack["artifact_paths"]["scenario_eval_pack_markdown"] == exported["markdown_path"]
    assert all(row["passed"] for row in pack["scenario_results"])
    assert any(row["actual"]["failure_state"] for row in pack["scenario_results"])
