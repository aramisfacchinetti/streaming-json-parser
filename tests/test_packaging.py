import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest


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


def test_built_distributions_include_pep561_type_information():
    dist_dir = os.environ.get("STREAMING_JSON_PARSER_DIST_DIR")
    if dist_dir is None:
        pytest.skip("set STREAMING_JSON_PARSER_DIST_DIR after building distributions")

    distribution_dir = Path(dist_dir)
    wheels = sorted(distribution_dir.glob("streaming_json_parser-*.whl"))
    sdists = sorted(distribution_dir.glob("streaming_json_parser-*.tar.gz"))
    assert len(wheels) == 1, f"expected one core wheel in {distribution_dir}, found {wheels}"
    assert len(sdists) == 1, f"expected one core sdist in {distribution_dir}, found {sdists}"

    expected_files = {
        "streaming_json_parser/py.typed",
        "streaming_json_parser/__init__.pyi",
        "streaming_json_parser/high_performance_parser.pyi",
    }
    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel_files = set(wheel.namelist())
        assert expected_files <= wheel_files
        assert not any("pyrightconfig" in name for name in wheel_files)
        assert not any(name.startswith("typing_tests/") for name in wheel_files)

    with tarfile.open(sdists[0], "r:gz") as sdist:
        sdist_files = {
            member.name
            for member in sdist.getmembers()
            if member.isfile()
        }
        packaged_files = {
            "/".join(Path(member.name).parts[-2:])
            for member in sdist.getmembers()
            if member.isfile()
        }
    assert expected_files <= packaged_files
    assert not any("pyrightconfig" in name for name in sdist_files)
    assert not any("/typing_tests/" in name for name in sdist_files)
