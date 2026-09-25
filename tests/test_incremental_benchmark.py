import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_incremental.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("incremental_benchmark_for_tests", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
incremental_benchmark = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(incremental_benchmark)


def test_incremental_benchmark_clock_is_elapsed_and_never_records_zero(monkeypatch):
    monkeypatch.setattr(incremental_benchmark.time, "process_time", lambda: 0.0)

    median, samples, repetitions = incremental_benchmark._measure(lambda: None, 1, samples=2)

    assert median > 0
    assert all(sample > 0 for sample in samples)
    assert len(repetitions) == 2


def test_incremental_benchmark_repeats_when_clock_resolution_returns_zero(monkeypatch):
    timestamps = iter((0.0, 0.0, 1.0, 2.0))
    monkeypatch.setattr(incremental_benchmark.time, "perf_counter", lambda: next(timestamps))
    monkeypatch.setattr(incremental_benchmark, "_TARGET_SECONDS_PER_SAMPLE", 0.0)

    median, samples, repetitions = incremental_benchmark._measure(
        lambda: None, incremental_benchmark._TARGET_BYTES_PER_SAMPLE, samples=1
    )

    assert median > 0
    assert samples == [0.5]
    assert repetitions == [2]


def test_incremental_benchmark_extends_short_batches_to_target_duration(monkeypatch):
    timestamps = iter((0.0, 0.001, 0.002, 0.013))
    monkeypatch.setattr(incremental_benchmark.time, "perf_counter", lambda: next(timestamps))
    monkeypatch.setattr(incremental_benchmark, "_TARGET_SECONDS_PER_SAMPLE", 0.01)

    median, samples, repetitions = incremental_benchmark._measure(
        lambda: None, incremental_benchmark._TARGET_BYTES_PER_SAMPLE, samples=1
    )

    assert median == pytest.approx(0.0011)
    assert samples == pytest.approx([0.0011])
    assert repetitions == [10]


@pytest.mark.skipif(
    incremental_benchmark._NATIVE is None,
    reason="native extension is optional outside release benchmark generation",
)
def test_incremental_benchmark_covers_shapes_chunk_sizes_and_only_strict_rows():
    snapshot = incremental_benchmark.collect_snapshot(
        sizes=(64,),
        chunk_sizes=(1, 8, 64, 256),
        samples=1,
    )

    assert snapshot["methodology"]["clock"] == "time.perf_counter"
    assert snapshot["semantics_family"] == "strict_incremental"
    assert {case["shape"] for case in snapshot["cases"]} == {
        "flat_string_object",
        "number_array",
        "string_array",
        "nested_records",
        "unicode_object",
        "escape_heavy_object",
        "root_number",
        "root_literal",
        "root_string",
    }
    assert {case["chunk_size_bytes"] for case in snapshot["cases"]} == {1, 8, 64}
    assert all(case["chunk_count"] >= 2 for case in snapshot["cases"])
    assert all(
        result["semantics_family"] == "strict_incremental"
        for case in snapshot["cases"]
        for result in case["results"]
    )
    assert all(
        result["valid"]
        for case in snapshot["cases"]
        for result in case["results"]
    )
    assert {
        result["name"]
        for case in snapshot["cases"]
        for result in case["results"]
    } == {
        "streaming_json_parser_native_public",
        "native_incremental_direct_result",
        "streaming_json_parser_python_fallback",
    }


def test_incremental_artifact_rendering_is_deterministic_and_svg_is_valid(tmp_path):
    snapshot = {
        "date": "2026-09-25",
        "benchmark": "strict incremental JSON parser by byte chunk size",
        "semantics_family": "strict_incremental",
        "environment": {
            "package_version": "0.2.2",
            "package_source": "installed distribution",
            "installed_distribution_version": "0.2.2",
            "package_module_version": "0.2.2",
            "commit_sha": "abc123",
            "working_tree_dirty": False,
            "native_extension": {
                "distribution_version": "0.2.2",
                "build_variant": "abi3",
                "abi3_binary": True,
                "module_filename": "streaming_json_parser_native.abi3.so",
                "binary_sha256": "deadbeef",
            },
            "python_version": "3.14.0",
            "platform": "test platform",
            "processor": "test processor",
            "benchmark_package_versions": {"msgspec": "0.21.1"},
            "rustc_version": "rustc test",
            "cargo_version": "cargo test",
            "maturin_version": "maturin test",
            "native_source_fingerprint_without_abi_feature": "native-source-hash",
        },
        "methodology": {
            "command": "benchmark command",
            "clock": "time.perf_counter",
            "aggregation": "median per-stream elapsed time across 1 measured batches",
            "timing_scope": "test timing scope",
            "chunking": "test chunking",
            "comparison": "test comparison",
            "semantic_scope": "strict incremental only; cumulative-prefix reparsing is excluded",
        },
        "sizes": [64],
        "chunk_sizes_bytes": [1],
        "implementations": [
            {"name": "streaming_json_parser_native_public", "display_name": "StreamingJsonParser (native ABI3)"},
            {"name": "native_incremental_direct_result", "display_name": "Direct result API"},
            {"name": "streaming_json_parser_python_fallback", "display_name": "StreamingJsonParser (Python fallback)"},
        ],
        "summary": {
            "paired_case_count": 1,
            "native_public_median_speedup_vs_python": 1.0,
            "native_public_faster_case_count": 1,
            "native_public_not_faster_case_count": 0,
        },
        "numeric_overflow_behavior": {
            "streaming_json_parser_native_public": {"outcome": "rejected", "error_type": "ValueError"},
            "native_incremental_direct_result": {"outcome": "rejected", "error_type": "ValueError"},
            "streaming_json_parser_python_fallback": {"outcome": "rejected", "error_type": "ValueError"},
        },
        "cases": [
            {
                "shape": "flat_string_object",
                "requested_size": 64,
                "payload_size_bytes": 70,
                "chunk_size_bytes": 1,
                "chunk_count": 70,
                "results": [
                    {"name": "streaming_json_parser_native_public", "valid": True, "median_seconds_per_stream": 0.001},
                    {"name": "native_incremental_direct_result", "valid": True, "median_seconds_per_stream": 0.0009},
                    {"name": "streaming_json_parser_python_fallback", "valid": True, "median_seconds_per_stream": 0.0011},
                ],
            }
        ],
    }

    first = incremental_benchmark.artifact_contents(snapshot, tmp_path)
    second = incremental_benchmark.artifact_contents(snapshot, tmp_path)

    assert first == second
    svg_path = tmp_path / "assets" / "benchmarks" / "incremental-chunk-size.svg"
    ET.fromstring(first[svg_path])
    written = incremental_benchmark.write_artifacts(snapshot, tmp_path)
    assert incremental_benchmark.verify_artifacts(tmp_path) == []
    assert json.loads((tmp_path / "incremental-benchmark.json").read_text()) == snapshot
    (tmp_path / "incremental-benchmark.md").write_text("stale\n")
    assert any("incremental-benchmark.md" in issue for issue in incremental_benchmark.verify_artifacts(tmp_path))
    assert len(written) == 3
