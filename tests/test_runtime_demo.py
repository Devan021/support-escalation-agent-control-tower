from pathlib import Path


def test_runtime_demo_readiness_returns_commands_and_safe_checks(client):
    response = client.get("/runtime/demo-readiness")
    assert response.status_code == 200, response.text
    readiness = response.json()

    assert readiness["title"] == "Runtime Demo Readiness"
    assert readiness["mode"] == "local-source-readiness-no-server-required"
    assert readiness["local_mock_only"] is True
    assert readiness["status"] in {"ready", "ready_with_warnings", "blocked"}
    assert readiness["run_commands"]["runtime_check"] == r".\.venv\Scripts\python.exe scripts\runtime_check.py"
    assert readiness["run_commands"]["start_script"] == r".\scripts\start_demo.ps1"
    assert any(command.endswith("--port 8000") for command in readiness["run_commands"]["start"])
    assert any("streamlit_app.py" in command for command in readiness["run_commands"]["start"])
    assert {item["port"] for item in readiness["expected_ports"]} == {8000, 8501}
    assert {item["name"] for item in readiness["env_requirements"]} >= {
        "CONTROL_TOWER_API_BASE_URL",
        "CONTROL_TOWER_API_KEY",
        "CONTROL_TOWER_STATE_FILE",
    }
    assert {item["name"] for item in readiness["dependency_checks"]} >= {
        "fastapi",
        "uvicorn",
        "streamlit",
        "requests",
        "pytest",
        "ruff",
    }
    assert readiness["process_port_checks"]["safe_read_only"] is True
    assert readiness["process_port_checks"]["auto_kill_processes"] is False
    assert "http://127.0.0.1:8000/runtime/demo-readiness" in readiness["health_urls"]
    assert any("never stops processes" in item for item in readiness["known_limitations"])


def test_runtime_demo_pack_exports_markdown_and_json(client, auth_headers):
    response = client.post("/runtime/demo-pack", headers=auth_headers)
    assert response.status_code == 200, response.text
    exported = response.json()
    pack = exported["pack"]
    markdown = exported["markdown"]

    assert exported["status"] in {"ready", "ready_with_warnings", "blocked"}
    assert "runtime_packs" in exported["markdown_path"]
    assert Path(exported["markdown_path"]).exists()
    assert Path(exported["json_path"]).exists()
    assert pack["title"] == "Runtime Demo Server Pack"
    assert pack["readiness"]["title"] == "Runtime Demo Readiness"
    assert pack["start_commands"]
    assert pack["stop_commands"]
    assert pack["health_checks"]
    assert pack["demo_flow_order"][0].startswith("Create and activate")
    assert pack["screenshot_checklist"]
    assert pack["recruiter_explanation"]
    assert pack["engineer_explanation"]
    assert "runtime_pack_markdown" in pack["artifact_paths"]
    assert "# Runtime Demo Server Pack" in markdown
    assert "## Read-Only Port Checks" in markdown
    saved = Path(exported["json_path"]).read_text(encoding="utf-8")
    assert "runtime/demo-readiness" in saved
    assert "runtime_pack_json" in saved


def test_runtime_demo_is_wired_into_launch_inventory_and_dashboard_smoke(client, auth_headers):
    smoke = client.get("/ops/smoke-matrix", headers=auth_headers).json()
    smoke_endpoints = {row["endpoint"]: row for row in smoke["matrix"]}
    assert "GET /runtime/demo-readiness" in smoke_endpoints
    assert "POST /runtime/demo-pack" in smoke_endpoints
    assert smoke_endpoints["POST /runtime/demo-pack"]["artifact_expectation"]["path"] == "data/runtime_packs"

    inventory = client.get("/artifacts/inventory", headers=auth_headers).json()
    runtime_artifact = next(item for item in inventory["artifacts"] if item["directory"] == "data/runtime_packs")
    assert runtime_artifact["producer_endpoint"] == "POST /runtime/demo-pack"
    assert "Runtime Demo Server Pack" in runtime_artifact["name"]

    dashboard_smoke = client.get("/ui/dashboard-smoke", headers=auth_headers).json()
    labels = {item["label"] for item in dashboard_smoke["expected_views"]}
    assert "Runtime Demo" in labels
    endpoints = {item["endpoint"]: item for item in dashboard_smoke["endpoint_references"]}
    assert endpoints["GET /runtime/demo-readiness"]["route_present"] is True
    assert endpoints["POST /runtime/demo-pack"]["dashboard_reference_present"] is True
    artifact_tabs = {
        item["tab_label"]: item
        for item in dashboard_smoke["generated_artifact_tabs"]
    }
    assert artifact_tabs["Runtime Demo"]["artifact_directory"] == "data/runtime_packs"
