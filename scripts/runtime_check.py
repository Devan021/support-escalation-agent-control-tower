from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.runtime_demo import build_runtime_readiness_for_cli, print_runtime_readiness  # noqa: E402


def main() -> int:
    readiness = build_runtime_readiness_for_cli()
    return print_runtime_readiness(readiness)


if __name__ == "__main__":
    raise SystemExit(main())
