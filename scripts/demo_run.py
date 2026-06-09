from pathlib import Path
import sys

import requests
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import create_app  # noqa: E402
from app.core.config import Settings  # noqa: E402


BASE = "http://localhost:8000"


def run_with_http_server() -> dict | None:
    try:
        token_payload = requests.post(f"{BASE}/auth/demo-token", timeout=3).json()
        token = token_payload.get("access_token") or token_payload["token"]
        headers = {"x-api-key": token}
        response = requests.post(
            f"{BASE}/demo/evidence-pack",
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        run_id = result["scenario"]["summary_metrics"]["run_id"]
        readiness_response = requests.post(
            f"{BASE}/ops/operator-readiness-pack",
            headers=headers,
            json={"run_id": run_id},
            timeout=60,
        )
        readiness_response.raise_for_status()
        result["operator_readiness_pack"] = readiness_response.json()
        policy_response = requests.post(
            f"{BASE}/policies/export",
            headers=headers,
            json={
                "run_id": run_id,
                "modifiers": {
                    "sla_pressure": "critical",
                    "kb_context": "conflicting",
                    "adapter_health": "degraded",
                    "confidence_override": 0.44,
                    "approval_policy": "strict",
                },
            },
            timeout=60,
        )
        policy_response.raise_for_status()
        result["policy_pack"] = policy_response.json()
        scorecard_response = requests.get(
            f"{BASE}/leadership/scorecard",
            headers=headers,
            timeout=60,
        )
        scorecard_response.raise_for_status()
        result["leadership_scorecard"] = scorecard_response.json()
        review_response = requests.post(
            f"{BASE}/leadership/review-pack",
            headers=headers,
            timeout=60,
        )
        review_response.raise_for_status()
        result["leadership_review_pack"] = review_response.json()
        kb_audit_response = requests.get(
            f"{BASE}/knowledge/quality-audit",
            headers=headers,
            timeout=60,
        )
        kb_audit_response.raise_for_status()
        result["knowledge_quality_audit"] = kb_audit_response.json()
        kb_plan_response = requests.post(
            f"{BASE}/knowledge/refresh-plan",
            headers=headers,
            timeout=60,
        )
        kb_plan_response.raise_for_status()
        result["kb_refresh_plan"] = kb_plan_response.json()
        smoke_response = requests.get(
            f"{BASE}/ops/smoke-matrix",
            headers=headers,
            timeout=60,
        )
        smoke_response.raise_for_status()
        result["smoke_matrix"] = smoke_response.json()
        checklist_response = requests.post(
            f"{BASE}/ops/launch-checklist",
            headers=headers,
            timeout=60,
        )
        checklist_response.raise_for_status()
        result["launch_checklist"] = checklist_response.json()
        evidence_index_response = requests.get(
            f"{BASE}/portfolio/evidence-index",
            headers=headers,
            timeout=60,
        )
        evidence_index_response.raise_for_status()
        result["portfolio_evidence_index"] = evidence_index_response.json()
        interview_pack_response = requests.post(
            f"{BASE}/portfolio/interview-pack",
            headers=headers,
            timeout=60,
        )
        interview_pack_response.raise_for_status()
        result["portfolio_interview_pack"] = interview_pack_response.json()
        release_gate_response = requests.get(
            f"{BASE}/release/quality-gate",
            headers=headers,
            timeout=60,
        )
        release_gate_response.raise_for_status()
        result["release_gate"] = release_gate_response.json()
        publish_pack_response = requests.post(
            f"{BASE}/release/publish-pack",
            headers=headers,
            timeout=60,
        )
        publish_pack_response.raise_for_status()
        result["release_publish_pack"] = publish_pack_response.json()
        quickstart_response = requests.get(
            f"{BASE}/reviewer/quickstart",
            headers=headers,
            timeout=60,
        )
        quickstart_response.raise_for_status()
        result["reviewer_quickstart"] = quickstart_response.json()
        walkthrough_pack_response = requests.post(
            f"{BASE}/reviewer/walkthrough-pack",
            headers=headers,
            timeout=60,
        )
        walkthrough_pack_response.raise_for_status()
        result["reviewer_walkthrough_pack"] = walkthrough_pack_response.json()
        ci_doctor_response = requests.get(
            f"{BASE}/ops/ci-doctor",
            headers=headers,
            timeout=60,
        )
        ci_doctor_response.raise_for_status()
        result["ci_doctor"] = ci_doctor_response.json()
        audit_pack_response = requests.post(
            f"{BASE}/ops/audit-pack",
            headers=headers,
            timeout=60,
        )
        audit_pack_response.raise_for_status()
        result["audit_pack"] = audit_pack_response.json()
        artifact_inventory_response = requests.get(
            f"{BASE}/artifacts/inventory",
            headers=headers,
            timeout=60,
        )
        artifact_inventory_response.raise_for_status()
        result["artifact_inventory"] = artifact_inventory_response.json()
        readme_checklist_response = requests.post(
            f"{BASE}/artifacts/readme-checklist",
            headers=headers,
            timeout=60,
        )
        readme_checklist_response.raise_for_status()
        result["readme_checklist_pack"] = readme_checklist_response.json()
        dashboard_smoke_response = requests.get(
            f"{BASE}/ui/dashboard-smoke",
            headers=headers,
            timeout=60,
        )
        dashboard_smoke_response.raise_for_status()
        result["dashboard_smoke"] = dashboard_smoke_response.json()
        ui_verification_response = requests.post(
            f"{BASE}/ui/verification-pack",
            headers=headers,
            timeout=60,
        )
        ui_verification_response.raise_for_status()
        result["ui_verification_pack"] = ui_verification_response.json()
        final_audit_response = requests.get(
            f"{BASE}/handoff/final-audit",
            headers=headers,
            timeout=60,
        )
        final_audit_response.raise_for_status()
        result["final_audit"] = final_audit_response.json()
        final_pack_response = requests.post(
            f"{BASE}/handoff/final-pack",
            headers=headers,
            timeout=60,
        )
        final_pack_response.raise_for_status()
        result["final_handoff_pack"] = final_pack_response.json()
        on_call_response = requests.get(
            f"{BASE}/handoff/on-call-summary",
            headers=headers,
            timeout=60,
        )
        on_call_response.raise_for_status()
        result["on_call_handoff"] = on_call_response.json()
        customer_comms_response = requests.post(
            f"{BASE}/handoff/customer-comms-pack",
            headers=headers,
            timeout=60,
        )
        customer_comms_response.raise_for_status()
        result["customer_comms_pack"] = customer_comms_response.json()
        git_readiness_response = requests.get(
            f"{BASE}/git/readiness",
            headers=headers,
            timeout=60,
        )
        git_readiness_response.raise_for_status()
        result["git_readiness"] = git_readiness_response.json()
        git_push_plan_response = requests.post(
            f"{BASE}/git/push-plan",
            headers=headers,
            timeout=60,
        )
        git_push_plan_response.raise_for_status()
        result["git_push_plan"] = git_push_plan_response.json()
        contract_audit_response = requests.get(
            f"{BASE}/api/contract-audit",
            headers=headers,
            timeout=60,
        )
        contract_audit_response.raise_for_status()
        result["api_contract_audit"] = contract_audit_response.json()
        reviewer_collection_response = requests.post(
            f"{BASE}/api/reviewer-collection",
            headers=headers,
            timeout=60,
        )
        reviewer_collection_response.raise_for_status()
        result["api_reviewer_collection"] = reviewer_collection_response.json()
        runtime_readiness_response = requests.get(
            f"{BASE}/runtime/demo-readiness",
            timeout=60,
        )
        runtime_readiness_response.raise_for_status()
        result["runtime_demo_readiness"] = runtime_readiness_response.json()
        runtime_pack_response = requests.post(
            f"{BASE}/runtime/demo-pack",
            headers=headers,
            timeout=60,
        )
        runtime_pack_response.raise_for_status()
        result["runtime_demo_pack"] = runtime_pack_response.json()
        scenario_catalog_response = requests.get(
            f"{BASE}/scenarios/catalog",
            headers=headers,
            timeout=60,
        )
        scenario_catalog_response.raise_for_status()
        result["scenario_catalog"] = scenario_catalog_response.json()
        scenario_eval_response = requests.post(
            f"{BASE}/scenarios/eval-pack",
            headers=headers,
            timeout=60,
        )
        scenario_eval_response.raise_for_status()
        result["scenario_eval_pack"] = scenario_eval_response.json()
        postmortem_response = requests.get(
            f"{BASE}/incidents/postmortem-summary",
            headers=headers,
            timeout=60,
        )
        postmortem_response.raise_for_status()
        result["postmortem_rca"] = postmortem_response.json()
        rca_pack_response = requests.post(
            f"{BASE}/incidents/rca-pack",
            headers=headers,
            timeout=60,
        )
        rca_pack_response.raise_for_status()
        result["rca_pack"] = rca_pack_response.json()
        result["mode"] = "http"
        return result
    except Exception:
        return None


def run_in_process() -> dict:
    state_file = ROOT / "data" / "demo_control_tower_state.db"
    for path in state_file.parent.glob(f"{state_file.name}*"):
        path.unlink(missing_ok=True)
    app = create_app(Settings(state_file=state_file))
    with TestClient(app) as client:
        token_payload = client.post("/auth/demo-token").json()
        token = token_payload.get("access_token") or token_payload["token"]
        response = client.post("/demo/evidence-pack", headers={"x-api-key": token})
        response.raise_for_status()
        result = response.json()
        run_id = result["scenario"]["summary_metrics"]["run_id"]
        readiness_response = client.post(
            "/ops/operator-readiness-pack",
            headers={"x-api-key": token},
            json={"run_id": run_id},
        )
        readiness_response.raise_for_status()
        result["operator_readiness_pack"] = readiness_response.json()
        policy_response = client.post(
            "/policies/export",
            headers={"x-api-key": token},
            json={
                "run_id": run_id,
                "modifiers": {
                    "sla_pressure": "critical",
                    "kb_context": "conflicting",
                    "adapter_health": "degraded",
                    "confidence_override": 0.44,
                    "approval_policy": "strict",
                },
            },
        )
        policy_response.raise_for_status()
        result["policy_pack"] = policy_response.json()
        scorecard_response = client.get("/leadership/scorecard", headers={"x-api-key": token})
        scorecard_response.raise_for_status()
        result["leadership_scorecard"] = scorecard_response.json()
        review_response = client.post("/leadership/review-pack", headers={"x-api-key": token})
        review_response.raise_for_status()
        result["leadership_review_pack"] = review_response.json()
        kb_audit_response = client.get("/knowledge/quality-audit", headers={"x-api-key": token})
        kb_audit_response.raise_for_status()
        result["knowledge_quality_audit"] = kb_audit_response.json()
        kb_plan_response = client.post("/knowledge/refresh-plan", headers={"x-api-key": token})
        kb_plan_response.raise_for_status()
        result["kb_refresh_plan"] = kb_plan_response.json()
        smoke_response = client.get("/ops/smoke-matrix", headers={"x-api-key": token})
        smoke_response.raise_for_status()
        result["smoke_matrix"] = smoke_response.json()
        checklist_response = client.post("/ops/launch-checklist", headers={"x-api-key": token})
        checklist_response.raise_for_status()
        result["launch_checklist"] = checklist_response.json()
        evidence_index_response = client.get("/portfolio/evidence-index", headers={"x-api-key": token})
        evidence_index_response.raise_for_status()
        result["portfolio_evidence_index"] = evidence_index_response.json()
        interview_pack_response = client.post("/portfolio/interview-pack", headers={"x-api-key": token})
        interview_pack_response.raise_for_status()
        result["portfolio_interview_pack"] = interview_pack_response.json()
        release_gate_response = client.get("/release/quality-gate", headers={"x-api-key": token})
        release_gate_response.raise_for_status()
        result["release_gate"] = release_gate_response.json()
        publish_pack_response = client.post("/release/publish-pack", headers={"x-api-key": token})
        publish_pack_response.raise_for_status()
        result["release_publish_pack"] = publish_pack_response.json()
        quickstart_response = client.get("/reviewer/quickstart", headers={"x-api-key": token})
        quickstart_response.raise_for_status()
        result["reviewer_quickstart"] = quickstart_response.json()
        walkthrough_pack_response = client.post("/reviewer/walkthrough-pack", headers={"x-api-key": token})
        walkthrough_pack_response.raise_for_status()
        result["reviewer_walkthrough_pack"] = walkthrough_pack_response.json()
        ci_doctor_response = client.get("/ops/ci-doctor", headers={"x-api-key": token})
        ci_doctor_response.raise_for_status()
        result["ci_doctor"] = ci_doctor_response.json()
        audit_pack_response = client.post("/ops/audit-pack", headers={"x-api-key": token})
        audit_pack_response.raise_for_status()
        result["audit_pack"] = audit_pack_response.json()
        artifact_inventory_response = client.get("/artifacts/inventory", headers={"x-api-key": token})
        artifact_inventory_response.raise_for_status()
        result["artifact_inventory"] = artifact_inventory_response.json()
        readme_checklist_response = client.post("/artifacts/readme-checklist", headers={"x-api-key": token})
        readme_checklist_response.raise_for_status()
        result["readme_checklist_pack"] = readme_checklist_response.json()
        dashboard_smoke_response = client.get("/ui/dashboard-smoke", headers={"x-api-key": token})
        dashboard_smoke_response.raise_for_status()
        result["dashboard_smoke"] = dashboard_smoke_response.json()
        ui_verification_response = client.post("/ui/verification-pack", headers={"x-api-key": token})
        ui_verification_response.raise_for_status()
        result["ui_verification_pack"] = ui_verification_response.json()
        final_audit_response = client.get("/handoff/final-audit", headers={"x-api-key": token})
        final_audit_response.raise_for_status()
        result["final_audit"] = final_audit_response.json()
        final_pack_response = client.post("/handoff/final-pack", headers={"x-api-key": token})
        final_pack_response.raise_for_status()
        result["final_handoff_pack"] = final_pack_response.json()
        on_call_response = client.get("/handoff/on-call-summary", headers={"x-api-key": token})
        on_call_response.raise_for_status()
        result["on_call_handoff"] = on_call_response.json()
        customer_comms_response = client.post(
            "/handoff/customer-comms-pack",
            headers={"x-api-key": token},
        )
        customer_comms_response.raise_for_status()
        result["customer_comms_pack"] = customer_comms_response.json()
        git_readiness_response = client.get("/git/readiness", headers={"x-api-key": token})
        git_readiness_response.raise_for_status()
        result["git_readiness"] = git_readiness_response.json()
        git_push_plan_response = client.post("/git/push-plan", headers={"x-api-key": token})
        git_push_plan_response.raise_for_status()
        result["git_push_plan"] = git_push_plan_response.json()
        contract_audit_response = client.get("/api/contract-audit", headers={"x-api-key": token})
        contract_audit_response.raise_for_status()
        result["api_contract_audit"] = contract_audit_response.json()
        reviewer_collection_response = client.post("/api/reviewer-collection", headers={"x-api-key": token})
        reviewer_collection_response.raise_for_status()
        result["api_reviewer_collection"] = reviewer_collection_response.json()
        runtime_readiness_response = client.get("/runtime/demo-readiness")
        runtime_readiness_response.raise_for_status()
        result["runtime_demo_readiness"] = runtime_readiness_response.json()
        runtime_pack_response = client.post("/runtime/demo-pack", headers={"x-api-key": token})
        runtime_pack_response.raise_for_status()
        result["runtime_demo_pack"] = runtime_pack_response.json()
        scenario_catalog_response = client.get("/scenarios/catalog", headers={"x-api-key": token})
        scenario_catalog_response.raise_for_status()
        result["scenario_catalog"] = scenario_catalog_response.json()
        scenario_eval_response = client.post("/scenarios/eval-pack", headers={"x-api-key": token})
        scenario_eval_response.raise_for_status()
        result["scenario_eval_pack"] = scenario_eval_response.json()
        postmortem_response = client.get("/incidents/postmortem-summary", headers={"x-api-key": token})
        postmortem_response.raise_for_status()
        result["postmortem_rca"] = postmortem_response.json()
        rca_pack_response = client.post("/incidents/rca-pack", headers={"x-api-key": token})
        rca_pack_response.raise_for_status()
        result["rca_pack"] = rca_pack_response.json()
        result["mode"] = "in-process"
        return result


def main():
    result = run_with_http_server() or run_in_process()
    scenario = result["scenario"]
    metrics = scenario["summary_metrics"]
    pack = result["pack"]
    readiness = result["operator_readiness_pack"]
    policy = result["policy_pack"]
    leadership = result["leadership_scorecard"]
    leadership_review = result["leadership_review_pack"]
    kb_audit = result["knowledge_quality_audit"]
    kb_plan = result["kb_refresh_plan"]
    smoke = result["smoke_matrix"]
    checklist = result["launch_checklist"]
    portfolio_evidence = result["portfolio_evidence_index"]
    interview_pack = result["portfolio_interview_pack"]
    release_gate = result["release_gate"]
    release_publish_pack = result["release_publish_pack"]
    reviewer_quickstart = result["reviewer_quickstart"]
    reviewer_walkthrough_pack = result["reviewer_walkthrough_pack"]
    ci_doctor = result["ci_doctor"]
    audit_pack = result["audit_pack"]
    artifact_inventory = result["artifact_inventory"]
    readme_checklist_pack = result["readme_checklist_pack"]
    dashboard_smoke = result["dashboard_smoke"]
    ui_verification_pack = result["ui_verification_pack"]
    final_audit = result["final_audit"]
    final_handoff_pack = result["final_handoff_pack"]
    on_call_handoff = result["on_call_handoff"]
    customer_comms_pack = result["customer_comms_pack"]
    git_readiness = result["git_readiness"]
    git_push_plan = result["git_push_plan"]
    api_contract_audit = result["api_contract_audit"]
    api_reviewer_collection = result["api_reviewer_collection"]
    runtime_demo_readiness = result["runtime_demo_readiness"]
    runtime_demo_pack = result["runtime_demo_pack"]
    scenario_catalog = result["scenario_catalog"]
    scenario_eval_pack = result["scenario_eval_pack"]
    postmortem_rca = result["postmortem_rca"]
    rca_pack = result["rca_pack"]
    policy_simulation = policy["pack"]["primary_simulation"]

    print("Mode:", result["mode"])
    print("Scenario:", scenario["scenario_id"])
    print("Evidence pack:", result["markdown_path"])
    print("Evidence JSON:", result["json_path"])
    print(
        "Operator readiness:",
        readiness["readiness_score"],
        readiness["readiness_status"],
    )
    print("Operator pack:", readiness["markdown_path"])
    print("Operator JSON:", readiness["json_path"])
    print("Policy decision:", policy_simulation["policy_decision"])
    print("Policy approval:", policy_simulation["required_approval_type"])
    print("Policy pack:", policy["markdown_path"])
    print("Policy JSON:", policy["json_path"])
    print(
        "Leadership readiness:",
        leadership["overall_score"],
        leadership["readiness_status"],
    )
    print("Leadership review pack:", leadership_review["markdown_path"])
    print("Leadership review JSON:", leadership_review["json_path"])
    print(
        "KB readiness:",
        kb_audit["kb_coverage_score"],
        kb_audit["readiness_status"],
    )
    print("KB refresh plan:", kb_plan["markdown_path"])
    print("KB refresh JSON:", kb_plan["json_path"])
    print(
        "Launch readiness:",
        smoke["readiness_summary"]["status"],
        f"checks={smoke['readiness_summary']['total_checks']}",
    )
    print("Launch checklist:", checklist["markdown_path"])
    print("Launch checklist JSON:", checklist["json_path"])
    print(
        "Portfolio evidence score:",
        portfolio_evidence["evidence_score"],
        f"count={portfolio_evidence['evidence_count']}",
    )
    print("Interview Pack:", interview_pack["markdown_path"])
    print("Interview Pack JSON:", interview_pack["json_path"])
    print("Release gate:", release_gate["status"], f"score={release_gate['score']}")
    print("Release blockers:", len(release_gate["blockers"]))
    print("Release warnings:", len(release_gate["warnings"]))
    print("Publish Pack:", release_publish_pack["markdown_path"])
    print("Publish Pack JSON:", release_publish_pack["json_path"])
    print(
        "Reviewer quickstart:",
        reviewer_quickstart["status"],
        f"proofs={reviewer_quickstart['artifact_proof_count']}",
    )
    print("Walkthrough Pack:", reviewer_walkthrough_pack["markdown_path"])
    print("Walkthrough Pack JSON:", reviewer_walkthrough_pack["json_path"])
    print("CI Doctor:", ci_doctor["status"], f"score={ci_doctor['score']}")
    print("Secret scan findings:", ci_doctor["secret_scan_summary"]["finding_count"])
    print("Audit Pack:", audit_pack["markdown_path"])
    print("Audit Pack JSON:", audit_pack["json_path"])
    print(
        "Artifact inventory:",
        artifact_inventory["artifact_count"],
        f"generated={artifact_inventory['generated_artifact_directory_count']}",
    )
    print("README Checklist:", readme_checklist_pack["markdown_path"])
    print("README Checklist JSON:", readme_checklist_pack["json_path"])
    print(
        "Dashboard smoke:",
        dashboard_smoke["status"],
        f"checks={dashboard_smoke['summary']['total_checks']}",
        f"failed={dashboard_smoke['summary']['failed_checks']}",
    )
    print("UI Verification Pack:", ui_verification_pack["markdown_path"])
    print("UI Verification JSON:", ui_verification_pack["json_path"])
    print("Final audit:", final_audit["status"], f"score={final_audit['score']}")
    print("Final audit blockers:", len(final_audit["blockers"]))
    print("Final Handoff Pack:", final_handoff_pack["markdown_path"])
    print("Final Handoff JSON:", final_handoff_pack["json_path"])
    print(
        "On-Call Handoff:",
        on_call_handoff["status"],
        f"readiness={on_call_handoff['customer_communication_readiness']['status']}",
    )
    print("Customer Communications Pack:", customer_comms_pack["markdown_path"])
    print("Customer Communications JSON:", customer_comms_pack["json_path"])
    print("Git readiness:", git_readiness["status"], f"branch={git_readiness['current_branch'] or 'unknown'}")
    print("Git changed files:", git_readiness["summary"]["changed_count"])
    print("Push Plan:", git_push_plan["markdown_path"])
    print("Push Plan JSON:", git_push_plan["json_path"])
    print(
        "API Contract Audit:",
        api_contract_audit["status"],
        f"routes={api_contract_audit['summary']['openapi_route_count']}",
        f"protected={api_contract_audit['summary']['auth_protected_endpoint_count']}",
    )
    print("Reviewer Collection:", api_reviewer_collection["markdown_path"])
    print("Reviewer Collection JSON:", api_reviewer_collection["json_path"])
    print(
        "Runtime Demo Readiness:",
        runtime_demo_readiness["status"],
        f"checks={runtime_demo_readiness['summary']['total_checks']}",
        f"warnings={runtime_demo_readiness['summary']['warning_checks']}",
        f"failed={runtime_demo_readiness['summary']['failed_checks']}",
    )
    print("Runtime Demo Pack:", runtime_demo_pack["markdown_path"])
    print("Runtime Demo JSON:", runtime_demo_pack["json_path"])
    print(
        "Scenario catalog:",
        scenario_catalog["scenario_count"],
        f"domains={scenario_catalog['coverage_summary']['domain_count']}",
    )
    print(
        "Scenario coverage:",
        scenario_eval_pack["status"],
        f"passed={scenario_eval_pack['eval_summary']['passed_scenario_count']}",
        f"failed={scenario_eval_pack['eval_summary']['failed_scenario_count']}",
    )
    print("Scenario Eval Pack:", scenario_eval_pack["markdown_path"])
    print("Scenario Eval JSON:", scenario_eval_pack["json_path"])
    print(
        "Postmortem RCA:",
        postmortem_rca["readiness_summary"]["status"],
        f"root_cause={postmortem_rca['root_cause_category']['category']}",
        f"actions={len(postmortem_rca['corrective_actions'])}",
    )
    print("RCA Pack:", rca_pack["markdown_path"])
    print("RCA Pack JSON:", rca_pack["json_path"])
    print("Incident impact status:", metrics["incident_impact_status"])
    print("Incident narrative:", metrics["incident_narrative_path"])
    print("Ticket:", metrics["ticket_id"])
    print("Run:", metrics["run_id"], metrics["run_status"], metrics["final_action"])
    print("Trace:", metrics["trace_id"], f"events={metrics['trace_event_count']}")
    print("Approval:", metrics["approval_id"], metrics["approval_status"])
    print("Outbox dispatches:", metrics["outbox_dispatch_count"])
    print("Failure drill attempts:", metrics["failure_drill_failed_attempts"])
    print("SLA simulation tickets:", metrics["sla_simulation_ticket_count"])
    print("SLO:", metrics["slo_overall_status"])
    print("Replay risk:", metrics["replay_risk_score"])
    print("Replay action:", metrics["replay_recommended_action"])
    print("Replay report:", pack["artifact_paths"]["replay_report_markdown"])
    print("Artifacts:")
    for name, path in sorted(pack["artifact_paths"].items()):
        print(f"- {name}: {path}")
    print("Interview talking points:")
    for point in pack["interview_talking_points"]:
        print(f"- {point}")


if __name__ == "__main__":
    main()
