from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_pyright(project_file: str) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        ["pyright", "--outputjson", "--project", project_file],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Pyright did not return JSON for {project_file}:\n{completed.stdout}\n{completed.stderr}"
        ) from exc
    if not isinstance(report, dict):
        raise RuntimeError(f"Unexpected Pyright report for {project_file}: {report!r}")
    return completed.returncode, report


def main() -> int:
    valid_status, valid_report = run_pyright("pyrightconfig.json")
    valid_summary = valid_report.get("summary", {})
    if (
        valid_status != 0
        or not isinstance(valid_summary, dict)
        or valid_summary.get("filesAnalyzed", 0) < 1
        or valid_summary.get("errorCount") != 0
    ):
        print(json.dumps(valid_report, indent=2), file=sys.stderr)
        return 1

    invalid_status, invalid_report = run_pyright("pyrightconfig.invalid.json")
    diagnostics = invalid_report.get("generalDiagnostics", [])
    expected_diagnostic = any(
        isinstance(item, dict) and item.get("rule") == "reportArgumentType"
        for item in diagnostics
    ) if isinstance(diagnostics, list) else False
    if invalid_status == 0 or not expected_diagnostic:
        print(json.dumps(invalid_report, indent=2), file=sys.stderr)
        return 1

    print("Pyright accepted the downstream fixture and rejected the invalid input fixture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
