#!/usr/bin/env python3
"""Compare same-source local ABI3 and CPython-specific incremental builds."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"
_NATIVE_CASES = (
    "streaming_json_parser_native_public",
    "native_incremental_direct_result",
)
_PYTHON_CONTROL = "streaming_json_parser_python_fallback"
_MAX_MEDIAN_CONTROL_DIFFERENCE = 0.15
_MAX_P90_CONTROL_DIFFERENCE = 0.30
_MAX_SINGLE_CONTROL_DIFFERENCE = 0.50


def _case_key(case: dict[str, Any]) -> tuple[Any, ...]:
    return (
        case["shape"],
        case["requested_size"],
        case["payload_size_bytes"],
        case["chunk_size_bytes"],
        case["chunk_count"],
    )


def _validate_pair(abi3: dict[str, Any], cpython: dict[str, Any]) -> dict[tuple[Any, ...], float]:
    abi3_environment = abi3["environment"]
    cpython_environment = cpython["environment"]
    abi3_native = abi3_environment["native_extension"]
    cpython_native = cpython_environment["native_extension"]

    if abi3_native.get("build_variant") != "abi3" or abi3_native.get("abi3_binary") is not True:
        raise ValueError("first input must come from a local ABI3 native build")
    if cpython_native.get("build_variant") != "cpython-specific" or cpython_native.get("abi3_binary") is not False:
        raise ValueError("second input must come from a CPython-specific native build")
    if (
        abi3_environment.get("package_source") != "installed distribution"
        or cpython_environment.get("package_source") != "installed distribution"
    ):
        raise ValueError("build comparison requires the installed core release distribution")
    if abi3_environment.get("commit_sha") != cpython_environment.get("commit_sha"):
        raise ValueError("build comparison requires the same source revision")
    if not abi3_environment.get("commit_sha"):
        raise ValueError("build comparison requires source revision provenance")
    if abi3_environment.get("working_tree_dirty") is not False or cpython_environment.get("working_tree_dirty") is not False:
        raise ValueError("build comparison requires a clean source tree")
    if (
        abi3_environment.get("native_source_fingerprint_without_abi_feature")
        != cpython_environment.get("native_source_fingerprint_without_abi_feature")
    ):
        raise ValueError("build comparison requires identical native source and Cargo.lock content")
    shared_environment_fields = (
        "package_version",
        "installed_distribution_version",
        "python_version",
        "operating_system",
        "platform",
        "architecture",
        "processor",
        "benchmark_package_versions",
        "rustc_version",
        "cargo_version",
        "maturin_version",
    )
    mismatched = [
        field
        for field in shared_environment_fields
        if abi3_environment.get(field) != cpython_environment.get(field)
    ]
    if mismatched:
        raise ValueError(f"build comparison environment differs: {', '.join(mismatched)}")
    if not abi3_environment.get("rustc_version") or not abi3_environment.get("cargo_version"):
        raise ValueError("build comparison requires recorded Rust compiler and Cargo versions")
    if abi3_native.get("distribution_version") != cpython_native.get("distribution_version"):
        raise ValueError("build comparison requires matching native package versions")
    if abi3.get("methodology") != cpython.get("methodology"):
        raise ValueError("build comparison requires matching benchmark methodology")
    if abi3.get("sizes") != cpython.get("sizes") or abi3.get("chunk_sizes_bytes") != cpython.get("chunk_sizes_bytes"):
        raise ValueError("build comparison requires matching payload sizes and chunk sizes")

    abi3_cases = {_case_key(case): case for case in abi3.get("cases", [])}
    cpython_cases = {_case_key(case): case for case in cpython.get("cases", [])}
    if not abi3_cases or abi3_cases.keys() != cpython_cases.keys():
        raise ValueError("build comparison requires identical shape/chunk workloads")
    control_differences = {}
    for key, abi3_case in abi3_cases.items():
        cpython_case = cpython_cases[key]
        if abi3_case.get("sample_count") != cpython_case.get("sample_count"):
            raise ValueError(f"sample count differs for workload {key}")
        abi3_python = next(
            (result for result in abi3_case["results"] if result["name"] == _PYTHON_CONTROL),
            None,
        )
        cpython_python = next(
            (result for result in cpython_case["results"] if result["name"] == _PYTHON_CONTROL),
            None,
        )
        if (
            not abi3_python
            or not cpython_python
            or not abi3_python.get("valid")
            or not cpython_python.get("valid")
        ):
            raise ValueError(f"missing valid Python timing control for workload {key}")
        abi3_python_seconds = abi3_python["median_seconds_per_stream"]
        cpython_python_seconds = cpython_python["median_seconds_per_stream"]
        if abi3_python_seconds <= 0 or cpython_python_seconds <= 0:
            raise ValueError(f"Python timing control is not positive for workload {key}")
        control_difference = abs(abi3_python_seconds / cpython_python_seconds - 1.0)
        control_differences[key] = control_difference * 100.0
        for name in _NATIVE_CASES:
            abi3_result = next(
                (result for result in abi3_case["results"] if result["name"] == name),
                None,
            )
            cpython_result = next(
                (result for result in cpython_case["results"] if result["name"] == name),
                None,
            )
            if not abi3_result or not cpython_result or not abi3_result.get("valid") or not cpython_result.get("valid"):
                raise ValueError(f"missing valid {name} measurements for workload {key}")
    differences = sorted(control_differences.values())
    p90_difference = differences[max(0, math.ceil(0.9 * len(differences)) - 1)]
    control_summary = {
        "median_per_workload_difference_percent": statistics.median(differences),
        "p90_per_workload_difference_percent": p90_difference,
        "max_per_workload_difference_percent": max(differences),
        "compared_workload_count": len(differences),
        "maximum_median_difference_percent": _MAX_MEDIAN_CONTROL_DIFFERENCE * 100.0,
        "maximum_p90_difference_percent": _MAX_P90_CONTROL_DIFFERENCE * 100.0,
        "maximum_single_difference_percent": _MAX_SINGLE_CONTROL_DIFFERENCE * 100.0,
    }
    if (
        control_summary["median_per_workload_difference_percent"]
        > control_summary["maximum_median_difference_percent"]
        or control_summary["p90_per_workload_difference_percent"]
        > control_summary["maximum_p90_difference_percent"]
        or control_summary["max_per_workload_difference_percent"]
        > control_summary["maximum_single_difference_percent"]
    ):
        raise ValueError(
            "Python fallback timing control is too noisy across the build pair: "
            f"median {control_summary['median_per_workload_difference_percent']:.1f}% "
            f"(limit {control_summary['maximum_median_difference_percent']:.0f}%), "
            f"p90 {control_summary['p90_per_workload_difference_percent']:.1f}% "
            f"(limit {control_summary['maximum_p90_difference_percent']:.0f}%), "
            f"max {control_summary['max_per_workload_difference_percent']:.1f}% "
            f"(limit {control_summary['maximum_single_difference_percent']:.0f}%)"
        )
    return control_differences


def build_comparison(abi3: dict[str, Any], cpython: dict[str, Any]) -> dict[str, Any]:
    control_differences = _validate_pair(abi3, cpython)
    abi3_environment = abi3["environment"]
    cpython_environment = cpython["environment"]
    abi3_cases = {_case_key(case): case for case in abi3["cases"]}
    cpython_cases = {_case_key(case): case for case in cpython["cases"]}
    cases = []
    per_implementation: dict[str, list[float]] = {name: [] for name in _NATIVE_CASES}
    slower_case_counts = {name: 0 for name in _NATIVE_CASES}
    for key in sorted(abi3_cases, key=lambda item: (item[0], item[1], item[3])):
        abi3_case = abi3_cases[key]
        cpython_case = cpython_cases[key]
        abi3_results = {result["name"]: result for result in abi3_case["results"]}
        cpython_results = {result["name"]: result for result in cpython_case["results"]}
        implementation_results = []
        for name in _NATIVE_CASES:
            abi3_seconds = abi3_results[name]["median_seconds_per_stream"]
            cpython_seconds = cpython_results[name]["median_seconds_per_stream"]
            slowdown_percent = (abi3_seconds / cpython_seconds - 1.0) * 100.0
            per_implementation[name].append(slowdown_percent)
            slower_case_counts[name] += slowdown_percent > 0
            implementation_results.append(
                {
                    "name": name,
                    "display_name": abi3_results[name]["display_name"],
                    "abi3_median_seconds_per_stream": abi3_seconds,
                    "cpython_specific_median_seconds_per_stream": cpython_seconds,
                    "abi3_slowdown_percent": slowdown_percent,
                    "abi3_sample_seconds_per_stream": abi3_results[name]["sample_seconds_per_stream"],
                    "cpython_specific_sample_seconds_per_stream": cpython_results[name]["sample_seconds_per_stream"],
                }
            )
        cases.append(
            {
                "shape": abi3_case["shape"],
                "requested_size": abi3_case["requested_size"],
                "payload_size_bytes": abi3_case["payload_size_bytes"],
                "chunk_size_bytes": abi3_case["chunk_size_bytes"],
                "chunk_count": abi3_case["chunk_count"],
                "python_fallback_control_difference_percent": control_differences[key],
                "results": implementation_results,
            }
        )
    summary = {
        name: {
            "median_abi3_slowdown_percent": statistics.median(values),
            "abi3_slower_case_count": slower_case_counts[name],
            "paired_case_count": len(values),
            "slowdown_definition": "(ABI3 elapsed time / CPython-specific elapsed time - 1) * 100; positive means ABI3 was slower",
        }
        for name, values in per_implementation.items()
    }
    shape_results: dict[str, dict[str, list[float]]] = {}
    for case in cases:
        results = {result["name"]: result for result in case["results"]}
        shape = shape_results.setdefault(
            case["shape"], {name: [] for name in _NATIVE_CASES}
        )
        for name in _NATIVE_CASES:
            shape[name].append(results[name]["abi3_slowdown_percent"])
    shape_summary = [
        {
            "shape": shape,
            "paired_case_count": len(values[_NATIVE_CASES[0]]),
            "public_median_abi3_slowdown_percent": statistics.median(
                values["streaming_json_parser_native_public"]
            ),
            "direct_median_abi3_slowdown_percent": statistics.median(
                values["native_incremental_direct_result"]
            ),
        }
        for shape, values in sorted(shape_results.items())
    ]
    return {
        "date": abi3["date"],
        "benchmark": "same-source ABI3 versus CPython-specific strict incremental build investigation",
        "source_revision": abi3_environment["commit_sha"],
        "native_source_fingerprint_without_abi_feature": abi3_environment[
            "native_source_fingerprint_without_abi_feature"
        ],
        "environment": {
            field: abi3_environment.get(field)
            for field in (
                "python_version",
                "operating_system",
                "platform",
                "architecture",
                "processor",
                "benchmark_package_versions",
                "rustc_version",
                "cargo_version",
                "maturin_version",
            )
        },
        "core_distribution_version": abi3_environment["installed_distribution_version"],
        "native_distribution_version": abi3_environment["native_extension"]["distribution_version"],
        "builds": {
            "abi3": {
                "variant": "abi3",
                "pyo3_feature": "abi3-py310",
                "module_filename": abi3_environment["native_extension"]["module_filename"],
                "binary_sha256": abi3_environment["native_extension"]["binary_sha256"],
                "snapshot_date": abi3["date"],
            },
            "cpython_specific": {
                "variant": "cpython-specific",
                "pyo3_feature": "abi3-py310 omitted; extension-module retained",
                "module_filename": cpython_environment["native_extension"]["module_filename"],
                "binary_sha256": cpython_environment["native_extension"]["binary_sha256"],
                "snapshot_date": cpython["date"],
            },
        },
        "methodology": {
            "clock": abi3["methodology"]["clock"],
            "samples_per_case": abi3["methodology"]["samples_per_case"],
            "chunk_sizes_bytes": abi3["chunk_sizes_bytes"],
            "payload_sizes": abi3["sizes"],
            "comparison": "Both wheels were built locally from the same source revision, Rust files, Cargo.lock, compiler/toolchain, Python, and machine. The PyO3 abi3-py310 feature is the only source manifest difference.",
            "scope": "strict incremental public API and direct native result API only; Python fallback is excluded from ABI-mode deltas",
            "python_fallback_control": (
                "to detect timing-environment drift, Python fallback per-workload median differences are limited to "
                f"{_MAX_MEDIAN_CONTROL_DIFFERENCE:.0%} at the matrix median, "
                f"{_MAX_P90_CONTROL_DIFFERENCE:.0%} at p90, and "
                f"{_MAX_SINGLE_CONTROL_DIFFERENCE:.0%} maximum; this control is not part of ABI-mode deltas"
            ),
        },
        "python_fallback_timing_control": {
            "median_per_workload_difference_percent": statistics.median(
                control_differences.values()
            ),
            "p90_per_workload_difference_percent": sorted(control_differences.values())[
                max(0, math.ceil(0.9 * len(control_differences)) - 1)
            ],
            "max_per_workload_difference_percent": max(control_differences.values()),
            "compared_workload_count": len(control_differences),
            "maximum_median_difference_percent": _MAX_MEDIAN_CONTROL_DIFFERENCE * 100.0,
            "maximum_p90_difference_percent": _MAX_P90_CONTROL_DIFFERENCE * 100.0,
            "maximum_single_difference_percent": _MAX_SINGLE_CONTROL_DIFFERENCE * 100.0,
        },
        "summary": summary,
        "shape_summary": shape_summary,
        "cases": cases,
    }


def render_markdown(comparison: dict[str, Any]) -> str:
    environment = comparison["environment"]
    builds = comparison["builds"]
    summary = comparison["summary"]
    lines = [
        "# ABI3 Strict Incremental Build Investigation",
        "",
        f"Date: {comparison['date']}",
        "",
        "This is a development-only build comparison used to isolate PyO3 ABI mode on the recommended strict incremental workload. It does not replace the [published-release benchmark](incremental-benchmark.md), which measures the native 0.2.2 ABI3 wheel against the Python fallback.",
        "",
        "## Controlled build pair",
        "",
        f"- Source revision: `{comparison['source_revision']}` (clean working tree).",
        f"- Native Rust source fingerprint excluding the ABI feature: `{comparison['native_source_fingerprint_without_abi_feature']}`.",
        f"- Core/native package versions: `{comparison['core_distribution_version']}` / `{comparison['native_distribution_version']}`.",
        f"- Python/platform/processor: `{environment['python_version']}` / `{environment['platform']}` / `{environment['processor']}`.",
        f"- Toolchain: `{environment['rustc_version']}`, `{environment['cargo_version']}`, `{environment['maturin_version'] or 'maturin version unavailable'}`.",
        "- Benchmark library versions: "
        + ", ".join(
            f"`{name}={version or 'not installed'}`"
            for name, version in sorted(environment["benchmark_package_versions"].items())
        )
        + ".",
        f"- ABI3 wheel binary: `{builds['abi3']['module_filename']}`; SHA-256 `{builds['abi3']['binary_sha256']}`; PyO3 `abi3-py310` enabled.",
        f"- CPython-specific wheel binary: `{builds['cpython_specific']['module_filename']}`; SHA-256 `{builds['cpython_specific']['binary_sha256']}`; PyO3 `abi3-py310` omitted.",
        f"- {comparison['methodology']['comparison']}",
        "- Python fallback timing control: "
        f"median `{comparison['python_fallback_timing_control']['median_per_workload_difference_percent']:.1f}%`, "
        f"p90 `{comparison['python_fallback_timing_control']['p90_per_workload_difference_percent']:.1f}%`, "
        f"max `{comparison['python_fallback_timing_control']['max_per_workload_difference_percent']:.1f}%` "
        "(limits 15% / 30% / 50%).",
        "",
        "## ABI3 timing difference",
        "",
        "Values show the ABI3 build's elapsed time change relative to the CPython-specific build for the same shape and chunk size. Positive percentages mean ABI3 was slower; negative percentages mean it was faster.",
        "",
        "| Native path | Median ABI3 change | Cases ABI3 slower | Paired cases |",
        "| --- | ---: | ---: | ---: |",
    ]
    labels = {
        "streaming_json_parser_native_public": "Public `StreamingJsonParser`",
        "native_incremental_direct_result": "Direct `consume_and_poll_result`",
    }
    for name in _NATIVE_CASES:
        row = summary[name]
        lines.append(
            f"| {labels[name]} | {row['median_abi3_slowdown_percent']:+.1f}% | {row['abi3_slower_case_count']} | {row['paired_case_count']} |"
        )
    lines.extend(
        [
            "",
            "## Median ABI3 change by payload shape",
            "",
            "Positive values mean ABI3 was slower. These are medians across the chunk sizes available for each shape.",
            "",
            "| Shape | Public path | Direct native path | Paired chunk sizes |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in comparison["shape_summary"]:
        lines.append(
            f"| `{row['shape']}` | {row['public_median_abi3_slowdown_percent']:+.1f}% | "
            f"{row['direct_median_abi3_slowdown_percent']:+.1f}% | {row['paired_case_count']} |"
        )
    lines.extend(
        [
            "",
            "## Paired results",
            "",
            "Times are median elapsed milliseconds per complete stream. This table is limited to the two native strict paths; complete decoding, NDJSON extraction, structural finishers, and repair libraries are not included.",
            "",
            "| Shape | Payload bytes | Chunk bytes | Chunks | Public ABI3 ms | Public CPython ms | Change | Direct ABI3 ms | Direct CPython ms | Change |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for case in comparison["cases"]:
        results = {result["name"]: result for result in case["results"]}
        public = results["streaming_json_parser_native_public"]
        direct = results["native_incremental_direct_result"]
        lines.append(
            f"| `{case['shape']}` | {case['payload_size_bytes']:,} | {case['chunk_size_bytes']:,} | {case['chunk_count']:,} | "
            f"{public['abi3_median_seconds_per_stream'] * 1000:.3f} | {public['cpython_specific_median_seconds_per_stream'] * 1000:.3f} | {public['abi3_slowdown_percent']:+.1f}% | "
            f"{direct['abi3_median_seconds_per_stream'] * 1000:.3f} | {direct['cpython_specific_median_seconds_per_stream'] * 1000:.3f} | {direct['abi3_slowdown_percent']:+.1f}% |"
        )
    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "This comparison isolates ABI mode for one Python version, platform, compiler, and workload matrix. Use the release-wheel benchmark for current user-facing performance. A material change should be investigated with profiling before changing native packaging or parser code.",
        ]
    )
    return "\n".join(lines) + "\n"


def artifact_contents(comparison: dict[str, Any], output_dir: Path) -> dict[Path, str]:
    return {
        output_dir / "abi3-incremental-investigation.json": json.dumps(
            comparison, indent=2, sort_keys=True
        )
        + "\n",
        output_dir / "abi3-incremental-investigation.md": render_markdown(comparison),
    }


def verify_artifacts(output_dir: Path) -> list[str]:
    json_path = output_dir / "abi3-incremental-investigation.json"
    if not json_path.exists():
        return [f"missing:{json_path}"]
    try:
        comparison = json.loads(json_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid-json:{json_path}:{exc}"]
    mismatches = []
    for path, content in artifact_contents(comparison, output_dir.resolve()).items():
        if not path.exists() or path.read_text() != content:
            mismatches.append(f"stale-or-missing:{path}")
    if not comparison.get("cases") or comparison.get("benchmark") != "same-source ABI3 versus CPython-specific strict incremental build investigation":
        mismatches.append("invalid:build-comparison")
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abi3-json", type=Path)
    parser.add_argument("--cpython-json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DOCS_ROOT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        mismatches = verify_artifacts(args.output_dir)
        if mismatches:
            raise SystemExit("\n".join(mismatches))
        print("ABI3 build comparison artifacts match their JSON snapshot")
        return
    if args.abi3_json is None or args.cpython_json is None:
        parser.error("--abi3-json and --cpython-json are required unless --verify is used")
    comparison = build_comparison(
        json.loads(args.abi3_json.read_text()),
        json.loads(args.cpython_json.read_text()),
    )
    for path in artifact_contents(comparison, args.output_dir.resolve()):
        path.parent.mkdir(parents=True, exist_ok=True)
    for path, content in artifact_contents(comparison, args.output_dir.resolve()).items():
        path.write_text(content)
        print(path)


if __name__ == "__main__":
    main()
