import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_benchmark_charts.py"
MODULE_SPEC = importlib.util.spec_from_file_location("benchmark_charts_for_tests", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
benchmark_charts = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(benchmark_charts)


def test_chart_uses_all_snapshot_values_and_is_deterministic():
    snapshot = {
        "sections": [
            {
                "section": "complete_1mb_object",
                "iterations": 20,
                "workload": "1,000,012-byte object",
                "results": [
                    {"name": "msgspec_decode", "seconds": 0.005},
                    {"name": "facade_reusable_complete_decoder", "seconds": 0.00125},
                    {"name": "custom<decoder>", "seconds": 0.003},
                ],
            }
        ]
    }

    first = benchmark_charts.render_chart(snapshot, "complete_1mb_object", "Complete JSON decoding")
    second = benchmark_charts.render_chart(snapshot, "complete_1mb_object", "Complete JSON decoding")

    assert first == second
    assert "lower is better" in first
    assert "1,000,012-byte object" in first
    assert "Reusable complete decoder" in first
    assert "msgspec" in first
    assert "custom&lt;decoder&gt;" in first
    assert "1.25 ms" in first
    assert "3.00 ms" in first
    assert "5.00 ms" in first
    assert first.index("Reusable complete decoder") < first.index("custom&lt;decoder&gt;")
    assert first.index("custom&lt;decoder&gt;") < first.index("msgspec")


def test_render_all_charts_has_stable_repository_paths(tmp_path):
    rendered = benchmark_charts.render_benchmark_charts({"sections": []}, tmp_path)

    assert set(rendered) == {
        "chart:complete_1mb_object",
        "chart:complete_selective_extraction",
        "chart:ndjson_selective_extraction",
    }
    assert all(path.parent == tmp_path / "assets" / "benchmarks" for path, _ in rendered.values())


def test_streaming_parser_complete_input_label_is_explicit():
    assert (
        benchmark_charts._label("streaming_parser_single_chunk")
        == "StreamingJsonParser — single chunk"
    )
