#!/usr/bin/env python3
"""Measure strict NDJSON backend choices across record shapes and counts."""

from __future__ import annotations

import argparse
import inspect
import json
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from streaming_json_parser import (
    decode_ndjson,
    make_ndjson_decoder,
    make_tuned_ndjson_decoder,
)

try:
    import msgspec
except ImportError:  # pragma: no cover - optional benchmark dependency
    msgspec = None

try:
    import orjson
except ImportError:  # pragma: no cover - optional benchmark dependency
    orjson = None

try:
    import simdjson
except ImportError:  # pragma: no cover - optional benchmark dependency
    simdjson = None

try:
    import ujson
except ImportError:  # pragma: no cover - optional benchmark dependency
    ujson = None

try:
    import rapidjson
except ImportError:  # pragma: no cover - optional benchmark dependency
    rapidjson = None

try:
    import yyjson
except ImportError:  # pragma: no cover - optional benchmark dependency
    yyjson = None


PayloadFactory = Callable[[int], bytes]
InputPayload = str | bytes | bytearray
Decoder = Callable[[InputPayload], Any]
_STRICT_INVALID_LINES = (
    b'{"value":NaN}\n',
    b'{"value":01}\n',
    b'{"value":1e400}\n',
    b'{"value":1,}\n',
    b'{"value":1}\ntrailing\n',
)
_MEASUREMENT_BYTE_TARGET = 1_000_000
_MAX_INNER_REPETITIONS = 5_000


def _callable_key(function: Decoder) -> tuple[object, ...]:
    bound_self = getattr(function, "__self__", None)
    bound_function = getattr(function, "__func__", None)
    if inspect.isbuiltin(function):
        return (
            "builtin",
            getattr(function, "__module__", None),
            getattr(function, "__qualname__", getattr(function, "__name__", None)),
        )
    if bound_self is not None:
        # Built-in bound methods do not expose __func__, but repeated attribute
        # access still returns the same underlying callable for one instance.
        return id(bound_self), (
            id(bound_function)
            if bound_function is not None
            else getattr(function, "__name__", type(function))
        )
    return 0, id(function)


def _records(factory: Callable[[int], dict[str, Any]], count: int) -> bytes:
    return b"\n".join(
        json.dumps(factory(index), ensure_ascii=False, separators=(",", ":")).encode()
        for index in range(count)
    ) + b"\n"


def _flat_record(index: int) -> dict[str, Any]:
    return {"id": index, "value": "x" * 16, "ok": index % 2 == 0}


def _nested_record(index: int) -> dict[str, Any]:
    return {"row": {"id": index, "value": "x" * 16}, "meta": {"ok": index % 2 == 0}}


def _numeric_array_record(index: int) -> dict[str, Any]:
    return {"id": index, "values": list(range(32))}


def _unicode_record(index: int) -> dict[str, Any]:
    return {"id": index, "text": "hé🙂" * 64}


def _escape_heavy_record(index: int) -> dict[str, Any]:
    return {"id": index, "text": "\n\t\"" * 400}


def _line_loop(decoder: Decoder) -> Decoder:
    return lambda payload: [
        decoder(line)
        for line in payload.split(
            b"\n" if isinstance(payload, (bytes, bytearray)) else "\n"
        )
        if line
    ]


def _simdjson_line_loop(parser: Any) -> Decoder:
    def decode(payload: InputPayload) -> list[Any]:
        values = []
        for line in payload.split(
            b"\n" if isinstance(payload, (bytes, bytearray)) else "\n"
        ):
            if line:
                parsed = parser.parse(line)
                detached = parsed.as_dict() if hasattr(parsed, "as_dict") else parsed.as_list()
                values.append(detached)
                del parsed
        return values

    return decode


def _measure_functions(
    functions: list[tuple[str, Decoder]],
    payload: InputPayload,
    iterations: int,
) -> dict[str, tuple[float, int]]:
    repetitions = max(
        iterations,
        min(
            _MAX_INNER_REPETITIONS,
            _MEASUREMENT_BYTE_TARGET // max(1, len(payload)),
        ),
    )
    unique_functions: list[tuple[tuple[int, int], Decoder]] = []
    function_groups: dict[tuple[object, ...], list[str]] = {}
    for name, function in functions:
        key = _callable_key(function)
        if key not in function_groups:
            function_groups[key] = []
            unique_functions.append((key, function))
        function_groups[key].append(name)

    for _, function in unique_functions:
        function(payload)
    samples_by_key = {key: [] for key, _ in unique_functions}
    for sample_index in range(7):
        for offset in range(len(unique_functions)):
            key, function = unique_functions[(sample_index + offset) % len(unique_functions)]
            started = time.perf_counter()
            for _ in range(repetitions):
                function(payload)
            samples_by_key[key].append(
                (time.perf_counter() - started) / repetitions
            )
    measurements = {
        key: (statistics.median(samples), repetitions)
        for key, samples in samples_by_key.items()
    }
    return {
        name: measurements[key]
        for key, names in function_groups.items()
        for name in names
    }


def _as_input(payload: bytes, input_kind: str) -> InputPayload:
    if input_kind == "bytes":
        return payload
    if input_kind == "str":
        return payload.decode("utf-8")
    if input_kind == "bytearray":
        return bytearray(payload)
    raise ValueError(f"unsupported input kind: {input_kind}")


def _invalid_inputs(input_kind: str) -> tuple[InputPayload, ...]:
    return tuple(_as_input(payload, input_kind) for payload in _STRICT_INVALID_LINES)


def _is_compatible(
    function: Decoder,
    payload: bytes,
    reference: Any,
    input_kind: str = "bytes",
) -> bool:
    probe = _as_input(payload, input_kind)
    try:
        if function(probe) != reference:
            return False
    except Exception:
        return False
    for invalid_payload in _invalid_inputs(input_kind):
        try:
            function(invalid_payload)
        except Exception:
            continue
        return False
    return True


def collect_matrix(
    record_counts: tuple[int, ...],
    *,
    iterations: int,
    input_kinds: tuple[str, ...] = ("bytes", "str", "bytearray"),
) -> dict[str, Any]:
    factories: tuple[tuple[str, PayloadFactory], ...] = (
        ("flat_records", lambda count: _records(_flat_record, count)),
        ("nested_records", lambda count: _records(_nested_record, count)),
        ("numeric_array_records", lambda count: _records(_numeric_array_record, count)),
        ("unicode_records", lambda count: _records(_unicode_record, count)),
        ("escape_heavy_records", lambda count: _records(_escape_heavy_record, count)),
    )
    reusable_facade = make_ndjson_decoder()
    reusable_msgspec = msgspec.json.Decoder() if msgspec is not None else None
    reusable_simdjson = simdjson.Parser() if simdjson is not None else None
    cases = []

    for shape, factory in factories:
        for requested_count in record_counts:
            payload = factory(requested_count)
            reference = [json.loads(line) for line in payload.split(b"\n") if line]
            for input_kind in input_kinds:
                sample = _as_input(payload, input_kind)
                functions: list[tuple[str, Decoder]] = [
                    ("facade_decode_ndjson", decode_ndjson),
                    ("facade_reusable_ndjson_decoder", reusable_facade),
                    (
                        "facade_tuned_ndjson_decoder",
                        make_tuned_ndjson_decoder(
                            sample=sample,
                            payload_size_hint=len(payload),
                        ),
                    ),
                ]
                if msgspec is not None:
                    functions.append(("msgspec_decode_lines", reusable_msgspec.decode_lines))
                if orjson is not None:
                    functions.append(("orjson_line_loop", _line_loop(orjson.loads)))
                if reusable_simdjson is not None:
                    functions.append(("simdjson_line_loop", _simdjson_line_loop(reusable_simdjson)))
                if ujson is not None:
                    functions.append(("ujson_line_loop", _line_loop(ujson.loads)))
                if rapidjson is not None:
                    functions.append(("rapidjson_line_loop", _line_loop(rapidjson.loads)))
                if yyjson is not None:
                    functions.append(("yyjson_line_loop", _line_loop(yyjson.loads)))

                results = []
                compatible_functions = []
                for name, function in functions:
                    if not _is_compatible(function, payload, reference, input_kind):
                        results.append(
                            {
                                "name": name,
                                "seconds": None,
                                "measurement_iterations": 0,
                                "valid": False,
                            }
                        )
                        continue
                    compatible_functions.append((name, function))
                measurements = _measure_functions(
                    compatible_functions,
                    sample,
                    iterations,
                )
                for name, _ in compatible_functions:
                    seconds, measurement_iterations = measurements[name]
                    results.append(
                        {
                            "name": name,
                            "seconds": seconds,
                            "measurement_iterations": measurement_iterations,
                            "valid": True,
                        }
                    )
                results.sort(key=lambda item: item["seconds"] if item["valid"] else float("inf"))
                external = [
                    result
                    for result in results
                    if result["valid"]
                    and result["name"] not in {
                        "facade_decode_ndjson",
                        "facade_reusable_ndjson_decoder",
                        "facade_tuned_ndjson_decoder",
                    }
                ]
                best_external = min(external, key=lambda item: item["seconds"])
                reusable = next(
                    result
                    for result in results
                    if result["name"] == "facade_reusable_ndjson_decoder"
                )
                tuned = next(
                    result
                    for result in results
                    if result["name"] == "facade_tuned_ndjson_decoder"
                )
                cases.append(
                    {
                        "shape": shape,
                        "input_kind": input_kind,
                        "requested_records": requested_count,
                        "payload_size": len(payload),
                        "iterations": iterations,
                        "winner": results[0]["name"],
                        "best_external": best_external["name"],
                        "facade_reusable_ratio": reusable["seconds"] / best_external["seconds"],
                        "facade_tuned_ratio": tuned["seconds"] / best_external["seconds"],
                        "results": results,
                    }
                )

    return {
        "clock": "performance_counter_seconds",
        "sample_count": 7,
        "record_counts": list(record_counts),
        "input_kinds": list(input_kinds),
        "cases": cases,
    }


def _render_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# NDJSON Strategy Matrix",
        "",
        "Median elapsed seconds per decode from seven warmed, interleaved samples; incompatible permissive backends are excluded.",
        "",
    ]
    for case in matrix["cases"]:
        lines.extend(
            [
                f"## {case['shape']} ({case['input_kind']}, {case['requested_records']} records, {case['payload_size']} bytes)",
                "",
                f"Winner: `{case['winner']}`; best external: `{case['best_external']}`; reusable facade ratio: `{case['facade_reusable_ratio']:.2f}x`; tuned facade ratio: `{case['facade_tuned_ratio']:.2f}x`.",
                "",
            ]
        )
        for result in case["results"]:
            if result["valid"]:
                lines.append(f"- `{result['name']}`: `{result['seconds']:.6f}s`")
            else:
                lines.append(f"- `{result['name']}`: incompatible output (excluded)")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, nargs="+", default=[100, 1000, 5000])
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--input-kinds",
        choices=("bytes", "str", "bytearray"),
        nargs="+",
        default=["bytes", "str", "bytearray"],
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()
    matrix = collect_matrix(
        tuple(args.records),
        iterations=args.iterations,
        input_kinds=tuple(args.input_kinds),
    )
    if args.format == "json":
        print(json.dumps(matrix, indent=2, sort_keys=True))
    else:
        print(_render_markdown(matrix))


if __name__ == "__main__":
    main()
