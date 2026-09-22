import os
import subprocess
import sys
from pathlib import Path


def test_package_imports_without_repository_root_on_path(tmp_path):
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from streaming_json_parser import ParseStatus, StreamingJsonParser; assert StreamingJsonParser().feed('{}').status is ParseStatus.COMPLETE",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
