import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_incremental_builds.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("compare_incremental_builds_for_tests", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
compare_builds = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(compare_builds)


def _snapshot(variant, abi3, public_seconds):
    return {
        "date": "2026-09-25",
        "environment": {
            "commit_sha": "abc123",
            "working_tree_dirty": False,
            "native_source_fingerprint_without_abi_feature": "same-rust-source",
            "package_version": "0.2.2",
            "installed_distribution_version": "0.2.2",
            "package_source": "installed distribution",
            "python_version": "3.14.0",
            "operating_system": "macOS",
            "platform": "macOS-test",
            "architecture": "arm64",
            "processor": "Test CPU",
            "benchmark_package_versions": {"msgspec": "0.21.1"},
            "rustc_version": "rustc test",
            "cargo_version": "cargo test",
            "maturin_version": "maturin test",
            "native_extension": {
                "distribution_version": "0.2.2",
                "build_variant": variant,
                "abi3_binary": abi3,
                "module_filename": f"native.{variant}.so",
                "binary_sha256": f"{variant}-hash",
            },
        },
        "methodology": {
            "clock": "time.perf_counter",
            "samples_per_case": 1,
            "chunking": "fixed-width byte chunks",
        },
        "sizes": [8192],
        "chunk_sizes_bytes": [64],
        "cases": [
            {
                "shape": "flat_string_object",
                "requested_size": 8192,
                "payload_size_bytes": 8200,
                "chunk_size_bytes": 64,
                "chunk_count": 129,
                "sample_count": 1,
                "results": [
                    {
                        "name": "streaming_json_parser_native_public",
                        "display_name": "StreamingJsonParser",
                        "valid": True,
                        "median_seconds_per_stream": public_seconds,
                        "sample_seconds_per_stream": [public_seconds],
                    },
                    {
                        "name": "native_incremental_direct_result",
                        "display_name": "Direct result API",
                        "valid": True,
                        "median_seconds_per_stream": public_seconds * 0.9,
                        "sample_seconds_per_stream": [public_seconds * 0.9],
                    },
                    {
                        "name": "streaming_json_parser_python_fallback",
                        "display_name": "Python fallback",
                        "valid": True,
                        "median_seconds_per_stream": 0.01,
                        "sample_seconds_per_stream": [0.01],
                    },
                ],
            }
        ],
    }


def test_build_comparison_requires_same_source_and_machine():
    abi3 = _snapshot("abi3", True, 0.0011)
    cpython = _snapshot("cpython-specific", False, 0.001)
    cpython["environment"]["processor"] = "Different CPU"

    with pytest.raises(ValueError, match="environment differs: processor"):
        compare_builds.build_comparison(abi3, cpython)


def test_build_comparison_reports_abi3_slowdown_without_mixing_fallback():
    comparison = compare_builds.build_comparison(
        _snapshot("abi3", True, 0.0011),
        _snapshot("cpython-specific", False, 0.001),
    )

    public = comparison["cases"][0]["results"][0]
    assert public["abi3_slowdown_percent"] == pytest.approx(10.0)
    assert "streaming_json_parser_python_fallback" not in {
        result["name"]
        for case in comparison["cases"]
        for result in case["results"]
    }
    assert "PyO3 `abi3-py310` enabled" in compare_builds.render_markdown(comparison)
    assert comparison["python_fallback_timing_control"]["max_per_workload_difference_percent"] == 0


def test_build_comparison_rejects_timing_environment_drift():
    abi3 = _snapshot("abi3", True, 0.0011)
    cpython = _snapshot("cpython-specific", False, 0.001)
    cpython["cases"][0]["results"][2]["median_seconds_per_stream"] = 0.02

    with pytest.raises(ValueError, match="Python fallback timing control differs"):
        compare_builds.build_comparison(abi3, cpython)


def test_build_comparison_artifacts_render_deterministically_and_detect_staleness(tmp_path):
    comparison = compare_builds.build_comparison(
        _snapshot("abi3", True, 0.0011),
        _snapshot("cpython-specific", False, 0.001),
    )
    first = compare_builds.artifact_contents(comparison, tmp_path)
    second = compare_builds.artifact_contents(comparison, tmp_path)

    assert first == second
    for path, content in first.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    assert compare_builds.verify_artifacts(tmp_path) == []
    json.loads((tmp_path / "abi3-incremental-investigation.json").read_text())
    (tmp_path / "abi3-incremental-investigation.md").write_text("stale\n")
    assert any(
        "abi3-incremental-investigation.md" in issue
        for issue in compare_builds.verify_artifacts(tmp_path)
    )
