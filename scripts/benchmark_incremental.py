#!/usr/bin/env python3
"""Measure and publish strict incremental parser performance by byte chunk size."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import sysconfig
import time
from html import escape
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
DOCS_ROOT = REPO_ROOT / "docs"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
_USE_INSTALLED_PACKAGE = os.environ.get("BENCHMARK_USE_INSTALLED_PACKAGE") == "1"
if not _USE_INSTALLED_PACKAGE and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import benchmark_partial_strategy_matrix as partial_matrix
import streaming_json_parser as project_module
import streaming_json_parser.high_performance_parser as high_performance_module
from streaming_json_parser import (
    ParseStatus,
    StreamingJsonParser,
)

_NATIVE = partial_matrix._partial.streaming_json_parser_native
_DEFAULT_SIZES = (8192,)
_DEFAULT_CHUNK_SIZES = (1, 8, 64, 256, 1024, 4096)
_SAMPLE_COUNT = 7
_MAX_REPETITIONS = 4096
_TARGET_BYTES_PER_SAMPLE = 16 * 1024
_TARGET_SECONDS_PER_SAMPLE = 0.01
_INVALID_PAYLOADS = (
    b'{"value":NaN}',
    b'{"value":01}',
    b'{"value":1,}',
    b'{"value":1} trailing',
)
_OVERFLOW_PAYLOAD = b'{"value":1e400}'
_BENCHMARK_DISTRIBUTIONS = {
    "ijson": "ijson",
    "msgspec": "msgspec",
    "orjson": "orjson",
    "simdjson": "pysimdjson",
    "ujson": "ujson",
    "rapidjson": "python-rapidjson",
    "pydantic-core": "pydantic-core",
    "jiter": "jiter",
    "jsonriver": "jsonriver",
    "partial-json-parser": "partial-json-parser",
    "partialjson": "partialjson",
    "json-repair": "json-repair",
    "untruncate-json": "untruncate-json",
}
_SHAPES: tuple[tuple[str, Callable[[int], str]], ...] = (
    ("flat_string_object", partial_matrix._flat_string_object),
    ("number_array", partial_matrix._number_array),
    ("string_array", partial_matrix._string_array),
    ("nested_records", partial_matrix._nested_records),
    ("unicode_object", partial_matrix._unicode_object),
    ("escape_heavy_object", partial_matrix._escape_heavy_object),
    ("root_number", partial_matrix._root_number),
    ("root_literal", partial_matrix._root_literal),
    ("root_string", partial_matrix._root_string),
)
_IMPLEMENTATIONS = (
    ("streaming_json_parser_native_public", "StreamingJsonParser (native backend)"),
    (
        "native_incremental_direct_result",
        "IncrementalJsonParser.consume_and_poll_result (native)",
    ),
    ("streaming_json_parser_python_fallback", "StreamingJsonParser (Python fallback)"),
)
_CHART_SHAPES = (
    "flat_string_object",
    "number_array",
    "nested_records",
    "unicode_object",
    "escape_heavy_object",
)
_CHART_COLORS = {
    "streaming_json_parser_native_public": "#2463a6",
    "native_incremental_direct_result": "#14836b",
    "streaming_json_parser_python_fallback": "#b75a12",
}


class _PythonFallbackParser(StreamingJsonParser):
    """Use the normal parser implementation while preventing native dispatch."""

    def _can_use_native_incremental(self) -> bool:
        return False


def _implementation_labels(native: dict[str, Any]) -> dict[str, str]:
    variant = native.get("build_variant")
    if variant == "abi3":
        public_label = "StreamingJsonParser (native ABI3)"
        direct_label = "IncrementalJsonParser result API (native ABI3)"
    elif variant == "cpython-specific":
        public_label = "StreamingJsonParser (native CPython-specific)"
        direct_label = "IncrementalJsonParser result API (native CPython-specific)"
    else:
        public_label = "StreamingJsonParser (native backend)"
        direct_label = "IncrementalJsonParser result API (native backend)"
    return {
        "streaming_json_parser_native_public": public_label,
        "native_incremental_direct_result": direct_label,
        "streaming_json_parser_python_fallback": "StreamingJsonParser (Python fallback)",
    }


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git_provenance() -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - source archive
        return {"commit_sha": None, "working_tree_dirty": None}
    return {"commit_sha": revision or None, "working_tree_dirty": bool(status.strip())}


def _processor() -> str:
    processor = platform.processor().strip()
    if processor and processor.lower() not in {
        "arm",
        "arm64",
        "aarch64",
        "x86_64",
        "amd64",
        "i386",
        "i686",
    }:
        return processor
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.stdout.strip():
                return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - platform-specific
            pass
    return processor or "unavailable"


def _command_version(command: str) -> str | None:
    if shutil.which(command) is None:
        return None
    try:
        return subprocess.run(
            [command, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - optional toolchain
        return None


def _native_source_fingerprint() -> str:
    native_root = REPO_ROOT / "rust_native"
    manifest_path = native_root / "Cargo.toml"
    manifest = manifest_path.read_text(encoding="utf-8").replace(
        ', "abi3-py310"', ""
    )
    digest = hashlib.sha256()
    for path, content in [
        (manifest_path, manifest.encode()),
        (native_root / "Cargo.lock", (native_root / "Cargo.lock").read_bytes()),
        *[(path, path.read_bytes()) for path in sorted((native_root / "src").rglob("*.rs"))],
    ]:
        digest.update(path.relative_to(native_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _native_metadata() -> dict[str, Any]:
    if _NATIVE is None:
        raise RuntimeError("strict incremental characterization requires the native package")
    native_binary_module = importlib.import_module(
        f"{_NATIVE.__name__}.streaming_json_parser_native"
    )
    native_path = Path(native_binary_module.__file__).resolve()
    filename = native_path.name
    is_abi3 = ".abi3." in filename
    if os.environ.get("BENCHMARK_NATIVE_BUILD_VARIANT"):
        variant = os.environ["BENCHMARK_NATIVE_BUILD_VARIANT"]
    elif is_abi3:
        variant = "abi3"
    elif sysconfig.get_config_var("EXT_SUFFIX") and filename.endswith(
        sysconfig.get_config_var("EXT_SUFFIX")
    ):
        variant = "cpython-specific"
    else:
        variant = "unknown"
    try:
        binary_sha256 = hashlib.sha256(native_path.read_bytes()).hexdigest()
    except OSError:  # pragma: no cover - unusual import loaders
        binary_sha256 = None
    return {
        "distribution_version": _version("streaming-json-parser-native"),
        "importable": True,
        "module_filename": filename,
        "abi3_binary": is_abi3,
        "build_variant": variant,
        "binary_sha256": binary_sha256,
    }


def _environment() -> dict[str, Any]:
    core_version = _version("streaming-json-parser")
    package_path = Path(project_module.__file__).resolve()
    if _USE_INSTALLED_PACKAGE:
        try:
            core_distribution = importlib.metadata.distribution("streaming-json-parser")
            expected_core_path = Path(
                core_distribution.locate_file("streaming_json_parser/__init__.py")
            ).resolve()
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(
                "BENCHMARK_USE_INSTALLED_PACKAGE=1 requires an installed core distribution"
            ) from exc
        if (
            core_version is None
            or SRC_ROOT in package_path.parents
            or package_path != expected_core_path
        ):
            raise RuntimeError(
                "BENCHMARK_USE_INSTALLED_PACKAGE=1 requires importing the core module "
                "from the installed distribution, not a source checkout"
            )
    try:
        native_distribution = importlib.metadata.distribution("streaming-json-parser-native")
        native_distribution_version = native_distribution.version
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "strict incremental characterization requires installed core and native distributions"
        ) from exc
    native = _native_metadata()
    if native["distribution_version"] != native_distribution_version:
        raise RuntimeError("native module and distribution metadata versions disagree")
    if _USE_INSTALLED_PACKAGE:
        native_binary_module = importlib.import_module(
            f"{_NATIVE.__name__}.streaming_json_parser_native"
        )
        native_binary_path = Path(native_binary_module.__file__).resolve()
        packaged_native_files = {
            Path(native_distribution.locate_file(entry)).resolve()
            for entry in (native_distribution.files or ())
        }
        if native_binary_path not in packaged_native_files:
            raise RuntimeError(
                "BENCHMARK_USE_INSTALLED_PACKAGE=1 requires the native module binary "
                "to belong to the installed native distribution"
            )
    return {
        **_git_provenance(),
        "package_version": project_module.__version__,
        "package_module_version": project_module.__version__,
        "installed_distribution_version": core_version,
        "package_source": "installed distribution" if _USE_INSTALLED_PACKAGE else "repository source tree",
        "python_version": platform.python_version(),
        "operating_system": platform.system(),
        "platform": platform.platform(),
        "architecture": platform.machine() or "unavailable",
        "processor": _processor(),
        "benchmark_package_versions": {
            name: _version(distribution)
            for name, distribution in _BENCHMARK_DISTRIBUTIONS.items()
        },
        "native_extension": native,
        "native_source_fingerprint_without_abi_feature": _native_source_fingerprint(),
        "rustc_version": _command_version("rustc"),
        "cargo_version": _command_version("cargo"),
        "maturin_version": _command_version("maturin"),
    }


def _byte_chunks(payload: bytes, chunk_size: int) -> list[bytes]:
    if chunk_size < 1:
        raise ValueError("chunk sizes must be positive")
    return [payload[offset : offset + chunk_size] for offset in range(0, len(payload), chunk_size)]


def _status_text(result: Any) -> str:
    status = getattr(result, "status", None)
    return str(getattr(status, "value", status)).lower()


def _inspect_partial_result(result: Any) -> None:
    status = _status_text(result)
    error = getattr(result, "error", None)
    value = getattr(result, "value", None)
    complete = bool(getattr(result, "complete", False))
    del value  # Reading the current partial value is part of the public streaming workload.
    if error is not None or status.endswith("invalid"):
        raise ValueError(error or "parser rejected valid JSON")
    if complete and not status.endswith("complete"):
        raise RuntimeError(f"parser reported complete with status {status!r}")


def _finish_result(result: Any) -> Any:
    _inspect_partial_result(result)
    if not bool(getattr(result, "complete", False)) or not _status_text(result).endswith("complete"):
        raise ValueError(f"parser did not finish a complete JSON value: {_status_text(result)}")
    return result.value


def _drive_public_parser(chunks: list[bytes]) -> Any:
    parser = StreamingJsonParser()
    for chunk in chunks:
        _inspect_partial_result(parser.feed(chunk))
    return _finish_result(parser.finish())


def _run_public_native(chunks: list[bytes]) -> Any:
    if _NATIVE is None:
        raise RuntimeError("native incremental backend is unavailable")
    parser = StreamingJsonParser()
    if not isinstance(parser, _NATIVE.IncrementalJsonParser):
        raise RuntimeError("StreamingJsonParser did not select the installed native backend")
    for chunk in chunks:
        _inspect_partial_result(parser.feed(chunk))
    return _finish_result(parser.finish())


def _run_native_direct_result(chunks: list[bytes]) -> Any:
    if _NATIVE is None:
        raise RuntimeError("native incremental backend is unavailable")
    parser = _NATIVE.IncrementalJsonParser()
    parser.configure_statuses(
        ParseStatus.EMPTY,
        ParseStatus.PARTIAL,
        ParseStatus.COMPLETE,
        ParseStatus.INVALID,
    )
    for chunk in chunks:
        _inspect_partial_result(parser.consume_and_poll_result(chunk))
    return _finish_result(parser.finish_result())


def _run_python_fallback(chunks: list[bytes]) -> Any:
    parser = _PythonFallbackParser()
    if _NATIVE is not None and isinstance(parser, _NATIVE.IncrementalJsonParser):
        raise RuntimeError("native backend remained active during Python fallback measurement")
    for chunk in chunks:
        _inspect_partial_result(parser.feed(chunk))
    return _finish_result(parser.finish())


def _implementation_functions(chunks: list[bytes]) -> tuple[tuple[str, Callable[[], Any]], ...]:
    return (
        ("streaming_json_parser_native_public", lambda: _run_public_native(chunks)),
        ("native_incremental_direct_result", lambda: _run_native_direct_result(chunks)),
        ("streaming_json_parser_python_fallback", lambda: _run_python_fallback(chunks)),
    )


def _accepts_valid(function: Callable[[], Any], reference: Any) -> bool:
    try:
        return function() == reference
    except Exception:
        return False


def _rejects_invalid(function: Callable[[list[bytes]], Any], chunk_size: int) -> bool:
    for payload in _INVALID_PAYLOADS:
        try:
            value = function(_byte_chunks(payload, min(chunk_size, max(1, len(payload) - 1))))
        except Exception:
            continue
        else:
            del value
            return False
    return True


def _overflow_behavior() -> dict[str, Any]:
    chunks = _byte_chunks(_OVERFLOW_PAYLOAD, 1)
    behavior = {}
    for name, runner in (
        ("streaming_json_parser_native_public", _run_public_native),
        ("native_incremental_direct_result", _run_native_direct_result),
        ("streaming_json_parser_python_fallback", _run_python_fallback),
    ):
        try:
            value = runner(chunks)
        except Exception as exc:
            behavior[name] = {"outcome": "rejected", "error_type": type(exc).__name__}
        else:
            overflow_value = value.get("value") if isinstance(value, dict) else value
            description = (
                "non-finite float"
                if isinstance(overflow_value, float) and not math.isfinite(overflow_value)
                else type(overflow_value).__name__
            )
            behavior[name] = {"outcome": "accepted", "decoded_value": description}
    return behavior


def _measure(
    function: Callable[[], Any],
    payload_bytes: int,
    samples: int = _SAMPLE_COUNT,
) -> tuple[float, list[float], list[int]]:
    repetitions = max(
        1,
        min(_MAX_REPETITIONS, _TARGET_BYTES_PER_SAMPLE // max(1, payload_bytes)),
    )
    function()  # One untimed warm-up complete stream.
    sample_seconds: list[float] = []
    repetitions_per_sample: list[int] = []
    for _ in range(samples):
        batch_repetitions = repetitions
        while True:
            started = time.perf_counter()
            for _ in range(batch_repetitions):
                function()
            elapsed = time.perf_counter() - started
            if elapsed > 0 and (
                elapsed >= _TARGET_SECONDS_PER_SAMPLE
                or batch_repetitions >= _MAX_REPETITIONS
            ):
                sample_seconds.append(elapsed / batch_repetitions)
                repetitions_per_sample.append(batch_repetitions)
                break
            if batch_repetitions >= _MAX_REPETITIONS:
                raise RuntimeError("performance clock returned zero elapsed time for a benchmark batch")
            if elapsed > 0:
                target_repetitions = math.ceil(
                    batch_repetitions * _TARGET_SECONDS_PER_SAMPLE / elapsed
                )
                batch_repetitions = min(
                    _MAX_REPETITIONS,
                    max(batch_repetitions * 2, target_repetitions),
                )
            else:
                batch_repetitions = min(_MAX_REPETITIONS, batch_repetitions * 2)
    return statistics.median(sample_seconds), sample_seconds, repetitions_per_sample


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    public_speedups: list[float] = []
    direct_speedups: list[float] = []
    public_faster = 0
    paired_cases = 0
    for case in cases:
        results = {result["name"]: result for result in case["results"]}
        public = results.get("streaming_json_parser_native_public")
        direct = results.get("native_incremental_direct_result")
        python = results.get("streaming_json_parser_python_fallback")
        if not all(result and result["valid"] for result in (public, direct, python)):
            continue
        paired_cases += 1
        public_speedups.append(python["median_seconds_per_stream"] / public["median_seconds_per_stream"])
        direct_speedups.append(python["median_seconds_per_stream"] / direct["median_seconds_per_stream"])
        public_faster += public["median_seconds_per_stream"] < python["median_seconds_per_stream"]
    return {
        "paired_case_count": paired_cases,
        "native_public_median_speedup_vs_python": statistics.median(public_speedups) if public_speedups else None,
        "native_direct_median_speedup_vs_python": statistics.median(direct_speedups) if direct_speedups else None,
        "native_public_faster_case_count": public_faster,
        "native_public_not_faster_case_count": paired_cases - public_faster,
        "speedup_definition": "Python fallback median elapsed time divided by native median elapsed time; values above 1 mean native is faster",
    }


def collect_snapshot(
    *,
    sizes: tuple[int, ...] = _DEFAULT_SIZES,
    chunk_sizes: tuple[int, ...] = _DEFAULT_CHUNK_SIZES,
    samples: int = _SAMPLE_COUNT,
) -> dict[str, Any]:
    """Run comparable strict incremental workloads using fixed-width UTF-8 byte chunks."""
    if samples < 1:
        raise ValueError("samples must be positive")
    if any(size < 1 for size in sizes) or any(size < 1 for size in chunk_sizes):
        raise ValueError("payload sizes and chunk sizes must be positive")
    environment = _environment()
    implementation_labels = _implementation_labels(environment["native_extension"])
    native_type = _NATIVE.IncrementalJsonParser if _NATIVE is not None else None
    if native_type is None:
        raise RuntimeError("strict incremental characterization requires IncrementalJsonParser")
    if not high_performance_module._NATIVE_PUBLIC_AVAILABLE:
        raise RuntimeError("installed native extension does not expose the public incremental API")

    cases: list[dict[str, Any]] = []
    for shape, factory in _SHAPES:
        for requested_size in sizes:
            payload = factory(requested_size).encode("utf-8")
            reference = json.loads(payload)
            # Keep this focused on an arriving multi-chunk stream, not complete-input decoding.
            for chunk_size in chunk_sizes:
                if chunk_size >= len(payload):
                    continue
                chunks = _byte_chunks(payload, chunk_size)
                functions = _implementation_functions(chunks)
                results: list[dict[str, Any]] = []
                for name, function in functions:
                    valid = _accepts_valid(function, reference)
                    if not valid:
                        results.append(
                            {
                                "name": name,
                                "display_name": implementation_labels[name],
                                "semantics_family": "strict_incremental",
                                "valid": False,
                                "reason": "failed the valid complete-stream reference check",
                            }
                        )
                        continue
                    runner = {
                        "streaming_json_parser_native_public": _run_public_native,
                        "native_incremental_direct_result": _run_native_direct_result,
                        "streaming_json_parser_python_fallback": _run_python_fallback,
                    }[name]
                    if not _rejects_invalid(runner, chunk_size):
                        results.append(
                            {
                                "name": name,
                                "display_name": implementation_labels[name],
                                "semantics_family": "strict_incremental",
                                "valid": False,
                                "reason": "failed the strict invalid-input compatibility gate",
                            }
                        )
                        continue
                    median_seconds, sample_seconds, repetition_counts = _measure(
                        function,
                        payload_bytes=len(payload),
                        samples=samples,
                    )
                    results.append(
                        {
                            "name": name,
                            "display_name": implementation_labels[name],
                            "semantics_family": "strict_incremental",
                            "valid": True,
                            "median_seconds_per_stream": median_seconds,
                            "sample_seconds_per_stream": sample_seconds,
                            "measurement_repetitions_per_sample": repetition_counts,
                            "reason": None,
                        }
                    )
                cases.append(
                    {
                        "shape": shape,
                        "requested_size": requested_size,
                        "payload_size_bytes": len(payload),
                        "chunk_size_bytes": chunk_size,
                        "chunk_count": len(chunks),
                        "input_representation": "UTF-8 bytes sliced at exact byte boundaries",
                        "semantics_family": "strict_incremental",
                        "sample_count": samples,
                        "results": results,
                    }
                )
    return {
        "date": time.strftime("%Y-%m-%d"),
        "benchmark": "strict incremental JSON parser by byte chunk size",
        "semantics_family": "strict_incremental",
        "environment": environment,
        "methodology": {
            "command": os.environ.get(
                "BENCHMARK_ARTIFACT_COMMAND",
                (
                    "BENCHMARK_USE_INSTALLED_PACKAGE=1 make benchmark-release-artifacts "
                    "COMMUNITY_JSON_CORPUS_DIR=/path/to/json_benchmark/data"
                    if _USE_INSTALLED_PACKAGE
                    else "make benchmark-incremental"
                ),
            ),
            "clock": "time.perf_counter",
            "metric": "median elapsed seconds per complete parser lifecycle",
            "aggregation": f"median per-stream elapsed time across {samples} measured batches",
            "samples_per_case": samples,
            "warmup_full_streams_per_case": 1,
            "timing_scope": "parser construction, every delta-chunk feed/consume-and-poll call, inspection of each partial status/value/error, and finalization; payload construction and reference JSON decoding are outside timing",
            "chunking": "UTF-8 serialized payloads are sliced as bytes at exact requested byte widths; cases with fewer than two chunks are omitted",
            "measurement_resolution": (
                "batches target at least 10 ms elapsed when possible; repetitions grow based on observed duration, "
                "up to 4096 full streams, and zero-duration batches are retried"
            ),
            "comparison": "all three adapters must produce the same complete Python value and reject NaN, leading-zero numbers, trailing commas, and trailing data",
            "numeric_overflow_note": "1e400 is valid JSON number syntax but exceeds finite Python float range; backend numeric-range behavior is recorded separately",
            "semantic_scope": "strict incremental only; complete decoding, cumulative-prefix reparsing, structural finishers, and permissive repair libraries are excluded",
        },
        "sizes": list(sizes),
        "chunk_sizes_bytes": list(chunk_sizes),
        "implementations": [
            {"name": name, "display_name": implementation_labels[name], "semantics_family": "strict_incremental"}
            for name, _label in _IMPLEMENTATIONS
        ],
        "summary": _summary(cases),
        "numeric_overflow_behavior": _overflow_behavior(),
        "cases": cases,
    }


def _seconds_ms(value: float | None) -> str:
    return "—" if value is None else f"{value * 1000:.3f}"


def render_markdown(snapshot: dict[str, Any]) -> str:
    environment = snapshot["environment"]
    native = environment["native_extension"]
    methodology = snapshot["methodology"]
    summary = snapshot["summary"]
    speedup = summary.get("native_public_median_speedup_vs_python")
    speedup_text = "unavailable" if speedup is None else f"{speedup:.2f}×"
    lines = [
        "# Strict Incremental Parser Benchmark",
        "",
        f"Date: {snapshot['date']}",
        "",
        "This benchmark measures strict incremental parsing as UTF-8 bytes arrive in fixed-width chunks. Every chunk is fed and its partial status/value/error is inspected before the next chunk; the stream is finalized after the last chunk. All rows are in the same strict incremental semantic family.",
        "",
        "## Provenance",
        "",
        f"- Core package: `{environment['package_version']}` ({environment['package_source']}; installed metadata `{environment.get('installed_distribution_version') or 'not installed'}`)",
        f"- Source revision: `{environment.get('commit_sha') or 'unavailable'}`; working tree dirty: `{environment.get('working_tree_dirty')}`",
        f"- Native package: `{native.get('distribution_version') or 'not installed'}`; build variant: `{native.get('build_variant')}`; ABI3 binary: `{native.get('abi3_binary')}`",
        f"- Native module file: `{native.get('module_filename')}`; SHA-256: `{native.get('binary_sha256') or 'unavailable'}`",
        f"- Python/platform: `{environment['python_version']}` / `{environment['platform']}`; processor: `{environment['processor']}`",
        f"- Rust compiler: `{environment.get('rustc_version') or 'unavailable'}`",
        "- Benchmark toolchain libraries: "
        + ", ".join(
            f"`{name}={version or 'not installed'}`"
            for name, version in sorted(environment["benchmark_package_versions"].items())
        ),
        f"- Native source fingerprint (excluding only the PyO3 ABI feature): `{environment['native_source_fingerprint_without_abi_feature']}`",
        "",
        "## Methodology",
        "",
        f"- Clock: `{methodology['clock']}`; {methodology['aggregation']}.",
        f"- Timed lifecycle: {methodology['timing_scope']}.",
        f"- Chunking: {methodology['chunking']}.",
        f"- Correctness: {methodology['comparison']}.",
        f"- Scope: {methodology['semantic_scope']}.",
        "- Each timing is per complete stream, including parser construction and finalization; lower is better.",
        "",
        "## Summary",
        "",
        f"- Paired shape/chunk cases: {summary['paired_case_count']}.",
        f"- Median native public speedup vs Python fallback: `{speedup_text}` (Python elapsed time divided by native elapsed time; above 1 means native is faster).",
        f"- Cases where native public was faster: {summary['native_public_faster_case_count']}; not faster (slower or tied): {summary['native_public_not_faster_case_count']}.",
        "",
        "## Numeric overflow edge case",
        "",
        f"`1e400` has valid JSON number syntax but exceeds finite Python float range. Its untimed behavior is recorded separately: `{json.dumps(snapshot['numeric_overflow_behavior'], sort_keys=True)}`. This input is not included in performance timings.",
        "",
        "## Results",
        "",
        "Times are median elapsed milliseconds per complete stream. `direct native` uses `IncrementalJsonParser.consume_and_poll_result` directly; it is an implementation reference, not a separate public recommendation.",
        "",
        "| Payload shape | Payload bytes | Chunk bytes | Chunks | Public native ms | Direct native ms | Python fallback ms | Native/Python speedup |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in snapshot["cases"]:
        values = {result["name"]: result for result in case["results"]}
        public = values.get("streaming_json_parser_native_public", {})
        direct = values.get("native_incremental_direct_result", {})
        python = values.get("streaming_json_parser_python_fallback", {})
        public_seconds = public.get("median_seconds_per_stream")
        python_seconds = python.get("median_seconds_per_stream")
        ratio = (
            f"{python_seconds / public_seconds:.2f}×"
            if public_seconds and python_seconds
            else "—"
        )
        lines.append(
            f"| `{case['shape']}` | {case['payload_size_bytes']:,} | {case['chunk_size_bytes']:,} | {case['chunk_count']:,} | "
            f"{_seconds_ms(public_seconds)} | {_seconds_ms(direct.get('median_seconds_per_stream'))} | "
            f"{_seconds_ms(python_seconds)} | {ratio} |"
        )
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "The release benchmark target generates this artifact alongside the core and community benchmark snapshots from a clean checkout with the installed core and native release distributions.",
            "",
            f"Command: `{methodology['command']}`",
            "",
            "This artifact describes the installed native build. The separate [same-source ABI comparison](abi3-incremental-investigation.md) is a local build investigation and does not replace these release-wheel measurements.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_chart(snapshot: dict[str, Any]) -> str:
    width = 1440
    panel_height = 260
    height = 160 + panel_height * len(_CHART_SHAPES)
    left = 190
    plot_width = 1170
    chart_top = 36
    chart_height = 150
    implementation_labels = {
        "streaming_json_parser_native_public": f"Public {snapshot['implementations'][0]['display_name']}",
        "native_incremental_direct_result": f"Direct {snapshot['implementations'][1]['display_name']}",
        "streaming_json_parser_python_fallback": "StreamingJsonParser (Python fallback)",
    }
    build_variant = snapshot["environment"]["native_extension"].get("build_variant")
    native_description = {
        "abi3": "native ABI3 parser",
        "cpython-specific": "native CPython-specific parser",
    }.get(build_variant, "native parser")
    chunks_by_shape: dict[str, list[dict[str, Any]]] = {
        shape: [case for case in snapshot["cases"] if case["shape"] == shape]
        for shape in _CHART_SHAPES
    }
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-description">',
        '<title id="chart-title">Strict incremental parser latency by chunk size</title>',
        f'<desc id="chart-description">Grouped bars compare complete-stream elapsed milliseconds for the public {escape(native_description)}, direct native result API, and Python fallback across five payload shapes. Lower is better. Each panel has its own vertical scale.</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="36" y="34" fill="#172033" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="25" font-weight="700">Strict incremental parsing by chunk size</text>',
        '<text x="36" y="61" fill="#44505e" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="14">Median elapsed milliseconds per complete stream · exact UTF-8 byte chunks · lower is better</text>',
    ]
    legend_x = left
    for index, (name, label) in enumerate(implementation_labels.items()):
        x = legend_x + index * 380
        parts.append(f'<rect x="{x}" y="78" width="15" height="15" rx="2" fill="{_CHART_COLORS[name]}"/>')
        parts.append(
            f'<text x="{x + 23}" y="91" fill="#243244" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="13">{escape(label)}</text>'
        )

    for panel_index, shape in enumerate(_CHART_SHAPES):
        panel_y = chart_top + 90 + panel_index * panel_height
        cases = sorted(chunks_by_shape[shape], key=lambda case: case["chunk_size_bytes"])
        if not cases:
            continue
        values_by_case = []
        for case in cases:
            values_by_case.append(
                {
                    result["name"]: result.get("median_seconds_per_stream")
                    for result in case["results"]
                    if result.get("valid")
                }
            )
        max_ms = max(
            (
                value * 1000
                for row in values_by_case
                for value in row.values()
                if value is not None
            ),
            default=1.0,
        )
        max_ms = max(max_ms, 0.001)
        parts.append(
            f'<text x="36" y="{panel_y + 20}" fill="#172033" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="18" font-weight="650">{escape(shape.replace("_", " "))}</text>'
        )
        for grid_index in range(4):
            fraction = grid_index / 3
            y = panel_y + chart_top + chart_height - fraction * chart_height
            label = max_ms * fraction
            parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="#d8dee8" stroke-width="1"/>')
            parts.append(
                f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" fill="#667085" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="11">{label:.2f}</text>'
            )
        group_width = plot_width / len(cases)
        bar_width = min(21.0, group_width / 5)
        for case_index, (case, row) in enumerate(zip(cases, values_by_case)):
            center = left + group_width * (case_index + 0.5)
            offsets = (-bar_width - 2, 0, bar_width + 2)
            for implementation_index, (name, _label) in enumerate(_IMPLEMENTATIONS):
                seconds = row.get(name)
                if seconds is None:
                    continue
                milliseconds = seconds * 1000
                bar_height = chart_height * milliseconds / max_ms
                x = center + offsets[implementation_index] - bar_width / 2
                y = panel_y + chart_top + chart_height - bar_height
                parts.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{max(0.5, bar_height):.1f}" rx="2" fill="{_CHART_COLORS[name]}"><title>{escape(implementation_labels[name])}: {milliseconds:.3f} ms, {case["chunk_size_bytes"]} byte chunks</title></rect>'
                )
            parts.append(
                f'<text x="{center:.1f}" y="{panel_y + chart_top + chart_height + 20}" text-anchor="middle" fill="#44505e" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="11">{case["chunk_size_bytes"]:,}</text>'
            )
        parts.append(
            f'<text x="{left + plot_width / 2:.1f}" y="{panel_y + chart_top + chart_height + 42}" text-anchor="middle" fill="#667085" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="11">Chunk size in bytes · panel maximum {max_ms:.3f} ms</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def artifact_contents(snapshot: dict[str, Any], output_dir: Path) -> dict[Path, str]:
    return {
        output_dir / "incremental-benchmark.json": json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        output_dir / "incremental-benchmark.md": render_markdown(snapshot),
        output_dir / "assets" / "benchmarks" / "incremental-chunk-size.svg": render_chart(snapshot),
    }


def write_artifacts(snapshot: dict[str, Any], output_dir: Path) -> list[Path]:
    contents = artifact_contents(snapshot, output_dir.resolve())
    for path, content in contents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return list(contents)


def verify_artifacts(output_dir: Path) -> list[str]:
    json_path = output_dir / "incremental-benchmark.json"
    if not json_path.exists():
        return [f"missing:{json_path}"]
    try:
        snapshot = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid-json:{json_path}:{exc}"]
    mismatches = []
    for path, expected in artifact_contents(snapshot, output_dir.resolve()).items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            mismatches.append(f"stale-or-missing:{path}")
    if snapshot.get("semantics_family") != "strict_incremental":
        mismatches.append("invalid:semantic-family")
    if snapshot.get("methodology", {}).get("clock") != "time.perf_counter":
        mismatches.append("invalid:clock")
    if "cumulative-prefix" not in snapshot.get("methodology", {}).get("semantic_scope", ""):
        mismatches.append("invalid:semantic-scope")
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(_DEFAULT_SIZES))
    parser.add_argument("--chunks", type=int, nargs="+", default=list(_DEFAULT_CHUNK_SIZES))
    parser.add_argument("--samples", type=int, default=_SAMPLE_COUNT)
    parser.add_argument("--output-dir", type=Path, default=DOCS_ROOT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        mismatches = verify_artifacts(args.output_dir)
        if mismatches:
            raise SystemExit("\n".join(mismatches))
        print("strict incremental benchmark artifacts match their JSON snapshot")
        return
    command = os.environ.get("BENCHMARK_ARTIFACT_COMMAND")
    if command:
        os.environ["BENCHMARK_ARTIFACT_COMMAND"] = command
    snapshot = collect_snapshot(
        sizes=tuple(args.sizes),
        chunk_sizes=tuple(args.chunks),
        samples=args.samples,
    )
    paths = write_artifacts(snapshot, args.output_dir)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
