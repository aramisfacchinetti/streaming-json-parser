import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_parser.py"
MODULE_SPEC = importlib.util.spec_from_file_location("benchmark_parser_for_tests", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
benchmark_parser = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(benchmark_parser)


def test_collect_current_snapshot_uses_expected_sections(monkeypatch):
    complete = {"section": "complete_1mb_object", "iterations": 20, "results": []}
    selective = {"section": "complete_selective_extraction", "iterations": 200, "results": []}
    ndjson = {"section": "ndjson_selective_extraction", "iterations": 5, "results": []}

    monkeypatch.setattr(benchmark_parser, "collect_complete_baseline_snapshot", lambda: complete)
    monkeypatch.setattr(benchmark_parser, "collect_selective_access_snapshot", lambda: selective)
    monkeypatch.setattr(benchmark_parser, "collect_ndjson_selective_access_snapshot", lambda: ndjson)
    monkeypatch.setattr(benchmark_parser.time, "strftime", lambda _fmt: "2026-06-13")
    monkeypatch.setattr(benchmark_parser, "_collect_environment_metadata", lambda: {"package_version": "0.2.0"})
    monkeypatch.setattr(benchmark_parser, "_benchmark_methodology", lambda: {"samples_per_case": 7})

    snapshot = benchmark_parser.collect_current_snapshot()

    assert snapshot == {
        "date": "2026-06-13",
        "environment": {"package_version": "0.2.0"},
        "methodology": {"samples_per_case": 7},
        "sections": [complete, selective, ndjson],
    }


def test_environment_distinguishes_source_from_installed_distribution(monkeypatch):
    monkeypatch.setattr(benchmark_parser, "_PROJECT_VERSION", "0.2.0")
    monkeypatch.setattr(
        benchmark_parser,
        "_distribution_version",
        lambda name: "0.1.0" if name in {"streaming-json-parser", "streaming-json-parser-native"} else None,
    )
    monkeypatch.setattr(benchmark_parser, "_git_provenance", lambda: {"commit_sha": "abc", "working_tree_dirty": False})
    monkeypatch.setattr(benchmark_parser, "_cpu_identifier", lambda: "test processor")
    monkeypatch.setattr(benchmark_parser, "_backend_native", object())

    environment = benchmark_parser._collect_environment_metadata()

    assert environment["package_version"] == "0.2.0"
    assert environment["installed_distribution_version"] == "0.1.0"
    assert environment["native_extension"] == {
        "installed": True,
        "importable": True,
        "version": "0.1.0",
    }


def test_complete_selective_snapshot_records_two_common_paths():
    snapshot = benchmark_parser.collect_selective_access_snapshot(iterations=1)

    assert snapshot["selected_paths"] == ["meta.name", "tail.count"]
    assert snapshot["record_count"] == 5_000
    assert snapshot["payload_size_bytes"] > 0
    assert snapshot["samples_per_case"] == benchmark_parser._SAMPLE_COUNT
    assert snapshot["warmup_invocations_per_case"] == benchmark_parser._WARMUP_INVOCATIONS


def test_partial_benchmark_prefixes_include_the_final_payload():
    partial_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_partial_parser.py"
    partial_spec = importlib.util.spec_from_file_location("benchmark_partial_for_tests", partial_path)
    assert partial_spec is not None and partial_spec.loader is not None
    partial = importlib.util.module_from_spec(partial_spec)
    partial_spec.loader.exec_module(partial)

    assert partial._prefixes("abcdefg", 3) == ["abc", "abcdef", "abcdefg"]


def test_strategy_matrix_covers_shapes_and_reports_measurement_repetitions():
    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location("strategy_matrix_for_tests", matrix_path)
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)

    matrix = matrix_module.collect_matrix((64,), iterations=1)

    assert {case["shape"] for case in matrix["cases"]} == {
        "flat_string_object",
        "number_array",
        "string_array",
        "nested_records",
        "unicode_object",
        "escape_heavy_object",
        "wide_object",
        "nested_arrays",
        "root_number",
        "root_literal",
        "root_string",
    }
    assert {case["input_kind"] for case in matrix["cases"]} == {
        "bytes",
        "str",
        "bytearray",
    }
    assert all(
        result["measurement_iterations"] >= 1
        for case in matrix["cases"]
        for result in case["results"]
        if result["valid"]
    )
    assert all(
        case["facade_tuned_ratio"] > 0
        for case in matrix["cases"]
    )


def test_strategy_matrix_compatibility_rejects_permissive_decoders():
    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location(
        "strategy_matrix_compatibility_for_tests", matrix_path
    )
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)

    payload = b'{"value":1}'
    assert not matrix_module._is_compatible(
        json.loads,
        payload,
        {"value": 1},
    )


def test_strategy_matrix_measures_identical_callable_once():
    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location(
        "strategy_matrix_callable_identity", matrix_path
    )
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)

    function = lambda payload: payload
    measurements = matrix_module._measure_functions(
        [("first", function), ("same", function)],
        b"{}",
        1,
    )

    assert measurements["first"] == measurements["same"]


def test_strategy_matrix_groups_repeated_builtin_bound_methods():
    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location(
        "strategy_matrix_builtin_callable_identity", matrix_path
    )
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)

    import msgspec

    measurements = matrix_module._measure_functions(
        [
            ("first", msgspec.json.Decoder().decode),
            ("same", msgspec.json.Decoder().decode),
        ],
        b"{}",
        1,
    )

    assert measurements["first"] == measurements["same"]


def test_ndjson_matrix_measures_identical_callable_once():
    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_ndjson_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location(
        "ndjson_matrix_callable_identity", matrix_path
    )
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)

    function = lambda payload: payload
    measurements = matrix_module._measure_functions(
        [("first", function), ("same", function)],
        b"{}\n",
        1,
    )

    assert measurements["first"] == measurements["same"]


def test_ndjson_matrix_groups_repeated_builtin_bound_methods():
    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_ndjson_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location(
        "ndjson_matrix_builtin_callable_identity", matrix_path
    )
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)

    import msgspec

    measurements = matrix_module._measure_functions(
        [
            ("first", msgspec.json.Decoder().decode_lines),
            ("same", msgspec.json.Decoder().decode_lines),
        ],
        b"{}\n",
        1,
    )

    assert measurements["first"] == measurements["same"]


def test_partial_strategy_matrix_covers_workloads_and_semantic_families():
    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_partial_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location("partial_strategy_matrix_for_tests", matrix_path)
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)

    matrix = matrix_module.collect_matrix((64,), (2,), repeats=1)

    assert {case["shape"] for case in matrix["cases"]} == {
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
    assert all(case["chunk_count"] >= 1 for case in matrix["cases"])
    assert {case["input_kind"] for case in matrix["cases"]} == {
        "str",
        "bytes",
        "bytearray",
    }
    families = {
        result["family"]
        for case in matrix["cases"]
        for result in case["results"]
        if result["valid"]
    }
    expected_families = {
        "strict_incremental",
        "structural_finisher",
    }
    if any(
        getattr(matrix_module._partial, name) is not None
        for name in ("PartialJsonParser", "partial_json_loads", "repair_json", "untruncate_json")
    ):
        expected_families.add("permissive_recovery")
    if (
        matrix_module._partial.jsonriver is not None
        or matrix_module._partial._ijson_yajl2_c is not None
    ):
        expected_families.add("event_driven_partial")
    if matrix_module._partial._PYDANTIC_CORE_TRAILING_STRINGS:
        expected_families.add("structural_trailing_finisher")
    assert families == expected_families
    assert all(
        case["structural_trailing_winner"] is None
        or case["structural_trailing_winner"]
        in {
            "facade_structural_trailing_finisher",
            "facade_structural_trailing_function_finisher",
            "facade_structural_trailing_one_shot_finisher",
            "pydantic_core_trailing_strings_finisher",
            "jiter_trailing_strings_finisher",
        }
        for case in matrix["cases"]
    )
    if matrix_module._partial.jsonriver is not None:
        assert all(case["jsonriver_strict_compatible"] for case in matrix["cases"])
        assert all(
            result["valid"]
            for case in matrix["cases"]
            for result in case["results"]
            if result["name"] == "jsonriver_event_driven"
        )
    if matrix_module._partial._ijson_yajl2_c is not None:
        assert all(case["ijson_strict_compatible"] for case in matrix["cases"])
        assert all(
            result["valid"]
            for case in matrix["cases"]
            for result in case["results"]
            if result["name"] == "ijson_yajl2_c_event_driven"
        )
        assert all(
            result["family"] == "event_driven_partial"
            for case in matrix["cases"]
            for result in case["results"]
            if result["name"] == "ijson_yajl2_c_event_driven"
        )
        assert all(
            result["family"] == "event_driven_partial"
            for case in matrix["cases"]
            for result in case["results"]
            if result["name"] == "jsonriver_event_driven"
        )
    if matrix_module._partial.streaming_json_parser_native is not None:
        assert all(
            any(
                result["name"] == "native_incremental_direct" and result["valid"]
                for result in case["results"]
            )
            for case in matrix["cases"]
        )
        assert all(
            any(
                result["name"] == "native_incremental_public_result" and result["valid"]
                for result in case["results"]
            )
            for case in matrix["cases"]
        )
        assert all(
            case["strict_incremental_winner"]
            in {
                "native_incremental_direct",
                "native_incremental_public_result",
                "facade_incremental",
                "facade_consume_poll",
            }
            for case in matrix["cases"]
        )
        assert all(
            case["strict_incremental_public_winner"]
            in {
                "native_incremental_public_result",
                "facade_incremental",
                "facade_consume_poll",
            }
            for case in matrix["cases"]
        )
        assert all(
            case["strict_incremental_public_winner"]
            != "native_incremental_direct"
            for case in matrix["cases"]
        )
    elif matrix_module._partial.jsonriver is not None:
        assert all(
            case["strict_incremental_winner"]
            in {"facade_incremental", "facade_consume_poll"}
            for case in matrix["cases"]
        )
        assert all(
            case["strict_incremental_public_winner"]
            in {"facade_incremental", "facade_consume_poll"}
            for case in matrix["cases"]
        )
    assert any(
        result["name"] == "facade_structural_function_finisher"
        for case in matrix["cases"]
        for result in case["results"]
    )
    assert any(
        result["name"] == "facade_structural_one_shot_finisher"
        for case in matrix["cases"]
        for result in case["results"]
    )
    assert all(
        result["valid"]
        for case in matrix["cases"]
        for result in case["results"]
        if (
            result["name"] == "facade_structural_one_shot_finisher"
            and case["shape"] != "root_literal"
        )
    )
    if matrix_module._partial._PYDANTIC_CORE_TRAILING_STRINGS:
        assert all(
            result["valid"]
            for case in matrix["cases"]
            for result in case["results"]
            if (
                result["name"] == "facade_structural_trailing_one_shot_finisher"
                and case["shape"] != "root_literal"
            )
        )


def test_partial_matrix_tunes_structural_decoder_from_representative_prefix(
    monkeypatch,
):
    partial_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_partial_parser.py"
    partial_spec = importlib.util.spec_from_file_location(
        "partial_benchmark_representative_sample", partial_path
    )
    assert partial_spec is not None and partial_spec.loader is not None
    partial = importlib.util.module_from_spec(partial_spec)
    partial_spec.loader.exec_module(partial)
    if partial.pydantic_core_from_json is None:
        pytest.skip("pydantic-core is required for structural tuning")

    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_partial_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location(
        "partial_strategy_matrix_representative_sample", matrix_path
    )
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)
    samples = []

    def fake_tuned_decoder(*, sample=None, trailing_strings=False):
        del trailing_strings
        samples.append(sample)
        return lambda _payload: None

    monkeypatch.setattr(
        matrix_module._partial,
        "make_tuned_structural_partial_decoder",
        fake_tuned_decoder,
    )
    matrix_module._case_functions(
        ['{"a":'],
        ['{"a":', '{"a":1}'],
        include_cumulative_finishers=True,
        input_kind="str",
    )

    assert samples == ['{"a":', '{"a":']


def test_complete_snapshot_excludes_permissive_decoders():
    snapshot = benchmark_parser.collect_complete_baseline_snapshot(
        payload_size=64,
        iterations=1,
    )
    names = {result["name"] for result in snapshot["results"]}

    assert "json_loads" not in names
    assert "custom_complete_once" not in names
    assert "ujson_loads" not in names
    assert "rapidjson_loads" not in names


def test_ndjson_strategy_matrix_covers_escape_heavy_workloads():
    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_ndjson_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location("ndjson_strategy_matrix_for_tests", matrix_path)
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)

    matrix = matrix_module.collect_matrix((2,), iterations=1)

    assert {case["shape"] for case in matrix["cases"]} == {
        "flat_records",
        "nested_records",
        "numeric_array_records",
        "unicode_records",
        "escape_heavy_records",
    }
    assert {case["input_kind"] for case in matrix["cases"]} == {
        "bytes",
        "str",
        "bytearray",
    }
    assert all(
        result["measurement_iterations"] >= 1
        for case in matrix["cases"]
        for result in case["results"]
        if result["valid"]
    )


def test_ndjson_strategy_matrix_compatibility_rejects_permissive_decoders():
    matrix_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_ndjson_strategy_matrix.py"
    matrix_spec = importlib.util.spec_from_file_location("ndjson_strategy_compatibility_for_tests", matrix_path)
    assert matrix_spec is not None and matrix_spec.loader is not None
    matrix_module = importlib.util.module_from_spec(matrix_spec)
    matrix_spec.loader.exec_module(matrix_module)

    assert not matrix_module._is_compatible(
        lambda payload: [json.loads(line) for line in payload.split(b"\n") if line],
        b'{"value":1}\n',
        [{"value": 1}],
    )


def test_compare_snapshots_ignores_common_slowdown_but_catches_relative_regression():
    tracked = {
        "sections": [
            {
                "section": "workload",
                "iterations": 1,
                "results": [
                    {"name": "a", "seconds": 1.0},
                    {"name": "b", "seconds": 2.0},
                    {"name": "c", "seconds": 3.0},
                ],
            }
        ]
    }
    common_slowdown = {
        "sections": [
            {
                "section": "workload",
                "iterations": 1,
                "results": [
                    {"name": "a", "seconds": 1.8},
                    {"name": "b", "seconds": 3.6},
                    {"name": "c", "seconds": 5.4},
                ],
            }
        ]
    }
    relative_regression = {
        "sections": [
            {
                "section": "workload",
                "iterations": 1,
                "results": [
                    {"name": "a", "seconds": 1.8},
                    {"name": "b", "seconds": 7.0},
                    {"name": "c", "seconds": 5.4},
                ],
            }
        ]
    }

    assert benchmark_parser._compare_snapshots(tracked, common_slowdown) == []
    assert any(
        item.startswith("drift:workload:b:")
        for item in benchmark_parser._compare_snapshots(tracked, relative_regression)
    )


def test_format_snapshot_markdown_renders_expected_sections():
    snapshot = {
        "date": "2026-06-13",
        "sections": [
            {
                "section": "complete_1mb_object",
                "iterations": 20,
                "payload_size": 1_000_000,
                "results": [{"name": "simdjson_parse", "seconds": 0.004684}],
            },
            {
                "section": "complete_selective_extraction",
                "iterations": 200,
                "results": [{"name": "repo_path_extractor", "seconds": 0.060561}],
            },
            {
                "section": "ndjson_selective_extraction",
                "iterations": 5,
                "results": [{"name": "tuned_ndjson_path_extractor", "seconds": 0.007967}],
            },
        ],
    }

    rendered = benchmark_parser._format_snapshot_markdown(snapshot)

    assert rendered.startswith("# Benchmark Snapshot\n")
    assert "Date: 2026-06-13" in rendered
    assert "make benchmark-artifacts" in rendered
    assert "## Complete 1 MB Object" in rendered
    assert "## Complete Selective Extraction" in rendered
    assert "## NDJSON Selective Extraction" in rendered
    assert "`simdjson_parse`: `0.004684s`" in rendered
    assert "`repo_path_extractor`: `0.060561s`" in rendered
    assert "`tuned_ndjson_path_extractor`: `0.007967s`" in rendered


def test_format_current_api_scorecard_renders_dynamic_links_and_values():
    snapshot = {
        "date": "2026-06-13",
        "sections": [
            {
                "section": "complete_1mb_object",
                "iterations": 20,
                "payload_size": 1_000_000,
                "results": [
                    {"name": "simdjson_parse", "seconds": 0.004684},
                    {"name": "msgspec_decode", "seconds": 0.005132},
                    {"name": "orjson_loads", "seconds": 0.006165},
                    {"name": "hybrid_complete_once", "seconds": 0.007136},
                    {"name": "json_loads", "seconds": 0.020029},
                    {"name": "custom_complete_once", "seconds": 0.086587},
                ],
            },
            {
                "section": "complete_selective_extraction",
                "iterations": 200,
                "results": [
                    {"name": "simdjson_proxy_manual", "seconds": 0.060565},
                    {"name": "tuned_complete_path_extractor", "seconds": 0.060461},
                    {"name": "tuned_json_path_extractor", "seconds": 0.060698},
                    {"name": "repo_path_extractor", "seconds": 0.060561},
                    {"name": "orjson_full_then_select", "seconds": 0.251542},
                ],
            },
            {
                "section": "ndjson_selective_extraction",
                "iterations": 5,
                "results": [
                    {"name": "tuned_ndjson_path_extractor", "seconds": 0.007967},
                    {"name": "tuned_json_path_extractor", "seconds": 0.008496},
                    {"name": "typed_ndjson_path_extractor", "seconds": 0.008440},
                    {"name": "orjson_full_then_select", "seconds": 0.011788},
                    {"name": "msgspec_full_then_select", "seconds": 0.012787},
                    {"name": "generic_ndjson_path_extractor", "seconds": 0.015765},
                    {"name": "native_ndjson_extract_once", "seconds": 0.039371},
                    {"name": "native_ndjson_path_extractor", "seconds": 0.040976},
                ],
            },
        ],
    }

    rendered = benchmark_parser._format_current_api_scorecard(snapshot, benchmark_parser.REPO_ROOT / "docs")

    assert rendered.startswith("# Current API Scorecard\n")
    assert "Date: 2026-06-13" in rendered
    assert "benchmark-snapshot-2026-06-13.md" in rendered
    assert "benchmark-snapshot-2026-06-13.json" in rendered
    assert "make benchmark-artifacts" in rendered
    assert "make verify-benchmark-artifacts" in rendered
    assert "`simdjson_parse`: `0.004684s`" in rendered
    assert "`tuned_complete_path_extractor`: `0.060461s`" in rendered
    assert 'native `sonic-rs` path: `0.039371s-0.040976s`' in rendered


def test_main_snapshot_json_emits_structured_output(monkeypatch, capsys):
    snapshot = {"date": "2026-06-13", "sections": [{"section": "complete_1mb_object", "iterations": 20, "results": []}]}

    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--snapshot", "json"])

    benchmark_parser.main()
    captured = capsys.readouterr()

    assert json.loads(captured.out) == snapshot


def test_main_snapshot_markdown_emits_rendered_snapshot(monkeypatch, capsys):
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: {"date": "2026-06-13", "sections": []})
    monkeypatch.setattr(benchmark_parser, "_format_snapshot_markdown", lambda snapshot: f"date={snapshot['date']}\n")
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--snapshot", "markdown"])

    benchmark_parser.main()
    captured = capsys.readouterr()

    assert captured.out == "date=2026-06-13\n"


def test_emit_snapshot_json_writes_output_file(monkeypatch, tmp_path):
    snapshot = {"date": "2026-06-13", "sections": [{"section": "complete_1mb_object", "iterations": 20, "results": []}]}
    output_path = tmp_path / "snapshot.json"

    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)

    rendered = benchmark_parser.emit_snapshot("json", output_path)

    assert json.loads(rendered) == snapshot
    assert json.loads(output_path.read_text()) == snapshot


def test_emit_snapshot_markdown_writes_output_file(monkeypatch, tmp_path):
    snapshot = {"date": "2026-06-13", "sections": []}
    output_path = tmp_path / "snapshot.md"

    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)
    monkeypatch.setattr(benchmark_parser, "_format_snapshot_markdown", lambda current: f"date={current['date']}\n")

    rendered = benchmark_parser.emit_snapshot("markdown", output_path)

    assert rendered == "date=2026-06-13\n"
    assert output_path.read_text() == "date=2026-06-13\n"


def test_main_snapshot_markdown_with_output_file(monkeypatch, capsys, tmp_path):
    output_path = tmp_path / "snapshot.md"

    monkeypatch.setattr(benchmark_parser, "emit_snapshot", lambda snapshot_format, file_path=None: f"{snapshot_format}:{file_path.name}\n")
    monkeypatch.setattr(
        sys,
        "argv",
        ["benchmark_parser.py", "--snapshot", "markdown", "--snapshot-output", str(output_path)],
    )

    benchmark_parser.main()
    captured = capsys.readouterr()

    assert captured.out == "markdown:snapshot.md\n"


def test_write_snapshot_bundle_writes_markdown_and_json(monkeypatch, tmp_path):
    snapshot = {"date": "2026-06-13", "sections": []}

    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)
    monkeypatch.setattr(benchmark_parser, "_format_snapshot_markdown", lambda current: f"date={current['date']}\n")

    created = benchmark_parser.write_snapshot_bundle(tmp_path)

    assert created["markdown"] == tmp_path / "benchmark-snapshot-2026-06-13.md"
    assert created["json"] == tmp_path / "benchmark-snapshot-2026-06-13.json"
    assert created["markdown"].read_text() == "date=2026-06-13\n"
    assert json.loads(created["json"].read_text()) == snapshot


def test_write_artifact_bundle_writes_scorecard(monkeypatch, tmp_path):
    snapshot = {
        "date": "2026-06-13",
        "sections": [
            {
                "section": "complete_1mb_object",
                "iterations": 20,
                "payload_size": 1_000_000,
                "results": [
                    {"name": "simdjson_parse", "seconds": 0.004684},
                    {"name": "msgspec_decode", "seconds": 0.005132},
                    {"name": "orjson_loads", "seconds": 0.006165},
                    {"name": "hybrid_complete_once", "seconds": 0.007136},
                    {"name": "json_loads", "seconds": 0.020029},
                    {"name": "custom_complete_once", "seconds": 0.086587},
                ],
            },
            {
                "section": "complete_selective_extraction",
                "iterations": 200,
                "results": [
                    {"name": "simdjson_proxy_manual", "seconds": 0.060565},
                    {"name": "tuned_complete_path_extractor", "seconds": 0.060461},
                    {"name": "tuned_json_path_extractor", "seconds": 0.060698},
                    {"name": "repo_path_extractor", "seconds": 0.060561},
                    {"name": "orjson_full_then_select", "seconds": 0.251542},
                ],
            },
            {
                "section": "ndjson_selective_extraction",
                "iterations": 5,
                "results": [
                    {"name": "tuned_ndjson_path_extractor", "seconds": 0.007967},
                    {"name": "tuned_json_path_extractor", "seconds": 0.008496},
                    {"name": "typed_ndjson_path_extractor", "seconds": 0.008440},
                    {"name": "orjson_full_then_select", "seconds": 0.011788},
                    {"name": "msgspec_full_then_select", "seconds": 0.012787},
                    {"name": "generic_ndjson_path_extractor", "seconds": 0.015765},
                    {"name": "native_ndjson_extract_once", "seconds": 0.039371},
                    {"name": "native_ndjson_path_extractor", "seconds": 0.040976},
                ],
            },
        ],
    }

    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)

    created = benchmark_parser.write_artifact_bundle(tmp_path)

    assert created["markdown"] == tmp_path / "benchmark-snapshot-2026-06-13.md"
    assert created["json"] == tmp_path / "benchmark-snapshot-2026-06-13.json"
    assert created["scorecard"] == tmp_path / "current-api-scorecard-2026-06-13.md"
    assert created["current_markdown"] == tmp_path / "benchmark-snapshot.md"
    assert created["current_json"] == tmp_path / "benchmark-snapshot.json"
    assert created["current_scorecard"] == tmp_path / "current-api-scorecard.md"
    assert created["scorecard"].exists()
    assert created["current_scorecard"].exists()
    assert "Current API Scorecard" in created["scorecard"].read_text()
    assert created["chart:complete_1mb_object"].exists()
    assert created["chart:complete_selective_extraction"].exists()
    assert created["chart:ndjson_selective_extraction"].exists()


def test_render_artifact_bundle_returns_expected_paths(monkeypatch, tmp_path):
    snapshot = {
        "date": "2026-06-13",
        "sections": [],
    }
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)
    monkeypatch.setattr(benchmark_parser, "_format_snapshot_markdown", lambda current: f"md:{current['date']}\n")
    monkeypatch.setattr(benchmark_parser, "_format_current_api_scorecard", lambda current, docs_dir, **kwargs: f"score:{current['date']}:{docs_dir.name}\n")

    rendered = benchmark_parser.render_artifact_bundle(tmp_path)

    assert rendered["markdown"][0] == tmp_path / "benchmark-snapshot-2026-06-13.md"
    assert rendered["markdown"][1] == "md:2026-06-13\n"
    assert rendered["json"][0] == tmp_path / "benchmark-snapshot-2026-06-13.json"
    assert json.loads(rendered["json"][1]) == snapshot
    assert rendered["scorecard"][0] == tmp_path / "current-api-scorecard-2026-06-13.md"
    assert rendered["scorecard"][1] == f"score:2026-06-13:{tmp_path.name}\n"
    assert rendered["current_markdown"][0] == tmp_path / "benchmark-snapshot.md"
    assert rendered["current_json"][0] == tmp_path / "benchmark-snapshot.json"
    assert rendered["current_scorecard"][0] == tmp_path / "current-api-scorecard.md"
    assert rendered["current_scorecard"][1] == f"score:2026-06-13:{tmp_path.name}\n"
    assert rendered["chart:complete_1mb_object"][0] == tmp_path / "assets/benchmarks/complete-decoding.svg"
    assert "No benchmark results recorded" in rendered["chart:complete_1mb_object"][1]


def test_verify_artifact_bundle_returns_empty_for_matching_files(monkeypatch, tmp_path):
    snapshot = {
        "date": "2026-06-13",
        "sections": [
            {
                "section": "complete_1mb_object",
                "iterations": 20,
                "payload_size": 1_000_000,
                "results": [{"name": "simdjson_parse", "seconds": 0.004684}],
            },
            {
                "section": "complete_selective_extraction",
                "iterations": 200,
                "results": [{"name": "repo_path_extractor", "seconds": 0.060561}],
            },
            {
                "section": "ndjson_selective_extraction",
                "iterations": 5,
                "results": [
                    {"name": "tuned_ndjson_path_extractor", "seconds": 0.007967},
                    {"name": "native_ndjson_extract_once", "seconds": 0.039371},
                    {"name": "native_ndjson_path_extractor", "seconds": 0.040976},
                ],
            },
        ],
    }
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)
    monkeypatch.setattr(benchmark_parser, "_format_snapshot_markdown", lambda current: f"md:{current['date']}\n")
    monkeypatch.setattr(benchmark_parser, "_format_current_api_scorecard", lambda current, docs_dir, **kwargs: f"score:{current['date']}\n")

    benchmark_parser.write_artifact_bundle(tmp_path)

    assert benchmark_parser.verify_artifact_bundle(tmp_path) == []


def test_verify_artifact_bundle_tolerates_small_timing_drift(monkeypatch, tmp_path):
    tracked_snapshot = {
        "date": "2026-06-13",
        "sections": [
            {
                "section": "complete_1mb_object",
                "iterations": 20,
                "payload_size": 1_000_000,
                "results": [{"name": "simdjson_parse", "seconds": 0.004684}],
            },
            {
                "section": "complete_selective_extraction",
                "iterations": 200,
                "results": [{"name": "repo_path_extractor", "seconds": 0.060561}],
            },
            {
                "section": "ndjson_selective_extraction",
                "iterations": 5,
                "results": [
                    {"name": "tuned_ndjson_path_extractor", "seconds": 0.007967},
                    {"name": "native_ndjson_extract_once", "seconds": 0.039371},
                    {"name": "native_ndjson_path_extractor", "seconds": 0.040976},
                ],
            },
        ],
    }
    current_snapshot = {
        "date": "2026-06-13",
        "sections": [
            {
                "section": "complete_1mb_object",
                "iterations": 20,
                "payload_size": 1_000_000,
                "results": [{"name": "simdjson_parse", "seconds": 0.004900}],
            },
            {
                "section": "complete_selective_extraction",
                "iterations": 200,
                "results": [{"name": "repo_path_extractor", "seconds": 0.061000}],
            },
            {
                "section": "ndjson_selective_extraction",
                "iterations": 5,
                "results": [
                    {"name": "tuned_ndjson_path_extractor", "seconds": 0.008100},
                    {"name": "native_ndjson_extract_once", "seconds": 0.040000},
                    {"name": "native_ndjson_path_extractor", "seconds": 0.041200},
                ],
            },
        ],
    }
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: tracked_snapshot)
    monkeypatch.setattr(benchmark_parser, "_format_snapshot_markdown", lambda current: f"md:{current['date']}\n")
    monkeypatch.setattr(benchmark_parser, "_format_current_api_scorecard", lambda current, docs_dir, **kwargs: f"score:{current['date']}\n")

    benchmark_parser.write_artifact_bundle(tmp_path)
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: current_snapshot)

    assert benchmark_parser.verify_artifact_bundle(tmp_path) == []


def test_verify_artifact_bundle_reports_stale_and_large_drift(monkeypatch, tmp_path):
    tracked_snapshot = {
        "date": "2026-06-13",
        "sections": [
            {
                "section": "complete_1mb_object",
                "iterations": 20,
                "payload_size": 1_000_000,
                "results": [{"name": "simdjson_parse", "seconds": 0.004684}],
            },
            {
                "section": "complete_selective_extraction",
                "iterations": 200,
                "results": [{"name": "repo_path_extractor", "seconds": 0.060561}],
            },
            {
                "section": "ndjson_selective_extraction",
                "iterations": 5,
                "results": [
                    {"name": "tuned_ndjson_path_extractor", "seconds": 0.007967},
                    {"name": "native_ndjson_extract_once", "seconds": 0.039371},
                    {"name": "native_ndjson_path_extractor", "seconds": 0.040976},
                ],
            },
        ],
    }
    current_snapshot = {
        "date": "2026-06-13",
        "sections": [
            {
                "section": "complete_1mb_object",
                "iterations": 20,
                "payload_size": 1_000_000,
                "results": [{"name": "simdjson_parse", "seconds": 0.020000}],
            },
            {
                "section": "complete_selective_extraction",
                "iterations": 200,
                "results": [{"name": "repo_path_extractor", "seconds": 0.060561}],
            },
            {
                "section": "ndjson_selective_extraction",
                "iterations": 5,
                "results": [
                    {"name": "tuned_ndjson_path_extractor", "seconds": 0.007967},
                    {"name": "native_ndjson_extract_once", "seconds": 0.039371},
                    {"name": "native_ndjson_path_extractor", "seconds": 0.040976},
                ],
            },
        ],
    }
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: tracked_snapshot)
    monkeypatch.setattr(benchmark_parser, "_format_snapshot_markdown", lambda current: f"md:{current['date']}\n")
    monkeypatch.setattr(benchmark_parser, "_format_current_api_scorecard", lambda current, docs_dir, **kwargs: f"score:{current['date']}\n")

    benchmark_parser.write_artifact_bundle(tmp_path)
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: current_snapshot)

    (tmp_path / "benchmark-snapshot.md").write_text("stale\n")

    mismatches = benchmark_parser.verify_artifact_bundle(tmp_path)

    assert f"stale:markdown:{tmp_path / 'benchmark-snapshot.md'}" in mismatches
    assert any(item.startswith("drift:complete_1mb_object:simdjson_parse:") for item in mismatches)


def test_verify_artifact_bundle_reports_missing_json(monkeypatch, tmp_path):
    snapshot = {"date": "2026-06-13", "sections": []}
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)
    monkeypatch.setattr(benchmark_parser, "_format_snapshot_markdown", lambda current: f"md:{current['date']}\n")
    monkeypatch.setattr(benchmark_parser, "_format_current_api_scorecard", lambda current, docs_dir, **kwargs: f"score:{current['date']}\n")

    benchmark_parser.write_artifact_bundle(tmp_path)
    (tmp_path / "benchmark-snapshot.json").unlink()

    mismatches = benchmark_parser.verify_artifact_bundle(tmp_path)

    assert mismatches == [f"missing:json:{tmp_path / 'benchmark-snapshot.json'}"]


def test_verify_artifact_bundle_reports_stale_chart(monkeypatch, tmp_path):
    snapshot = {
        "date": "2026-06-13",
        "sections": [
            {"section": "complete_1mb_object", "iterations": 1, "results": []},
            {"section": "complete_selective_extraction", "iterations": 1, "results": []},
            {"section": "ndjson_selective_extraction", "iterations": 1, "results": []},
        ],
    }
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)
    benchmark_parser.write_artifact_bundle(tmp_path)
    chart_path = tmp_path / "assets/benchmarks/complete-decoding.svg"
    chart_path.write_text("stale\n")

    mismatches = benchmark_parser.verify_artifact_bundle(tmp_path)

    assert f"stale:chart:complete_1mb_object:{chart_path}" in mismatches


def test_verify_artifact_bundle_reports_stale_dated_artifact(monkeypatch, tmp_path):
    snapshot = {
        "date": "2026-06-13",
        "sections": [
            {"section": "complete_1mb_object", "iterations": 1, "results": []},
            {"section": "complete_selective_extraction", "iterations": 1, "results": []},
            {"section": "ndjson_selective_extraction", "iterations": 1, "results": []},
        ],
    }
    monkeypatch.setattr(benchmark_parser, "collect_current_snapshot", lambda: snapshot)
    benchmark_parser.write_artifact_bundle(tmp_path)
    dated_path = tmp_path / "benchmark-snapshot-2026-06-13.md"
    dated_path.write_text("stale\n")

    mismatches = benchmark_parser.verify_artifact_bundle(tmp_path)

    assert f"stale:dated_markdown:{dated_path}" in mismatches


def test_compare_snapshots_reports_structure_changes():
    tracked_snapshot = {"date": "2026-06-13", "sections": [{"section": "complete_1mb_object", "iterations": 20, "payload_size": 1_000_000, "results": []}]}
    current_snapshot = {"date": "2026-06-13", "sections": [{"section": "other", "iterations": 20, "payload_size": 1_000_000, "results": []}]}

    mismatches = benchmark_parser._compare_snapshots(tracked_snapshot, current_snapshot)

    assert mismatches == ["structure:sections:complete_1mb_object,other"]


def test_main_snapshot_bundle_dir_writes_paths(monkeypatch, capsys, tmp_path):
    created = {
        "markdown": tmp_path / "benchmark-snapshot-2026-06-13.md",
        "json": tmp_path / "benchmark-snapshot-2026-06-13.json",
    }

    monkeypatch.setattr(benchmark_parser, "write_snapshot_bundle", lambda output_dir: created)
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--snapshot-bundle-dir", str(tmp_path)])

    benchmark_parser.main()
    captured = capsys.readouterr()

    assert captured.out == f"markdown={created['markdown']}\njson={created['json']}\n"


def test_main_artifacts_dir_writes_paths(monkeypatch, capsys, tmp_path):
    created = {
        "markdown": tmp_path / "benchmark-snapshot-2026-06-13.md",
        "json": tmp_path / "benchmark-snapshot-2026-06-13.json",
        "scorecard": tmp_path / "current-api-scorecard-2026-06-13.md",
    }

    monkeypatch.setattr(benchmark_parser, "write_artifact_bundle", lambda output_dir: created)
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--artifacts-dir", str(tmp_path)])

    benchmark_parser.main()
    captured = capsys.readouterr()

    assert captured.out == (
        f"markdown={created['markdown']}\n"
        f"json={created['json']}\n"
        f"scorecard={created['scorecard']}\n"
    )


def test_main_artifacts_writes_default_docs_paths(monkeypatch, capsys, tmp_path):
    created = {
        "markdown": tmp_path / "benchmark-snapshot-2026-06-13.md",
        "json": tmp_path / "benchmark-snapshot-2026-06-13.json",
        "scorecard": tmp_path / "current-api-scorecard-2026-06-13.md",
    }

    monkeypatch.setattr(benchmark_parser, "DOCS_ROOT", tmp_path)
    monkeypatch.setattr(benchmark_parser, "write_artifact_bundle", lambda output_dir: created)
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--artifacts"])

    benchmark_parser.main()
    captured = capsys.readouterr()

    assert captured.out == (
        f"markdown={created['markdown']}\n"
        f"json={created['json']}\n"
        f"scorecard={created['scorecard']}\n"
    )


def test_main_verify_artifacts_dir_ok(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(benchmark_parser, "verify_artifact_bundle", lambda output_dir: [])
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--verify-artifacts-dir", str(tmp_path)])

    benchmark_parser.main()
    captured = capsys.readouterr()

    assert captured.out == f"ok={tmp_path.resolve()}\n"


def test_main_verify_artifacts_ok(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(benchmark_parser, "DOCS_ROOT", tmp_path)
    monkeypatch.setattr(benchmark_parser, "verify_artifact_bundle", lambda output_dir: [])
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--verify-artifacts"])

    benchmark_parser.main()
    captured = capsys.readouterr()

    assert captured.out == f"ok={tmp_path.resolve()}\n"


def test_main_verify_artifacts_dir_reports_mismatches(monkeypatch, capsys, tmp_path):
    mismatches = [f"stale:markdown:{tmp_path / 'benchmark-snapshot-2026-06-13.md'}"]
    monkeypatch.setattr(benchmark_parser, "verify_artifact_bundle", lambda output_dir: mismatches)
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--verify-artifacts-dir", str(tmp_path)])

    try:
        benchmark_parser.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:  # pragma: no cover - failure path
        raise AssertionError("expected verification failure")

    captured = capsys.readouterr()
    assert captured.out == mismatches[0] + "\n"


def test_main_verify_artifacts_reports_mismatches(monkeypatch, capsys, tmp_path):
    mismatches = [f"stale:markdown:{tmp_path / 'benchmark-snapshot-2026-06-13.md'}"]
    monkeypatch.setattr(benchmark_parser, "DOCS_ROOT", tmp_path)
    monkeypatch.setattr(benchmark_parser, "verify_artifact_bundle", lambda output_dir: mismatches)
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--verify-artifacts"])

    try:
        benchmark_parser.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:  # pragma: no cover - failure path
        raise AssertionError("expected verification failure")

    captured = capsys.readouterr()
    assert captured.out == mismatches[0] + "\n"


def test_main_snapshot_output_requires_snapshot(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py", "--snapshot-output", "snapshot.md"])

    try:
        benchmark_parser.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - failure path
        raise AssertionError("expected parser error")


def test_main_artifacts_dir_cannot_be_combined(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_parser.py",
            "--artifacts-dir",
            str(tmp_path),
            "--snapshot",
            "markdown",
        ],
    )

    try:
        benchmark_parser.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - failure path
        raise AssertionError("expected parser error")


def test_main_artifacts_cannot_be_combined(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_parser.py",
            "--artifacts",
            "--verify-artifacts",
        ],
    )

    try:
        benchmark_parser.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - failure path
        raise AssertionError("expected parser error")


def test_main_verify_artifacts_dir_cannot_be_combined(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_parser.py",
            "--verify-artifacts-dir",
            str(tmp_path),
            "--snapshot",
            "markdown",
        ],
    )

    try:
        benchmark_parser.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - failure path
        raise AssertionError("expected parser error")


def test_main_verify_artifacts_cannot_be_combined(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_parser.py",
            "--verify-artifacts",
            "--snapshot",
            "markdown",
        ],
    )

    try:
        benchmark_parser.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - failure path
        raise AssertionError("expected parser error")


def test_main_snapshot_bundle_dir_cannot_be_combined(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_parser.py",
            "--snapshot",
            "markdown",
            "--snapshot-bundle-dir",
            str(tmp_path),
        ],
    )

    try:
        benchmark_parser.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - failure path
        raise AssertionError("expected parser error")


def test_main_without_snapshot_runs_full_benchmark(monkeypatch):
    called = {"value": False}

    def mark_called() -> None:
        called["value"] = True

    monkeypatch.setattr(benchmark_parser, "_run_full_benchmark", mark_called)
    monkeypatch.setattr(sys, "argv", ["benchmark_parser.py"])

    benchmark_parser.main()

    assert called["value"] is True
