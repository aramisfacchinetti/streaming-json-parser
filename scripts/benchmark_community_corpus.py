#!/usr/bin/env python3
"""Benchmark complete JSON loads using public TkTech json_benchmark data.

The upstream project also measures SAX/event streaming. This adapter only runs
its complete-document workload because this library returns Python JSON values;
SAX timings would measure different work.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
_USE_INSTALLED_PACKAGE = os.environ.get("BENCHMARK_USE_INSTALLED_PACKAGE") == "1"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if not _USE_INSTALLED_PACKAGE and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from generate_community_benchmark_chart import (  # noqa: E402
    community_corpus_chart_path,
    render_community_corpus_chart,
)

import streaming_json_parser as _PROJECT_MODULE  # noqa: E402
from streaming_json_parser import (  # noqa: E402
    ParseStatus,
    StreamingJsonParser,
    decode_complete_json,
    make_complete_json_decoder,
)

DEFAULT_DATASETS = (
    "canada.json",
    "citm_catalog.json",
    "twitter.json",
    "gsoc-2018.json",
    "poet.json",
    "fgo.json",
)
UPSTREAM_URL = "https://github.com/TkTech/json_benchmark"
SAMPLE_COUNT = 7
WARMUP_INVOCATIONS = 1
TARGET_BYTES_PER_BATCH = 4 * 1024 * 1024
MAX_REPETITIONS = 50

OPTIONAL_DISTRIBUTIONS = {
    "orjson": "orjson",
    "msgspec": "msgspec",
    "simdjson": "pysimdjson",
    "yyjson": "yyjson",
    "ujson": "ujson",
    "rapidjson": "python-rapidjson",
}


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _source_revision(data_dir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(data_dir), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _cpu_identifier() -> str:
    processor = platform.processor().strip()
    if processor.lower() in {"", "arm", "arm64", "aarch64", "x86_64", "amd64"}:
        if platform.system() == "Darwin":
            try:
                result = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                processor = result.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                processor = ""
        elif platform.system() == "Linux":
            try:
                for line in Path("/proc/cpuinfo").read_text().splitlines():
                    if line.lower().startswith(("model name", "hardware")):
                        processor = line.partition(":")[2].strip()
                        if processor:
                            break
            except OSError:
                processor = ""
    return processor or "unavailable"


def _environment() -> dict[str, Any]:
    import streaming_json_parser.high_performance_parser as parser_module

    distribution_version = _version("streaming-json-parser")
    if _USE_INSTALLED_PACKAGE:
        module_path = Path(_PROJECT_MODULE.__file__).resolve()
        if distribution_version is None or SRC_ROOT in module_path.parents:
            raise RuntimeError(
                "BENCHMARK_USE_INSTALLED_PACKAGE=1 requires an installed distribution "
                "and must not import the repository source tree"
            )

    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        revision, dirty = None, None

    try:
        native_version = importlib.metadata.version("streaming-json-parser-native")
    except importlib.metadata.PackageNotFoundError:
        native_version = None

    return {
        "package_version": (
            distribution_version if _USE_INSTALLED_PACKAGE else _PROJECT_MODULE.__version__
        ),
        "package_module_version": _PROJECT_MODULE.__version__,
        "installed_distribution_version": distribution_version,
        "package_source": (
            "installed distribution" if _USE_INSTALLED_PACKAGE else "repository source tree"
        ),
        "source_revision": revision or None,
        "working_tree_dirty": dirty,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "operating_system": platform.system(),
        "architecture": platform.machine() or "unavailable",
        "processor": _cpu_identifier(),
        "native_extension_version": native_version,
        "native_extension_importable": parser_module._backend_native is not None,
        "benchmark_library_versions": {
            "json (stdlib)": platform.python_version(),
            **{name: _version(distribution) for name, distribution in OPTIONAL_DISTRIBUTIONS.items()},
        },
    }


def _streaming_parser_decode(payload: str) -> Any:
    parser = StreamingJsonParser()
    result = parser.feed(payload)
    if result.status is not ParseStatus.COMPLETE:
        raise ValueError(f"streaming parser returned {result.status!r} for a complete document")
    return result.value


def _candidate_decoders(payload: str) -> list[tuple[str, Callable[[], Any]]]:
    reusable_decoder = make_complete_json_decoder()
    candidates: list[tuple[str, Callable[[], Any]]] = [
        ("decode_complete_json", lambda: decode_complete_json(payload)),
        ("reusable_complete_decoder", lambda: reusable_decoder(payload)),
        ("streaming_parser_single_chunk", lambda: _streaming_parser_decode(payload)),
        ("json_loads", lambda: json.loads(payload)),
    ]

    optional_functions = (
        ("orjson", "orjson_loads", lambda module: lambda: module.loads(payload)),
        ("msgspec", "msgspec_decode", lambda module: lambda: module.json.decode(payload)),
        ("simdjson", "simdjson_loads", lambda module: lambda: module.loads(payload)),
        ("yyjson", "yyjson_loads", lambda module: lambda: module.loads(payload)),
        ("ujson", "ujson_loads", lambda module: lambda: module.loads(payload)),
        ("rapidjson", "rapidjson_loads", lambda module: lambda: module.loads(payload)),
    )
    for module_name, result_name, make_decoder in optional_functions:
        try:
            module = __import__(module_name)
        except ImportError:
            continue
        if module_name == "msgspec":
            decoder = module.json.Decoder()
            candidates.append(
                (result_name, lambda decoder=decoder: decoder.decode(payload))
            )
            continue
        candidates.append((result_name, make_decoder(module)))
    return candidates


def _json_values_equal(value: Any, reference: Any) -> bool:
    """Compare decoded JSON trees without Python's bool/int equality shortcut."""
    if isinstance(value, dict) and isinstance(reference, dict):
        if len(value) != len(reference) or any(type(key) is not str for key in value):
            return False
        if value.keys() != reference.keys():
            return False
        return all(_json_values_equal(value[key], reference[key]) for key in reference)
    if isinstance(value, list) and isinstance(reference, list):
        return len(value) == len(reference) and all(
            _json_values_equal(item, expected)
            for item, expected in zip(value, reference, strict=True)
        )
    if isinstance(value, bool) or isinstance(reference, bool):
        return type(value) is type(reference) and value is reference
    if isinstance(value, (int, float)) or isinstance(reference, (int, float)):
        if type(value) is not type(reference):
            return False
        if isinstance(value, float):
            if math.isnan(value) and math.isnan(reference):
                return True
            if value == reference == 0.0:
                return math.copysign(1.0, value) == math.copysign(1.0, reference)
        return value == reference
    return type(value) is type(reference) and value == reference


def _compatible(decoder: Callable[[], Any], reference: Any) -> tuple[bool, str | None]:
    try:
        value = decoder()
    except Exception as exc:  # optional backend compatibility is workload-specific
        return False, f"{type(exc).__name__}: {exc}"
    if _json_values_equal(value, reference):
        return True, None
    return False, "decoded value differs from Python json.loads"


def _repetitions(payload_bytes: int) -> int:
    return max(1, min(MAX_REPETITIONS, TARGET_BYTES_PER_BATCH // max(payload_bytes, 1)))


def _measure(
    decoder: Callable[[], Any], repetitions: int, warmups: int, samples: int
) -> list[float]:
    for _ in range(warmups):
        for _ in range(repetitions):
            decoder()
    elapsed_per_operation = []
    for _ in range(samples):
        started = time.perf_counter()
        for _ in range(repetitions):
            decoder()
        elapsed_per_operation.append((time.perf_counter() - started) / repetitions)
    return elapsed_per_operation


def collect_snapshot(
    data_dir: Path,
    *,
    datasets: tuple[str, ...] = DEFAULT_DATASETS,
    samples: int = SAMPLE_COUNT,
    warmups: int = WARMUP_INVOCATIONS,
) -> dict[str, Any]:
    """Run complete-load cases from the upstream suite's public data files."""
    sections = []
    excluded: dict[str, dict[str, str]] = {}
    for filename in datasets:
        path = data_dir / filename
        payload_bytes = path.read_bytes()
        payload_text = payload_bytes.decode("utf-8")
        reference = json.loads(payload_text)
        repetitions = _repetitions(len(payload_bytes))
        results = []
        excluded_for_file: dict[str, str] = {}
        for name, decoder in _candidate_decoders(payload_text):
            compatible, reason = _compatible(decoder, reference)
            if not compatible:
                excluded_for_file[name] = reason or "incompatible output"
                continue
            sample_times = _measure(decoder, repetitions, warmups, samples)
            median_seconds = statistics.median(sample_times)
            results.append(
                {
                    "name": name,
                    "seconds_per_operation": median_seconds,
                    "minimum_seconds_per_operation": min(sample_times),
                    "maximum_seconds_per_operation": max(sample_times),
                    "mib_per_second": (len(payload_bytes) / (1024 * 1024)) / median_seconds,
                    "sample_seconds_per_operation": sample_times,
                }
            )
        sections.append(
            {
                "name": f"data/{filename}",
                "file_name": filename,
                "payload_size_bytes": len(payload_bytes),
                "text_character_count": len(payload_text),
                "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "repetitions_per_sample": repetitions,
                "sample_count": samples,
                "warmup_batches": warmups,
                "results": sorted(
                    results,
                    key=lambda result: (result["seconds_per_operation"], result["name"]),
                ),
            }
        )
        if excluded_for_file:
            excluded[filename] = excluded_for_file

    return {
        "date": time.strftime("%Y-%m-%d"),
        "benchmark": "TkTech/json_benchmark complete-document load workload (adapted)",
        "upstream": {
            "repository": UPSTREAM_URL,
            "commit": _source_revision(data_dir),
            "benchmark_definition": "tests/test_json.py::test_full_document_read",
            "data_definition": "tests/conftest.py::SAMPLE_FILES",
            "license": "Public Domain (upstream project metadata)",
        },
        "environment": _environment(),
        "methodology": {
            "command": os.environ.get(
                "BENCHMARK_ARTIFACT_COMMAND",
                (
                    "BENCHMARK_USE_INSTALLED_PACKAGE=1 make benchmark-community-corpus "
                    "COMMUNITY_JSON_CORPUS_DIR=/path/to/json_benchmark/data"
                    if _USE_INSTALLED_PACKAGE
                    else "make benchmark-community-corpus "
                    "COMMUNITY_JSON_CORPUS_DIR=/path/to/json_benchmark/data"
                ),
            ),
            "operation": "decode the complete document into an ordinary Python JSON value",
            "input": "UTF-8 data file decoded to Python str before timing; file I/O and UTF-8 decoding are outside timing",
            "clock": "time.perf_counter",
            "aggregation": f"median per-operation elapsed time across {samples} measured batches",
            "samples_per_case": samples,
            "warmup_invocations_per_case": warmups,
            "repetitions_per_sample": "max(1, floor(4 MiB / UTF-8 file byte length)), capped at 50; same count for every compatible decoder on a file",
            "comparison": "each candidate output was compared recursively with Python json.loads; booleans, integers, and floats must retain their exact Python value types, and incompatible candidates are excluded for that file",
            "throughput": "UTF-8 file bytes divided by median per-operation elapsed time; chart uses MiB/s, higher is better",
            "scope_note": "This adapts only the upstream complete-load workload. Its SAX/event streaming cases are not comparable because this library materializes Python values.",
        },
        "excluded_candidates": excluded,
        "sections": sections,
    }


def _format_report(snapshot: dict[str, Any]) -> str:
    environment = snapshot["environment"]
    upstream = snapshot["upstream"]
    methodology = snapshot["methodology"]
    versions = environment["benchmark_library_versions"]
    reproduce_commands = [
        f"python -m pip install 'streaming-json-parser[accelerated,benchmark]=={environment['package_version']}'"
    ]
    if environment.get("native_extension_version"):
        reproduce_commands.append(
            f"python -m pip install 'streaming-json-parser-native=={environment['native_extension_version']}'"
        )
    reproduce_commands.append(
        "git clone https://github.com/TkTech/json_benchmark.git /tmp/tktech-json-benchmark"
    )
    if upstream.get("commit"):
        reproduce_commands.append(
            f"git -C /tmp/tktech-json-benchmark checkout {upstream['commit']}"
        )
    reproduce_commands.append(
        methodology.get(
            "command",
            "BENCHMARK_USE_INSTALLED_PACKAGE=1 make benchmark-community-corpus "
            "COMMUNITY_JSON_CORPUS_DIR=/tmp/tktech-json-benchmark/data",
        )
    )
    lines = [
        "# Community JSON Benchmark Snapshot",
        "",
        f"Date: {snapshot['date']}",
        "",
        "This run adapts the complete-document load workload and public data files from [TkTech/json_benchmark](https://github.com/TkTech/json_benchmark). It is a community-maintained Python parser benchmark, not a formal industry standard. The upstream project also has SAX/event streaming cases; those are omitted because they do not materialize the same result as this library.",
        "",
        "## Provenance",
        "",
        f"- Upstream commit: `{upstream.get('commit') or 'unavailable'}`",
        f"- Upstream benchmark definition: `{upstream['benchmark_definition']}`",
        f"- Package: `streaming-json-parser {environment['package_version']}` ({environment['package_source']}); source revision: `{environment.get('source_revision') or 'unavailable'}`",
        f"- Module `__version__`: `{environment['package_module_version']}`; installed distribution metadata: `{environment.get('installed_distribution_version') or 'not installed'}`",
        f"- Working tree dirty: `{environment.get('working_tree_dirty')}`",
        f"- Python and platform: `{environment['python_version']}` / `{environment['platform']}`",
        f"- Processor: `{environment['processor']}` ({environment['architecture']})",
        f"- Native extension: `{environment.get('native_extension_version') or 'not installed'}`",
        "- Benchmark library versions: " + ", ".join(
            f"`{name}={version or 'not installed'}`"
            for name, version in sorted(versions.items())
        ),
        "",
        "## Methodology",
        "",
        f"- Operation: {methodology['operation']}.",
        f"- Input: {methodology['input']}.",
        f"- Timing: `{methodology['clock']}`; {methodology['aggregation']}; {methodology['warmup_invocations_per_case']} warm-up batch(s).",
        f"- Repetitions: {methodology['repetitions_per_sample']}.",
        f"- Fairness check: {methodology['comparison']}.",
        f"- Rate: {methodology['throughput']}.",
        f"- Scope: {methodology['scope_note']}",
        "",
        "The chart uses one scale per corpus file. Use the number labels and the exact values below for cross-file comparisons.",
        "",
        "## Results",
    ]
    for section in snapshot["sections"]:
        lines.extend(
            [
                "",
                f"### `{section['name']}` — {section['payload_size_bytes']:,} bytes",
                "",
                f"SHA-256: `{section['sha256']}`. {section['repetitions_per_sample']} load(s) per sample; {section['sample_count']} samples.",
                "",
                "| Rank | Decoder | Median elapsed ms/load | MiB/s |",
                "| ---: | --- | ---: | ---: |",
            ]
        )
        for index, result in enumerate(section["results"], start=1):
            lines.append(
                f"| {index} | `{result['name']}` | {result['seconds_per_operation'] * 1000:,.3f} | {result['mib_per_second']:,.1f} |"
            )
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "```bash",
            *reproduce_commands,
            "```",
            "",
            "The input files are not copied into this repository. The JSON snapshot records the upstream revision, file hashes, and exact tool versions for this run.",
        ]
    )
    excluded = snapshot.get("excluded_candidates", {})
    if excluded:
        lines.extend(["", "## Excluded incompatible results", ""])
        for filename, reasons in sorted(excluded.items()):
            for name, reason in sorted(reasons.items()):
                lines.append(f"- `{filename}` / `{name}`: {reason}")
    return "\n".join(lines) + "\n"


def _dated_artifact_stem(snapshot: dict[str, Any], output_dir: Path) -> str:
    stem = f"community-json-benchmark-{snapshot['date']}"
    prior_json = output_dir / f"{stem}.json"
    if not prior_json.exists():
        return stem
    try:
        prior_snapshot = json.loads(prior_json.read_text())
    except (OSError, json.JSONDecodeError):
        prior_version = None
    else:
        prior_version = prior_snapshot.get("environment", {}).get("package_version")
    current_version = snapshot.get("environment", {}).get("package_version")
    if prior_version != current_version:
        return f"{stem}-core-{current_version or 'unknown'}"
    return stem


def write_artifacts(snapshot: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_path = community_corpus_chart_path(output_dir)
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart = render_community_corpus_chart(snapshot)
    report = _format_report(snapshot)
    rendered_json = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    current_json = output_dir / "community-json-benchmark.json"
    current_markdown = output_dir / "community-json-benchmark.md"
    dated_stem = _dated_artifact_stem(snapshot, output_dir)
    dated_json = output_dir / f"{dated_stem}.json"
    dated_markdown = output_dir / f"{dated_stem}.md"
    for path, content in (
        (current_json, rendered_json),
        (dated_json, rendered_json),
        (current_markdown, report),
        (dated_markdown, report),
        (chart_path, chart),
    ):
        path.write_text(content)
    return {
        "json": current_json,
        "markdown": current_markdown,
        "dated_json": dated_json,
        "dated_markdown": dated_markdown,
        "chart": chart_path,
    }


def verify_artifacts(output_dir: Path) -> list[str]:
    current_json = output_dir / "community-json-benchmark.json"
    if not current_json.exists():
        return [f"missing:{current_json}"]
    snapshot = json.loads(current_json.read_text())
    expected_json = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    expected_markdown = _format_report(snapshot)
    dated_stem = _dated_artifact_stem(snapshot, output_dir)
    expected = {
        current_json: expected_json,
        output_dir / f"{dated_stem}.json": expected_json,
        output_dir / "community-json-benchmark.md": expected_markdown,
        output_dir / f"{dated_stem}.md": expected_markdown,
        community_corpus_chart_path(output_dir): render_community_corpus_chart(snapshot),
    }
    return [f"stale-or-missing:{path}" for path, content in expected.items() if not path.exists() or path.read_text() != content]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, help="Path to TkTech/json_benchmark/data")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "docs")
    parser.add_argument("--verify", action="store_true", help="Verify existing report and chart against their JSON snapshot")
    parser.add_argument("--datasets", nargs="+", default=list(DEFAULT_DATASETS), choices=DEFAULT_DATASETS)
    parser.add_argument("--samples", type=int, default=SAMPLE_COUNT)
    parser.add_argument("--warmups", type=int, default=WARMUP_INVOCATIONS)
    args = parser.parse_args()
    if args.verify:
        mismatches = verify_artifacts(args.output_dir)
        if mismatches:
            raise SystemExit("\n".join(mismatches))
        print("community JSON benchmark artifacts match their snapshot")
        return
    if args.corpus_dir is None:
        parser.error("--corpus-dir is required unless --verify is used")
    if args.samples < 1 or args.warmups < 0:
        parser.error("--samples must be positive and --warmups cannot be negative")
    snapshot = collect_snapshot(
        args.corpus_dir,
        datasets=tuple(args.datasets),
        samples=args.samples,
        warmups=args.warmups,
    )
    paths = write_artifacts(snapshot, args.output_dir)
    for label, path in paths.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
