from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.ui_verification import UIVerificationService  # noqa: E402


def main() -> int:
    service = UIVerificationService(Path("data/ui_verification"))
    smoke = service.dashboard_smoke_sync()
    summary = smoke["summary"]
    status = smoke["status"].upper()
    print(f"Dashboard Smoke: {status}")
    print(
        "Checks:",
        f"total={summary['total_checks']}",
        f"passed={summary['passed_checks']}",
        f"failed={summary['failed_checks']}",
    )
    print(f"Dashboard source: {smoke['dashboard_source']}")
    print("Checked views:")
    for view in smoke["expected_views"]:
        marker = "PASS" if view["present"] else "FAIL"
        position = f"#{view['position']}" if view["position"] else "missing"
        print(f"- {marker} {view['label']} ({position})")
    print("Checked endpoints:")
    for endpoint in smoke["endpoint_references"]:
        dashboard_marker = "dashboard=PASS" if endpoint["dashboard_reference_present"] else "dashboard=FAIL"
        route_marker = "route=PASS" if endpoint["route_present"] else "route=FAIL"
        print(f"- {endpoint['endpoint']} ({dashboard_marker}, {route_marker})")
    if smoke["status"] != "pass":
        print("Failed checks:")
        for check in smoke["checks"]:
            if check["status"] == "fail":
                print(f"- {check['name']}: {check['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
