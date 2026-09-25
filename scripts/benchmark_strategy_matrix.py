#!/usr/bin/env python3
"""Measure complete-document backend choices across shapes and sizes."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
import statistics
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from streaming_json_parser import (
    decode_complete_json,
    make_complete_json_decoder,
    make_tuned_complete_json_decoder,
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
    import streaming_json_parser_native
except ImportError:  # pragma: no cover - optional native benchmark dependency
    streaming_json_parser_native = None

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
_STRICT_INVALID_PAYLOADS = (
    b'{"value":NaN}',
    b'{"value":01}',
    b'{"value":1e400}',
    b'{"value":1,}',
    b'{"value":1} trailing',
)
_MEASUREMENT_BYTE_TARGET = 1_000_000
_MAX_INNER_REPETITIONS = 5_000


def _callable_key(function: Callable[[InputPayload], Any]) -> tuple[object, ...]:
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


def _flat_string_object(size: int) -> bytes:
    return json.dumps({"data": "x" * size}, separators=(",", ":")).encode()


def _number_array(size: int) -> bytes:
    return json.dumps(list(range(max(1, size // 3))), separators=(",", ":")).encode()


def _nested_records(size: int) -> bytes:
    rows = [
        {"id": index, "value": "x" * 16}
        for index in range(max(1, size // 36))
    ]
    return json.dumps({"rows": rows}, separators=(",", ":")).encode()


def _string_array(size: int) -> bytes:
    return json.dumps(
        ["x" * 16 for _ in range(max(1, size // 20))],
        separators=(",", ":"),
    ).encode()


def _unicode_object(size: int) -> bytes:
    return json.dumps(
        {"data": "hé🙂" * max(1, size // 5)},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _escape_heavy_object(size: int) -> bytes:
    return json.dumps(
        {"data": "\n\t\"\\" * max(1, size // 5)},
        separators=(",", ":"),
    ).encode()


def _wide_object(size: int) -> bytes:
    return json.dumps(
        {f"key_{index}": index for index in range(max(1, size // 12))},
        separators=(",", ":"),
    ).encode()


def _nested_arrays(size: int) -> bytes:
    values = list(range(max(1, size // 4)))
    return json.dumps([values, values], separators=(",", ":")).encode()


def _root_number(size: int) -> bytes:
    return str(max(1, size)).encode()


def _root_literal(size: int) -> bytes:
    del size
    return b"true"


def _root_string(size: int) -> bytes:
    return json.dumps("x" * max(1, size // 4), separators=(",", ":")).encode()


def _measure_functions(
    functions: list[tuple[str, Callable[[InputPayload], Any]]],
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
    unique_functions: list[tuple[tuple[int, int], Callable[[InputPayload], Any]]] = []
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


def _simdjson_materialize(parser: Any, payload: InputPayload) -> Any:
    parsed = parser.parse(payload)
    if hasattr(parsed, "as_dict"):
        return parsed.as_dict()
    if hasattr(parsed, "as_list"):
        return parsed.as_list()
    return parsed


def _as_input(payload: bytes, input_kind: str) -> InputPayload:
    if input_kind == "bytes":
        return payload
    if input_kind == "str":
        return payload.decode("utf-8")
    if input_kind == "bytearray":
        return bytearray(payload)
    raise ValueError(f"unsupported input kind: {input_kind}")


def _invalid_inputs(input_kind: str) -> tuple[InputPayload, ...]:
    return tuple(_as_input(payload, input_kind) for payload in _STRICT_INVALID_PAYLOADS)


def _is_compatible(
    function: Callable[[InputPayload], Any],
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
    sizes: tuple[int, ...],
    *,
    iterations: int,
    input_kinds: tuple[str, ...] = ("bytes", "str", "bytearray"),
) -> dict[str, Any]:
    factories: tuple[tuple[str, PayloadFactory], ...] = (
        ("flat_string_object", _flat_string_object),
        ("number_array", _number_array),
        ("string_array", _string_array),
        ("nested_records", _nested_records),
        ("unicode_object", _unicode_object),
        ("escape_heavy_object", _escape_heavy_object),
        ("wide_object", _wide_object),
        ("nested_arrays", _nested_arrays),
        ("root_number", _root_number),
        ("root_literal", _root_literal),
        ("root_string", _root_string),
    )
    reusable_facade = make_complete_json_decoder()
    reusable_msgspec = msgspec.json.Decoder() if msgspec is not None else None
    reusable_simdjson = simdjson.Parser() if simdjson is not None else None
    cases: list[dict[str, Any]] = []

    for shape, factory in factories:
        for requested_size in sizes:
            payload = factory(requested_size)
            reference = json.loads(payload)
            for input_kind in input_kinds:
                sample = _as_input(payload, input_kind)
                tuned_facade = make_tuned_complete_json_decoder(
                    payload_size_hint=len(payload),
                    sample=sample,
                )
                functions: list[tuple[str, Callable[[InputPayload], Any]]] = [
                    ("facade_decode_complete_json", decode_complete_json),
                    ("facade_reusable_complete_decoder", reusable_facade),
                    ("facade_tuned_complete_decoder", tuned_facade),
                ]
                if orjson is not None:
                    functions.append(("orjson_loads", orjson.loads))
                if reusable_msgspec is not None:
                    functions.append(("msgspec_reusable", reusable_msgspec.decode))
                if reusable_simdjson is not None:
                    functions.append(
                        (
                            "simdjson_materialize",
                            lambda data, parser=reusable_simdjson: _simdjson_materialize(parser, data),
                        )
                    )
                if ujson is not None:
                    functions.append(("ujson_loads", ujson.loads))
                if rapidjson is not None:
                    functions.append(("rapidjson_loads", rapidjson.loads))
                if yyjson is not None:
                    functions.append(("yyjson_loads", yyjson.loads))
                if streaming_json_parser_native is not None and hasattr(
                    streaming_json_parser_native, "decode_complete"
                ):
                    functions.append(
                        ("native_sonic_decode", streaming_json_parser_native.decode_complete)
                    )

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
                results.sort(
                    key=lambda item: item["seconds"]
                    if item["valid"]
                    else float("inf")
                )
                external = [
                    result
                    for result in results
                    if result["valid"]
                    and result["name"] not in {
                        "facade_decode_complete_json",
                        "facade_reusable_complete_decoder",
                        "facade_tuned_complete_decoder",
                    }
                ]
                best_external = min(external, key=lambda item: item["seconds"])
                reusable = next(
                    result
                    for result in results
                    if result["name"] == "facade_reusable_complete_decoder"
                )
                tuned = next(
                    result
                    for result in results
                    if result["name"] == "facade_tuned_complete_decoder"
                )
                cases.append(
                    {
                        "shape": shape,
                        "input_kind": input_kind,
                        "requested_size": requested_size,
                        "payload_size": len(payload),
                        "iterations": iterations,
                        "winner": results[0]["name"],
                        "best_external": best_external["name"],
                        "facade_reusable_ratio": (
                            reusable["seconds"] / best_external["seconds"]
                            if reusable["valid"]
                            else None
                        ),
                        "facade_tuned_ratio": (
                            tuned["seconds"] / best_external["seconds"]
                            if tuned["valid"]
                            else None
                        ),
                        "results": results,
                    }
                )

    return {
        "clock": "performance_counter_seconds",
        "sample_count": 7,
        "sizes": list(sizes),
        "input_kinds": list(input_kinds),
        "cases": cases,
    }


def _render_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# Complete Strategy Matrix",
        "",
        "Median elapsed seconds per decode from seven warmed, interleaved samples.",
        "",
    ]
    for case in matrix["cases"]:
        reusable_ratio = (
            f"{case['facade_reusable_ratio']:.2f}x"
            if case["facade_reusable_ratio"] is not None
            else "incompatible"
        )
        tuned_ratio = (
            f"{case['facade_tuned_ratio']:.2f}x"
            if case["facade_tuned_ratio"] is not None
            else "incompatible"
        )
        lines.extend(
            [
                f"## {case['shape']} ({case['input_kind']}, {case['payload_size']} bytes)",
                "",
                f"Winner: `{case['winner']}`; best external: `{case['best_external']}`; reusable facade ratio: `{reusable_ratio}`; tuned facade ratio: `{tuned_ratio}`.",
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
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=[256, 4096, 16384, 65536, 262144, 1048576],
    )
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
        tuple(args.sizes),
        iterations=args.iterations,
        input_kinds=tuple(args.input_kinds),
    )
    if args.format == "json":
        print(json.dumps(matrix, indent=2, sort_keys=True))
    else:
        print(_render_markdown(matrix))


if __name__ == "__main__":
    main()
