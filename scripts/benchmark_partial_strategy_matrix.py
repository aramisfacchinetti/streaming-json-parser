#!/usr/bin/env python3
"""Measure partial-parser strategies across payload shapes and chunk sizes."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
_USE_INSTALLED_PACKAGE = os.environ.get("BENCHMARK_USE_INSTALLED_PACKAGE") == "1"
if not _USE_INSTALLED_PACKAGE:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

from streaming_json_parser import ParseStatus


def _load_partial_benchmark() -> Any:
    path = Path(__file__).with_name("benchmark_partial_parser.py")
    spec = importlib.util.spec_from_file_location("partial_benchmark_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_partial = _load_partial_benchmark()


PayloadFactory = Callable[[int], str]
InputChunk = str | bytes | bytearray
CaseFunction = Callable[[], Any]
_STRICT_INVALID_PAYLOADS = (
    '{"value":NaN}',
    '{"value":01}',
    '{"value":1e400}',
    '{"value":1,}',
    '{"value":1} trailing',
)
_MEASUREMENT_WORK_TARGET = 50_000
_MAX_INNER_REPETITIONS = 32
_PUBLIC_STRICT_INCREMENTAL = frozenset(
    {
        "facade_incremental",
        "facade_consume_poll",
        "native_incremental_public_result",
    }
)


def _flat_string_object(size: int) -> str:
    return json.dumps({"data": "x" * size}, separators=(",", ":"))


def _number_array(size: int) -> str:
    return json.dumps(list(range(max(1, size // 3))), separators=(",", ":"))


def _string_array(size: int) -> str:
    return json.dumps(
        ["x" * 16 for _ in range(max(1, size // 20))],
        separators=(",", ":"),
    )


def _nested_records(size: int) -> str:
    rows = [
        {"id": index, "value": "x" * 16}
        for index in range(max(1, size // 36))
    ]
    return json.dumps({"rows": rows}, separators=(",", ":"))


def _unicode_object(size: int) -> str:
    return json.dumps(
        {"data": "hé🙂" * max(1, size // 5)},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _escape_heavy_object(size: int) -> str:
    return json.dumps(
        {"data": "\n\t\"\\" * max(1, size // 5)},
        separators=(",", ":"),
    )


def _root_number(size: int) -> str:
    return str(max(1, size))


def _root_literal(size: int) -> str:
    del size
    return "true"


def _root_string(size: int) -> str:
    return json.dumps("x" * max(1, size // 4), separators=(",", ":"))


def _chunks(payload: str, chunk_size: int, input_kind: str = "str") -> list[InputChunk]:
    chunks = [
        payload[offset : offset + chunk_size]
        for offset in range(0, len(payload), chunk_size)
    ]
    if input_kind == "str":
        return chunks
    if input_kind == "bytes":
        return [chunk.encode("utf-8") for chunk in chunks]
    if input_kind == "bytearray":
        return [bytearray(chunk.encode("utf-8")) for chunk in chunks]
    raise ValueError(f"unsupported input kind: {input_kind}")


def _prefixes(payload: str, chunk_size: int, input_kind: str = "str") -> list[InputChunk]:
    prefixes = [
        payload[: min(offset + chunk_size, len(payload))]
        for offset in range(0, len(payload), chunk_size)
    ]
    if input_kind == "str":
        return prefixes
    if input_kind == "bytes":
        return [prefix.encode("utf-8") for prefix in prefixes]
    if input_kind == "bytearray":
        return [bytearray(prefix.encode("utf-8")) for prefix in prefixes]
    raise ValueError(f"unsupported input kind: {input_kind}")


def _run_facade_snapshots(chunks: list[InputChunk]) -> Any:
    parser = _partial.StreamingJsonParser()
    for chunk in chunks:
        parser.feed(chunk)
    return parser.finish().value


def _run_facade_consume_poll(chunks: list[InputChunk]) -> Any:
    parser = _partial.StreamingJsonParser()
    for chunk in chunks:
        parser.consume(chunk)
        parser.poll()
    return parser.finish().value


def _run_native_incremental(chunks: list[InputChunk]) -> Any:
    native = _partial.streaming_json_parser_native
    if native is None:
        raise RuntimeError("native incremental backend is unavailable")
    parser = native.IncrementalJsonParser()
    value = None
    for chunk in chunks:
        _status, value, error = parser.consume_and_poll(chunk)
        if error is not None:
            raise ValueError(error)
    _status, value, error = parser.finish()
    if error is not None:
        raise ValueError(error)
    return value


def _run_native_incremental_public_result(chunks: list[InputChunk]) -> Any:
    native = _partial.streaming_json_parser_native
    if native is None:
        raise RuntimeError("native incremental backend is unavailable")
    parser = native.IncrementalJsonParser()
    parser.configure_statuses(
        ParseStatus.EMPTY,
        ParseStatus.PARTIAL,
        ParseStatus.COMPLETE,
        ParseStatus.INVALID,
    )
    for chunk in chunks:
        result = parser.consume_and_poll_result(chunk)
        if result.error is not None:
            raise ValueError(result.error)
    result = parser.finish_result()
    if result.error is not None:
        raise ValueError(result.error)
    return result.value


def _run_structural_snapshots(chunks: list[InputChunk], partial_mode: str = "structural") -> Any:
    parser = _partial.StreamingJsonParser(partial_mode=partial_mode)
    for chunk in chunks:
        parser.feed(chunk, copy_value=False)
    return parser.finish(copy_value=False).value


def _run_jsonriver(chunks: list[str]) -> Any:
    return _partial._run_jsonriver(chunks)


def _reject_non_finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    if isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
    elif isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)
    return value


def _run_jsonriver_strict(chunks: list[str]) -> Any:
    return _reject_non_finite(_run_jsonriver(chunks))


def _run_ijson_event_driven(chunks: list[InputChunk]) -> Any:
    return _partial._run_ijson_event_driven(chunks)


def _jsonriver_is_strict(chunk_size: int) -> bool:
    for invalid_payload in _STRICT_INVALID_PAYLOADS:
        try:
            _run_jsonriver_strict(_chunks(invalid_payload, chunk_size))
        except Exception:
            continue
        return False
    return True


def _ijson_is_strict(input_kind: str, chunk_size: int) -> bool:
    for invalid_payload in _STRICT_INVALID_PAYLOADS:
        try:
            _run_ijson_event_driven(_chunks(invalid_payload, chunk_size, input_kind))
        except Exception:
            continue
        return False
    return True


def _measure(
    function: CaseFunction,
    repeats: int,
    work_units: int,
) -> tuple[float, int]:
    repetitions = max(
        1,
        min(
            _MAX_INNER_REPETITIONS,
            _MEASUREMENT_WORK_TARGET // max(1, work_units),
        ),
    )
    function()
    samples = []
    for _ in range(max(1, repeats)):
        started = time.process_time()
        for _ in range(repetitions):
            function()
        samples.append((time.process_time() - started) / repetitions)
    return statistics.median(samples), repetitions


def _case_functions(
    chunks: list[InputChunk],
    prefixes: list[InputChunk],
    *,
    include_cumulative_finishers: bool,
    input_kind: str,
) -> list[tuple[str, str, CaseFunction]]:
    cases: list[tuple[str, str, CaseFunction]] = [
        ("facade_incremental", "strict_incremental", lambda: _run_facade_snapshots(chunks)),
        (
            "facade_consume_poll",
            "strict_incremental",
            lambda: _run_facade_consume_poll(chunks),
        ),
    ]
    if _partial.streaming_json_parser_native is not None:
        cases.append(
            (
                "native_incremental_direct",
                "strict_incremental",
                lambda: _run_native_incremental(chunks),
            )
        )
        cases.append(
            (
                "native_incremental_public_result",
                "strict_incremental",
                lambda: _run_native_incremental_public_result(chunks),
            )
        )
    if input_kind == "str" and _partial.jsonriver is not None:
        cases.append(
            (
                "jsonriver_event_driven",
                "event_driven_partial",
                lambda: _run_jsonriver_strict(chunks),
            )
        )
    if _partial._ijson_yajl2_c is not None:
        cases.append(
            (
                "ijson_yajl2_c_event_driven",
                "event_driven_partial",
                lambda: _run_ijson_event_driven(chunks),
            )
        )
    if include_cumulative_finishers and _partial.pydantic_core_from_json is not None:
        representative_prefix = (
            prefixes[-2]
            if len(prefixes) > 1
            else (prefixes[0] if prefixes else None)
        )
        tuned_structural_decoder = _partial.make_tuned_structural_partial_decoder(
            sample=representative_prefix,
        )
        cases.append(
            (
                "facade_structural_function_finisher",
                "structural_finisher",
                lambda: [tuned_structural_decoder(prefix) for prefix in prefixes],
            )
        )
        cases.append(
            (
                "facade_structural_one_shot_finisher",
                "structural_finisher",
                lambda: [
                    _partial.decode_structural_partial_json(prefix)
                    for prefix in prefixes
                ],
            )
        )
        if _partial._PYDANTIC_CORE_TRAILING_STRINGS:
            tuned_trailing_decoder = _partial.make_tuned_structural_partial_decoder(
                sample=representative_prefix,
                trailing_strings=True,
            )
            cases.append(
                (
                    "facade_structural_trailing_function_finisher",
                    "structural_trailing_finisher",
                    lambda: [tuned_trailing_decoder(prefix) for prefix in prefixes],
                )
            )
            cases.append(
                (
                    "facade_structural_trailing_one_shot_finisher",
                    "structural_trailing_finisher",
                    lambda: [
                        _partial.decode_structural_partial_json(
                            prefix,
                            trailing_strings=True,
                        )
                        for prefix in prefixes
                    ],
                )
            )
        cases.append(
            (
                "facade_structural_finisher",
                "structural_finisher",
                lambda: _run_structural_snapshots(chunks),
            )
        )
        if _partial._PYDANTIC_CORE_TRAILING_STRINGS:
            cases.append(
                (
                    "facade_structural_trailing_finisher",
                    "structural_trailing_finisher",
                    lambda: _run_structural_snapshots(chunks, "structural_trailing_strings"),
                )
            )
        cases.append(
            (
                "pydantic_core_partial_finisher",
                "structural_finisher",
                lambda: _partial._run_pydantic_core(prefixes),
            )
        )
        if _partial._PYDANTIC_CORE_TRAILING_STRINGS:
            cases.append(
                (
                    "pydantic_core_trailing_strings_finisher",
                    "structural_trailing_finisher",
                    lambda: _partial._run_pydantic_core_trailing_strings(prefixes),
                )
            )
    if include_cumulative_finishers and _partial.jiter is not None:
        cases.extend(
            [
                (
                    "jiter_partial_finisher",
                    "structural_finisher",
                    lambda: _partial._run_jiter(prefixes, True),
                ),
                (
                    "jiter_trailing_strings_finisher",
                    "structural_trailing_finisher",
                    lambda: _partial._run_jiter(prefixes, "trailing-strings"),
                ),
            ]
        )
    if input_kind == "str" and include_cumulative_finishers and _partial.PartialJsonParser is not None:
        cases.append(
            (
                "partialjson_cumulative_reparse",
                "permissive_recovery",
                lambda: _partial._run_partialjson(prefixes),
            )
        )
    if input_kind == "str" and include_cumulative_finishers and _partial.partial_json_loads is not None:
        cases.append(
            (
                "partial_json_parser_cumulative_reparse",
                "permissive_recovery",
                lambda: _partial._run_partial_json_parser(prefixes),
            )
        )
    if input_kind == "str" and include_cumulative_finishers and _partial.repair_json is not None:
        cases.append(
            (
                "json_repair_cumulative_reparse",
                "permissive_recovery",
                lambda: _partial._run_json_repair(prefixes),
            )
        )
    if input_kind == "str" and include_cumulative_finishers and _partial.untruncate_json is not None:
        cases.append(
            (
                "untruncate_json_cumulative_reparse",
                "permissive_recovery",
                lambda: _partial._run_untruncate(prefixes),
            )
        )
    return cases


def _winner(
    results: list[dict[str, Any]],
    family: str,
    names: frozenset[str] | None = None,
) -> str | None:
    comparable = [
        result
        for result in results
        if result["valid"]
        and result["family"] == family
        and (names is None or result["name"] in names)
    ]
    if not comparable:
        return None
    return min(comparable, key=lambda result: result["seconds"])["name"]


def collect_matrix(
    sizes: tuple[int, ...],
    chunk_sizes: tuple[int, ...],
    *,
    repeats: int,
    max_cumulative_work: int = 250_000,
    input_kinds: tuple[str, ...] = ("str", "bytes", "bytearray"),
) -> dict[str, Any]:
    factories: tuple[tuple[str, PayloadFactory], ...] = (
        ("flat_string_object", _flat_string_object),
        ("number_array", _number_array),
        ("string_array", _string_array),
        ("nested_records", _nested_records),
        ("unicode_object", _unicode_object),
        ("escape_heavy_object", _escape_heavy_object),
        ("root_number", _root_number),
        ("root_literal", _root_literal),
        ("root_string", _root_string),
    )
    cases: list[dict[str, Any]] = []
    jsonriver_strict_by_chunk = {
        chunk_size: _jsonriver_is_strict(chunk_size)
        if _partial.jsonriver is not None
        else False
        for chunk_size in chunk_sizes
    }
    ijson_strict_by_case = {
        (input_kind, chunk_size): _ijson_is_strict(input_kind, chunk_size)
        if _partial._ijson_yajl2_c is not None
        else False
        for input_kind in input_kinds
        for chunk_size in chunk_sizes
    }
    invalid_input_kinds = set(input_kinds) - {"str", "bytes", "bytearray"}
    if invalid_input_kinds:
        raise ValueError(f"unsupported input kinds: {sorted(invalid_input_kinds)}")
    for shape, factory in factories:
        for requested_size in sizes:
            payload = factory(requested_size)
            reference = json.loads(payload)
            for input_kind in input_kinds:
                for chunk_size in chunk_sizes:
                    chunks = _chunks(payload, chunk_size, input_kind)
                    prefixes = _prefixes(payload, chunk_size, input_kind)
                    cumulative_work = sum(len(prefix) for prefix in prefixes)
                    include_cumulative_finishers = cumulative_work <= max_cumulative_work
                    results = []
                    for name, family, function in _case_functions(
                        chunks,
                        prefixes,
                        include_cumulative_finishers=include_cumulative_finishers,
                        input_kind=input_kind,
                    ):
                        if name == "jsonriver_event_driven" and not jsonriver_strict_by_chunk[chunk_size]:
                            results.append(
                                {
                                    "name": name,
                                    "family": family,
                                    "seconds": None,
                                    "measurement_repetitions": 0,
                                    "valid": False,
                                    "reason": "fails strict invalid-input compatibility gate",
                                }
                            )
                            continue
                        if (
                            name == "ijson_yajl2_c_event_driven"
                            and not ijson_strict_by_case[(input_kind, chunk_size)]
                        ):
                            results.append(
                                {
                                    "name": name,
                                    "family": family,
                                    "seconds": None,
                                    "measurement_repetitions": 0,
                                    "valid": False,
                                    "reason": "fails strict invalid-input compatibility gate",
                                }
                            )
                            continue
                        try:
                            observed = function()
                        except Exception:
                            results.append(
                                {
                                    "name": name,
                                    "family": family,
                                    "seconds": None,
                                    "measurement_repetitions": 0,
                                    "valid": False,
                                    "reason": "raised during valid workload",
                                }
                            )
                            continue
                        valid = (
                            observed == reference
                            if family == "strict_incremental"
                            else True
                        )
                        if not valid:
                            results.append(
                                {
                                    "name": name,
                                    "family": family,
                                    "seconds": None,
                                    "measurement_repetitions": 0,
                                    "valid": False,
                                    "reason": "final value differed from reference",
                                }
                            )
                            continue
                        seconds, measurement_repetitions = _measure(
                            function,
                            repeats,
                            len(payload.encode("utf-8")),
                        )
                        results.append(
                            {
                                "name": name,
                                "family": family,
                                "seconds": seconds,
                                "measurement_repetitions": measurement_repetitions,
                                "valid": True,
                                "reason": None,
                            }
                        )
                    cases.append(
                        {
                            "input_kind": input_kind,
                            "shape": shape,
                            "requested_size": requested_size,
                            "payload_size": len(payload.encode("utf-8")),
                            "chunk_size": chunk_size,
                            "chunk_count": len(chunks),
                            "cumulative_work": cumulative_work,
                            "max_cumulative_work": max_cumulative_work,
                            "cumulative_finishers_skipped": not include_cumulative_finishers,
                            "jsonriver_strict_compatible": jsonriver_strict_by_chunk[chunk_size],
                            "ijson_strict_compatible": ijson_strict_by_case[(input_kind, chunk_size)],
                            "repeats": repeats,
                            "strict_incremental_winner": _winner(results, "strict_incremental"),
                            "strict_incremental_public_winner": _winner(
                                results,
                                "strict_incremental",
                                _PUBLIC_STRICT_INCREMENTAL,
                            ),
                            "structural_finisher_winner": _winner(results, "structural_finisher"),
                            "structural_trailing_winner": _winner(
                                results,
                                "structural_trailing_finisher",
                            ),
                            "permissive_recovery_winner": _winner(results, "permissive_recovery"),
                            "event_driven_winner": _winner(results, "event_driven_partial"),
                            "results": sorted(
                                results,
                                key=lambda result: result["seconds"]
                                if result["valid"]
                                else float("inf"),
                            ),
                        }
                    )
    return {
        "clock": "process_cpu_seconds",
        "sample_count": max(1, repeats),
        "sizes": list(sizes),
        "chunk_sizes": list(chunk_sizes),
        "input_kinds": list(input_kinds),
        "cases": cases,
    }


def _render_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# Partial Strategy Matrix",
        "",
        "Median process CPU seconds per full stream while observing every chunk; semantic families are ranked separately.",
        "",
    ]
    for case in matrix["cases"]:
        lines.extend(
            [
                f"## {case['shape']} ({case['payload_size']} bytes, {case['input_kind']}, chunk {case['chunk_size']})",
                "",
                f"Chunks: `{case['chunk_count']}`; strict incremental raw lower bound: `{case['strict_incremental_winner'] or 'none'}`; public API winner: `{case['strict_incremental_public_winner'] or 'none'}`; structural finisher winner: `{case['structural_finisher_winner'] or 'none'}`; trailing-strings finisher winner: `{case['structural_trailing_winner'] or 'none'}`; permissive recovery winner: `{case['permissive_recovery_winner'] or 'none'}`; event-driven winner: `{case['event_driven_winner'] or 'none'}`.",
                "",
            ]
        )
        if case["cumulative_finishers_skipped"]:
            lines.append(
                f"Structural finishers and cumulative recovery libraries skipped: prefix work `{case['cumulative_work']}` exceeds the `{case['max_cumulative_work']}` budget."
            )
            lines.append("")
        for result in case["results"]:
            if result["valid"]:
                lines.append(
                    f"- `{result['name']}` ({result['family']}): `{result['seconds']:.6f}s`"
                )
            else:
                lines.append(
                    f"- `{result['name']}` ({result['family']}): {result.get('reason', 'invalid or unavailable')}"
                )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[256, 4096, 16384])
    parser.add_argument("--chunks", type=int, nargs="+", default=[1, 8, 64])
    parser.add_argument(
        "--input-kinds",
        choices=("str", "bytes", "bytearray"),
        nargs="+",
        default=["str", "bytes", "bytearray"],
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--max-cumulative-work",
        type=int,
        default=250_000,
        help="Skip cumulative finishers above this total prefix-character budget.",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()
    matrix = collect_matrix(
        tuple(args.sizes),
        tuple(args.chunks),
        repeats=args.repeats,
        max_cumulative_work=args.max_cumulative_work,
        input_kinds=tuple(args.input_kinds),
    )
    if args.format == "json":
        print(json.dumps(matrix, indent=2, sort_keys=True))
    else:
        print(_render_markdown(matrix))


if __name__ == "__main__":
    main()
