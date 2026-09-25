import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_community_corpus.py"
MODULE_SPEC = importlib.util.spec_from_file_location("community_corpus_benchmark_for_tests", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
community_benchmark = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(community_benchmark)


def test_community_corpus_snapshot_includes_compatible_decoders_and_provenance(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "canada.json").write_text('{"city":"Zurich","rows":[1,2,3]}')

    snapshot = community_benchmark.collect_snapshot(
        data_dir,
        datasets=("canada.json",),
        samples=1,
        warmups=0,
    )

    section = snapshot["sections"][0]
    names = {result["name"] for result in section["results"]}
    assert snapshot["upstream"]["benchmark_definition"] == "tests/test_json.py::test_full_document_read"
    assert section["name"] == "data/canada.json"
    assert section["payload_size_bytes"] == len('{"city":"Zurich","rows":[1,2,3]}'.encode())
    assert len(section["sha256"]) == 64
    assert {"decode_complete_json", "reusable_complete_decoder", "streaming_parser_single_chunk", "json_loads"} <= names
    assert all(result["mib_per_second"] > 0 for result in section["results"])


def test_community_benchmark_survives_quantized_process_cpu_clock(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "canada.json").write_text('{"city":"Zurich"}')
    monkeypatch.setattr(community_benchmark.time, "process_time", lambda: 0.0)

    snapshot = community_benchmark.collect_snapshot(
        data_dir,
        datasets=("canada.json",),
        samples=1,
        warmups=0,
    )

    assert snapshot["methodology"]["clock"] == "time.perf_counter"
    assert all(result["mib_per_second"] > 0 for result in snapshot["sections"][0]["results"])


def test_environment_records_installed_distribution_version(monkeypatch, tmp_path):
    monkeypatch.setattr(community_benchmark, "_USE_INSTALLED_PACKAGE", True)
    monkeypatch.setattr(
        community_benchmark._PROJECT_MODULE,
        "__file__",
        str(tmp_path / "site-packages" / "streaming_json_parser" / "__init__.py"),
    )
    monkeypatch.setattr(
        community_benchmark,
        "_version",
        lambda name: "0.2.1" if name.startswith("streaming-json-parser") else None,
    )

    environment = community_benchmark._environment()

    assert environment["package_version"] == "0.2.1"
    assert environment["package_module_version"] == community_benchmark._PROJECT_MODULE.__version__
    assert environment["installed_distribution_version"] == "0.2.1"
    assert environment["package_source"] == "installed distribution"


def test_compatibility_requires_exact_json_value_types():
    assert not community_benchmark._compatible(lambda: {"flag": 1}, {"flag": True})[0]
    assert not community_benchmark._compatible(lambda: [1.0], [1])[0]
    assert not community_benchmark._compatible(lambda: -0.0, 0.0)[0]
    assert community_benchmark._compatible(lambda: {"flag": True, "count": 1}, {"flag": True, "count": 1})[0]


def test_community_corpus_artifacts_are_deterministic_and_verifiable(tmp_path):
    snapshot = {
        "date": "2026-09-23",
        "benchmark": "adapted TkTech corpus",
        "upstream": {
            "repository": "https://github.com/TkTech/json_benchmark",
            "commit": "abc123",
            "benchmark_definition": "tests/test_json.py::test_full_document_read",
            "data_definition": "tests/conftest.py::SAMPLE_FILES",
            "license": "Public Domain",
        },
        "environment": {
            "package_version": "0.2.0",
            "package_module_version": "0.2.0",
            "installed_distribution_version": "0.2.0",
            "package_source": "installed distribution",
            "source_revision": "abc123",
            "working_tree_dirty": True,
            "python_version": "3.14.0",
            "platform": "test platform",
            "processor": "test CPU",
            "architecture": "arm64",
            "native_extension_version": "0.2.0",
            "benchmark_library_versions": {
                "json (stdlib)": "3.14.0",
                "orjson": "3.12.0",
                "msgspec": "0.21.1",
            },
        },
        "methodology": {
            "operation": "complete decode",
            "input": "preloaded Python str",
            "clock": "time.process_time",
            "aggregation": "median per-operation CPU time",
            "samples_per_case": 1,
            "warmup_invocations_per_case": 0,
            "repetitions_per_sample": "one",
            "comparison": "output equality",
            "throughput": "UTF-8 file bytes / seconds",
            "scope_note": "complete loads only",
        },
        "excluded_candidates": {
            "twitter.json": {"yyjson_loads": "decoded value differs"},
            "canada.json": {"ujson_loads": "decoded value differs"},
        },
        "sections": [
            {
                "name": "data/canada.json",
                "file_name": "canada.json",
                "payload_size_bytes": 10,
                "text_character_count": 10,
                "sha256": "0" * 64,
                "repetitions_per_sample": 1,
                "sample_count": 1,
                "warmup_batches": 0,
                "results": [
                    {
                        "name": "decode_complete_json",
                        "seconds_per_operation": 0.001,
                        "minimum_seconds_per_operation": 0.001,
                        "maximum_seconds_per_operation": 0.001,
                        "mib_per_second": 9.5,
                        "sample_seconds_per_operation": [0.001],
                    },
                    {
                        "name": "json_loads",
                        "seconds_per_operation": 0.002,
                        "minimum_seconds_per_operation": 0.002,
                        "maximum_seconds_per_operation": 0.002,
                        "mib_per_second": 4.8,
                        "sample_seconds_per_operation": [0.002],
                    },
                ],
            }
        ],
    }

    output_dir = tmp_path / "docs"
    community_benchmark.write_artifacts(snapshot, output_dir)
    chart = (output_dir / "assets/benchmarks/community-json-corpus-throughput.svg").read_text()

    assert community_benchmark.verify_artifacts(output_dir) == []
    assert "higher is better" in chart
    assert "9.5 MiB/s" in chart
    assert "decode_complete_json" in chart

    (output_dir / "community-json-benchmark.md").write_text("stale\n")
    assert any("community-json-benchmark.md" in issue for issue in community_benchmark.verify_artifacts(output_dir))

    prior_dated_json = output_dir / "community-json-benchmark-2026-09-23.json"
    prior_dated_content = prior_dated_json.read_text()
    updated_snapshot = json.loads(prior_dated_content)
    updated_snapshot["environment"]["package_version"] = "0.2.3"
    updated_snapshot["environment"]["package_module_version"] = "0.2.3"
    updated_snapshot["environment"]["installed_distribution_version"] = "0.2.3"

    paths = community_benchmark.write_artifacts(updated_snapshot, output_dir)

    assert paths["dated_json"].name == "community-json-benchmark-2026-09-23-core-0.2.3.json"
    assert prior_dated_json.read_text() == prior_dated_content
    assert community_benchmark.verify_artifacts(output_dir) == []
