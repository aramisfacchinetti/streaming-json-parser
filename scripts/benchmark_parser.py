#!/usr/bin/env python3
import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
DOCS_ROOT = REPO_ROOT / "docs"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from streaming_json_parser.high_performance_parser import (
    HighPerformanceStreamingJsonParser,
    decode_complete_json,
    decode_complete_json_view,
    decode_ndjson,
    extract_complete_json_paths,
    extract_complete_json_typed_paths,
    extract_ndjson_paths,
    extract_tuned_json_paths,
    extract_tuned_complete_json_paths,
    extract_tuned_ndjson_paths,
    extract_ndjson_paths_native,
    extract_ndjson_typed_paths,
    make_complete_json_decoder,
    make_complete_json_typed_path_extractor,
    make_ndjson_path_extractor,
    make_tuned_json_path_extractor,
    make_tuned_complete_json_path_extractor,
    make_tuned_ndjson_path_extractor,
    make_tuned_complete_json_decoder,
    make_complete_json_view_decoder,
    make_json_path_extractor,
    make_ndjson_path_extractor_native,
    make_ndjson_typed_path_extractor,
    make_ndjson_decoder,
    make_tuned_ndjson_decoder,
)

try:
    import ijson
except ImportError:  # pragma: no cover - optional benchmark dependency
    ijson = None

try:
    import orjson
except ImportError:  # pragma: no cover - optional benchmark dependency
    orjson = None

try:
    import msgspec
except ImportError:  # pragma: no cover - optional benchmark dependency
    msgspec = None

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


_STRICT_INVALID_PAYLOADS = (
    b'{"value":NaN}',
    b'{"value":01}',
    b'{"value":1e400}',
    b'{"value":1,}',
    b'{"value":1} trailing',
)


def _is_strictly_compatible(
    decoder: Callable[[bytes], object],
    payload: bytes,
    reference: object,
) -> bool:
    try:
        if decoder(payload) != reference:
            return False
    except Exception:
        return False
    for invalid_payload in _STRICT_INVALID_PAYLOADS:
        try:
            decoder(invalid_payload)
        except Exception:
            continue
        return False
    return True


def _measure(name: str, iterations: int, func: Callable[[], object]) -> tuple[str, float]:
    func()
    samples = []
    for _ in range(7):
        started = time.process_time()
        for _ in range(iterations):
            func()
        samples.append(time.process_time() - started)
    return name, statistics.median(samples)


def benchmark_complete_parse_baselines(payload_size: int, iterations: int) -> None:
    payload_text = json.dumps({"data": "x" * payload_size})
    payload_bytes = payload_text.encode()
    reusable_decoder = make_complete_json_decoder()

    def hybrid_once() -> object:
        parser = HighPerformanceStreamingJsonParser()
        parser.consume(payload_bytes)
        return parser.poll().value

    cases: list[tuple[str, object]] = [
        ("hybrid_complete_once", hybrid_once),
        ("facade_decode_complete_json", lambda: decode_complete_json(payload_bytes)),
        ("facade_reusable_complete_decoder", lambda: reusable_decoder(payload_bytes)),
        ("json_loads", lambda: json.loads(payload_bytes)),
    ]

    if orjson is not None:
        cases.append(("orjson_loads", lambda: orjson.loads(payload_bytes)))

    if msgspec is not None:
        cases.append(("msgspec_decode", lambda: msgspec.json.decode(payload_bytes)))

    if ujson is not None:
        cases.append(("ujson_loads", lambda: ujson.loads(payload_bytes)))

    if rapidjson is not None:
        cases.append(("rapidjson_loads", lambda: rapidjson.loads(payload_bytes)))

    if simdjson is not None:
        parser = simdjson.Parser()
        cases.append(("simdjson_parse", lambda: parser.parse(payload_bytes).as_dict()))

    for name, func in cases:
        started = time.perf_counter()
        for _ in range(iterations):
            func()
        elapsed = time.perf_counter() - started
        print("complete_baseline", f"name={name}", f"iterations={iterations}", f"seconds={elapsed:.6f}")


def collect_complete_baseline_snapshot(payload_size: int = 1_000_000, iterations: int = 20) -> dict[str, object]:
    payload_text = json.dumps({"data": "x" * payload_size})
    payload_bytes = payload_text.encode()
    reference = json.loads(payload_bytes)
    reusable_decoder = make_complete_json_decoder()

    def hybrid_once() -> object:
        parser = HighPerformanceStreamingJsonParser()
        parser.consume(payload_bytes)
        return parser.poll().value

    cases: list[tuple[str, Callable[[], object]]] = [
        ("hybrid_complete_once", hybrid_once),
        ("facade_decode_complete_json", lambda: decode_complete_json(payload_bytes)),
        ("facade_reusable_complete_decoder", lambda: reusable_decoder(payload_bytes)),
    ]

    if orjson is not None:
        cases.append(("orjson_loads", lambda: orjson.loads(payload_bytes)))

    if msgspec is not None:
        cases.append(("msgspec_decode", lambda: msgspec.json.decode(payload_bytes)))

    if ujson is not None and _is_strictly_compatible(ujson.loads, payload_bytes, reference):
        cases.append(("ujson_loads", lambda: ujson.loads(payload_bytes)))

    if rapidjson is not None and _is_strictly_compatible(rapidjson.loads, payload_bytes, reference):
        cases.append(("rapidjson_loads", lambda: rapidjson.loads(payload_bytes)))

    if simdjson is not None:
        parser = simdjson.Parser()
        simdjson_decoder = lambda data: parser.parse(data).as_dict()
        if _is_strictly_compatible(simdjson_decoder, payload_bytes, reference):
            cases.append(("simdjson_parse", lambda: simdjson_decoder(payload_bytes)))

    results = [{"name": name, "seconds": elapsed} for name, elapsed in (_measure(name, iterations, func) for name, func in cases)]
    results.sort(key=lambda item: item["seconds"])
    return {
        "section": "complete_1mb_object",
        "payload_size": payload_size,
        "iterations": iterations,
        "results": results,
    }


def benchmark_concatenated_complete_objects(count: int) -> None:
    concatenated = ('{"a":1,"b":"xyz"}\n' * count).encode()

    def stdlib_raw_decode_loop() -> int:
        decoder = json.JSONDecoder()
        offset = 0
        parsed = 0
        text = concatenated.decode()
        while offset < len(text):
            _, offset = decoder.raw_decode(text, offset)
            while offset < len(text) and text[offset].isspace():
                offset += 1
            parsed += 1
        return parsed

    started = time.perf_counter()
    stdlib_count = stdlib_raw_decode_loop()
    stdlib_elapsed = time.perf_counter() - started
    print(
        "concat_complete",
        "name=stdlib_raw_decode_loop",
        f"count={stdlib_count}",
        f"seconds={stdlib_elapsed:.6f}",
    )


def benchmark_streaming_baselines(count: int) -> None:
    if ijson is None:
        print("streaming_baseline", "name=ijson", "status=unavailable")
        return

    object_text = '{"a":1,"b":"xyz"}'
    array_text = "[" + ",".join([object_text] * count) + "]"

    for backend_name in ("yajl2_c", "python"):
        try:
            backend = ijson.get_backend(backend_name)
        except Exception as exc:  # pragma: no cover - environment-specific
            print(
                "streaming_baseline",
                f"name=ijson_{backend_name}",
                f"status=unavailable:{type(exc).__name__}",
            )
            continue

        import io

        parsed = 0
        started = time.perf_counter()
        for _ in backend.items(io.StringIO(array_text), "item"):
            parsed += 1
        elapsed = time.perf_counter() - started
        print(
            "streaming_baseline",
            f"name=ijson_{backend_name}",
            f"count={parsed}",
            f"seconds={elapsed:.6f}",
        )


def show_hybrid_partial_state_semantics() -> None:
    parser = HighPerformanceStreamingJsonParser()
    parser.consume('{"key": "partial string')
    first = parser.poll()
    parser.consume(' complete"}')
    second = parser.poll()
    print(
        "hybrid_partial_state_case",
        "name=readme_delta_followup",
        f"first={first.value!r}",
        f"first_status={first.status.value}",
        f"second={second.value!r}",
        f"second_status={second.status.value}",
    )


def benchmark_hybrid_delta_stream(value_size: int, chunk_size: int) -> None:
    payload = json.dumps({"data": "x" * value_size, "n": 1, "ok": True, "arr": [1, 2, 3]})
    chunks = [payload[i : i + chunk_size] for i in range(0, len(payload), chunk_size)]

    hybrid = HighPerformanceStreamingJsonParser()
    started = time.perf_counter()
    for chunk in chunks:
        hybrid.consume(chunk)
        hybrid.poll(copy_value=False)
    hybrid_elapsed = time.perf_counter() - started
    hybrid_result = hybrid.poll(copy_value=False)

    print(
        "hybrid_delta_benchmark",
        f"value_size={value_size}",
        f"chunk_size={chunk_size}",
        f"hybrid_seconds={hybrid_elapsed:.6f}",
        f"hybrid_status={hybrid_result.status.value}",
    )


def benchmark_hybrid_reuse(payload_size: int, iterations: int) -> None:
    payload = json.dumps({"data": "x" * payload_size, "ok": True, "n": 1}).encode()
    hybrid = HighPerformanceStreamingJsonParser()

    started = time.perf_counter()
    for _ in range(iterations):
        hybrid.reset()
        hybrid.consume(payload)
        hybrid.poll(copy_value=False)
    elapsed = time.perf_counter() - started

    print(
        "hybrid_reuse",
        f"payload_size={payload_size}",
        f"iterations={iterations}",
        f"seconds={elapsed:.6f}",
    )


def benchmark_direct_helpers(payload_size: int, iterations: int) -> None:
    payload = json.dumps({"data": "x" * payload_size, "ok": True, "n": 1}).encode()
    tuned_decoder = make_tuned_complete_json_decoder(
        payload_size_hint=len(payload),
        sample=payload,
    )

    cases: list[tuple[str, object]] = [
        ("decode_complete_json", lambda: decode_complete_json(payload)),
        ("tuned_complete_json_decoder", lambda: tuned_decoder(payload)),
        ("decode_complete_json_view", lambda: decode_complete_json_view(payload)),
    ]

    if msgspec is not None:
        decoder = msgspec.json.Decoder()
        cases.append(("msgspec_decoder", lambda: decoder.decode(payload)))

    if orjson is not None:
        cases.append(("orjson_loads", lambda: orjson.loads(payload)))

    if ujson is not None:
        cases.append(("ujson_loads", lambda: ujson.loads(payload)))

    if rapidjson is not None:
        cases.append(("rapidjson_loads", lambda: rapidjson.loads(payload)))

    if simdjson is not None:
        parser = simdjson.Parser()
        cases.append(("simdjson_recursive", lambda: parser.parse(payload, recursive=True)))
        cases.append(("simdjson_proxy", lambda: parser.parse(payload)))

    for name, func in cases:
        started = time.perf_counter()
        for _ in range(iterations):
            func()
        elapsed = time.perf_counter() - started
        print("direct_helper", f"name={name}", f"payload_size={payload_size}", f"iterations={iterations}", f"seconds={elapsed:.6f}")


def benchmark_ndjson_modes(count: int, iterations: int) -> None:
    line = json.dumps({"a": 1, "b": "xyz"}).encode()
    payload = (b"\n".join([line] * count) + b"\n")
    record_type = None
    if msgspec is not None:
        record_type = msgspec.defstruct("BenchmarkRecord", [("a", int), ("b", str)])

    def streaming_parser() -> list[object]:
        parser = HighPerformanceStreamingJsonParser(framing="ndjson")
        parser.consume(payload)
        out = []
        while True:
            result = parser.poll(copy_value=False)
            if not result.complete:
                return out
            out.append(result.value)

    def streaming_typed_parser() -> list[object]:
        parser = HighPerformanceStreamingJsonParser(framing="ndjson", record_type=record_type)
        parser.consume(payload)
        out = []
        while True:
            result = parser.poll(copy_value=False)
            if not result.complete:
                return out
            out.append(result.value)

    def streaming_batch_parser() -> list[object]:
        parser = HighPerformanceStreamingJsonParser(framing="ndjson")
        parser.consume(payload)
        return parser.poll_many(copy_value=False)

    def streaming_typed_batch_parser() -> list[object]:
        parser = HighPerformanceStreamingJsonParser(framing="ndjson", record_type=record_type)
        parser.consume(payload)
        return parser.poll_many(copy_value=False)

    cases: list[tuple[str, object]] = [
        ("decode_ndjson", lambda: decode_ndjson(payload)),
        ("streaming_ndjson_parser", streaming_parser),
    ]

    if msgspec is not None:
        decoder = msgspec.json.Decoder()
        if hasattr(decoder, "decode_lines"):
            cases.append(("msgspec_decode_lines", lambda: decoder.decode_lines(payload)))
        if record_type is not None:
            typed_decoder = msgspec.json.Decoder(record_type)
            cases.append(("decode_ndjson_typed", lambda: decode_ndjson(payload, record_type=record_type)))
            cases.append(("msgspec_decode_lines_typed", lambda: typed_decoder.decode_lines(payload)))
            cases.append(("streaming_ndjson_typed_parser", streaming_typed_parser))
            cases.append(("streaming_ndjson_typed_batch_parser", streaming_typed_batch_parser))

    if orjson is not None:
        cases.append(("orjson_splitlines", lambda: [orjson.loads(line) for line in payload.splitlines() if line]))

    if ujson is not None:
        cases.append(("ujson_splitlines", lambda: [ujson.loads(line) for line in payload.splitlines() if line]))

    if rapidjson is not None:
        cases.append(("rapidjson_splitlines", lambda: [rapidjson.loads(line) for line in payload.splitlines() if line]))

    cases.append(("streaming_ndjson_batch_parser", streaming_batch_parser))

    for name, func in cases:
        started = time.perf_counter()
        for _ in range(iterations):
            func()
        elapsed = time.perf_counter() - started
        print("ndjson_mode", f"name={name}", f"count={count}", f"iterations={iterations}", f"seconds={elapsed:.6f}")


def benchmark_compiled_decoders(iterations: int, ndjson_iterations: int) -> None:
    if msgspec is None:
        print("compiled_decoder", "status=unavailable:msgspec")
        return

    value_type = msgspec.defstruct("CompiledValueRecord", [("a", int), ("b", str), ("ok", bool), ("arr", list[int])])
    record_type = msgspec.defstruct("CompiledNdjsonRecord", [("a", int), ("b", str)])
    payload = json.dumps({"a": 1, "b": "xyz", "ok": True, "arr": [1, 2, 3]}).encode()
    line = json.dumps({"a": 1, "b": "xyz"}).encode()
    ndjson_payload = (b"\n".join([line] * 5_000) + b"\n")

    direct_complete = msgspec.json.Decoder(value_type).decode
    direct_ndjson = msgspec.json.Decoder(record_type).decode_lines
    compiled_complete = make_complete_json_decoder(value_type=value_type)
    compiled_complete_view = make_complete_json_view_decoder()
    compiled_ndjson = make_ndjson_decoder(record_type=record_type)
    complete_payload = json.dumps({"a": 1, "b": "xyz", "ok": True, "arr": [1, 2, 3]}).encode()

    cases: list[tuple[str, object, int]] = [
        ("msgspec_typed_complete", lambda: direct_complete(complete_payload), iterations),
        ("compiled_typed_complete", lambda: compiled_complete(complete_payload), iterations),
        ("compiled_view_complete", lambda: compiled_complete_view(complete_payload), iterations),
        ("msgspec_typed_ndjson", lambda: direct_ndjson(ndjson_payload), ndjson_iterations),
        ("compiled_typed_ndjson", lambda: compiled_ndjson(ndjson_payload), ndjson_iterations),
    ]

    for name, func, count in cases:
        started = time.perf_counter()
        for _ in range(count):
            func()
        elapsed = time.perf_counter() - started
        print("compiled_decoder", f"name={name}", f"iterations={count}", f"seconds={elapsed:.6f}")


def benchmark_selective_access(iterations: int) -> None:
    payload = json.dumps(
        {
            "meta": {"version": 1, "name": "dataset", "ok": True},
            "rows": [{"a": i, "b": "xyz", "ok": True, "arr": [1, 2, 3]} for i in range(5_000)],
            "tail": {"count": 5_000, "checksum": "abc123"},
        }
    ).encode()
    paths = (("meta", "name"), ("tail", "count"), ("rows", 0, "a"))
    typed_paths = (("meta", "name"), ("tail", "count"))
    typed_sample = {
        "meta": {"version": 1, "name": "dataset", "ok": True},
        "tail": {"count": 5_000, "checksum": "abc123"},
    }
    extractor = make_json_path_extractor(*paths)
    typed_extractor = make_complete_json_typed_path_extractor(*typed_paths, sample=typed_sample)
    tuned_typed_extractor = make_tuned_complete_json_path_extractor(
        *typed_paths,
        sample=typed_sample,
        payload_size_hint=len(payload),
    )
    unified_tuned_extractor = make_tuned_json_path_extractor(
        *typed_paths,
        framing="single",
        sample=typed_sample,
        payload_size_hint=len(payload),
    )

    cases: list[tuple[str, object]] = [
        ("repo_path_extractor", lambda: extractor(payload)),
        ("repo_extract_once", lambda: extract_complete_json_paths(payload, *paths)),
        ("typed_complete_path_extractor", lambda: typed_extractor(payload)),
        ("typed_complete_extract_once", lambda: extract_complete_json_typed_paths(payload, *typed_paths, sample=typed_sample)),
        ("tuned_complete_path_extractor", lambda: tuned_typed_extractor(payload)),
        ("tuned_complete_extract_once", lambda: extract_tuned_complete_json_paths(payload, *typed_paths, sample=typed_sample)),
        ("tuned_json_path_extractor", lambda: unified_tuned_extractor(payload)),
        ("tuned_json_extract_once", lambda: extract_tuned_json_paths(payload, *typed_paths, framing="single", sample=typed_sample)),
    ]

    if simdjson is not None:
        parser = simdjson.Parser()
        cases.append(
            (
                "simdjson_proxy_manual",
                lambda: (
                    lambda doc: (doc["meta"]["name"], doc["tail"]["count"], doc["rows"][0]["a"])
                )(parser.parse(payload)),
            )
        )

    if orjson is not None:
        cases.append(
            (
                "orjson_full_then_select",
                lambda: (
                    lambda doc: (doc["meta"]["name"], doc["tail"]["count"], doc["rows"][0]["a"])
                )(orjson.loads(payload)),
            )
        )

    if msgspec is not None:
        decoder = msgspec.json.Decoder()
        cases.append(
            (
                "msgspec_full_then_select",
                lambda: (
                    lambda doc: (doc["meta"]["name"], doc["tail"]["count"], doc["rows"][0]["a"])
                )(decoder.decode(payload)),
            )
        )

    for name, func in cases:
        started = time.perf_counter()
        for _ in range(iterations):
            func()
        elapsed = time.perf_counter() - started
        print("selective_access", f"name={name}", f"iterations={iterations}", f"seconds={elapsed:.6f}")


def collect_selective_access_snapshot(iterations: int = 200) -> dict[str, object]:
    payload = json.dumps(
        {
            "meta": {"version": 1, "name": "dataset", "ok": True},
            "rows": [{"a": i, "b": "xyz", "ok": True, "arr": [1, 2, 3]} for i in range(5_000)],
            "tail": {"count": 5_000, "checksum": "abc123"},
        }
    ).encode()
    paths = (("meta", "name"), ("tail", "count"), ("rows", 0, "a"))
    typed_paths = (("meta", "name"), ("tail", "count"))
    typed_sample = {
        "meta": {"version": 1, "name": "dataset", "ok": True},
        "tail": {"count": 5_000, "checksum": "abc123"},
    }
    extractor = make_json_path_extractor(*paths)
    typed_extractor = make_complete_json_typed_path_extractor(*typed_paths, sample=typed_sample)
    tuned_typed_extractor = make_tuned_complete_json_path_extractor(
        *typed_paths,
        sample=typed_sample,
        payload_size_hint=len(payload),
    )
    unified_tuned_extractor = make_tuned_json_path_extractor(
        *typed_paths,
        framing="single",
        sample=typed_sample,
        payload_size_hint=len(payload),
    )

    cases: list[tuple[str, Callable[[], object]]] = [
        ("repo_path_extractor", lambda: extractor(payload)),
        ("repo_extract_once", lambda: extract_complete_json_paths(payload, *paths)),
        ("typed_complete_path_extractor", lambda: typed_extractor(payload)),
        ("typed_complete_extract_once", lambda: extract_complete_json_typed_paths(payload, *typed_paths, sample=typed_sample)),
        ("tuned_complete_path_extractor", lambda: tuned_typed_extractor(payload)),
        ("tuned_complete_extract_once", lambda: extract_tuned_complete_json_paths(payload, *typed_paths, sample=typed_sample)),
        ("tuned_json_path_extractor", lambda: unified_tuned_extractor(payload)),
        ("tuned_json_extract_once", lambda: extract_tuned_json_paths(payload, *typed_paths, framing="single", sample=typed_sample)),
    ]

    if simdjson is not None:
        parser = simdjson.Parser()
        cases.append(
            (
                "simdjson_proxy_manual",
                lambda: (
                    lambda doc: (doc["meta"]["name"], doc["tail"]["count"], doc["rows"][0]["a"])
                )(parser.parse(payload)),
            )
        )

    if orjson is not None:
        cases.append(
            (
                "orjson_full_then_select",
                lambda: (
                    lambda doc: (doc["meta"]["name"], doc["tail"]["count"], doc["rows"][0]["a"])
                )(orjson.loads(payload)),
            )
        )

    if msgspec is not None:
        decoder = msgspec.json.Decoder()
        cases.append(
            (
                "msgspec_full_then_select",
                lambda: (
                    lambda doc: (doc["meta"]["name"], doc["tail"]["count"], doc["rows"][0]["a"])
                )(decoder.decode(payload)),
            )
        )

    results = [{"name": name, "seconds": elapsed} for name, elapsed in (_measure(name, iterations, func) for name, func in cases)]
    results.sort(key=lambda item: item["seconds"])
    return {
        "section": "complete_selective_extraction",
        "iterations": iterations,
        "results": results,
    }


def benchmark_ndjson_selective_access(iterations: int) -> None:
    payload = (
        b"\n".join(
            [
                json.dumps(
                    {
                        "meta": {"src": "x"},
                        "row": {"id": i, "value": "xyz", "ok": True, "arr": [1, 2, 3]},
                    }
                ).encode()
                for i in range(5_000)
            ]
        )
        + b"\n"
    )
    lines = payload.splitlines()
    paths = (("row", "id"), ("row", "value"))
    typed_sample = {"meta": {"src": "x"}, "row": {"id": 1, "value": "xyz", "ok": True, "arr": [1, 2, 3]}}

    cases: list[tuple[str, object]] = []

    if msgspec is not None:
        typed_extractor = make_ndjson_typed_path_extractor(*paths, sample=typed_sample)
        cases.append(("typed_ndjson_path_extractor", lambda: typed_extractor(payload)))
        cases.append(("typed_ndjson_extract_once", lambda: extract_ndjson_typed_paths(payload, *paths, sample=typed_sample)))
        tuned_extractor = make_tuned_ndjson_path_extractor(*paths, sample=typed_sample, payload_size_hint=len(payload))
        cases.append(("tuned_ndjson_path_extractor", lambda: tuned_extractor(payload)))
        cases.append(("tuned_ndjson_extract_once", lambda: extract_tuned_ndjson_paths(payload, *paths, sample=typed_sample)))
        unified_tuned_extractor = make_tuned_json_path_extractor(
            *paths,
            framing="ndjson",
            sample=typed_sample,
            payload_size_hint=len(payload),
        )
        cases.append(("tuned_json_path_extractor", lambda: unified_tuned_extractor(payload)))
        cases.append(("tuned_json_extract_once", lambda: extract_tuned_json_paths(payload, *paths, framing="ndjson", sample=typed_sample)))

    generic_extractor = make_ndjson_path_extractor(*paths)
    cases.append(("generic_ndjson_path_extractor", lambda: generic_extractor(payload)))
    cases.append(("generic_ndjson_extract_once", lambda: extract_ndjson_paths(payload, *paths)))

    try:
        native_extractor = make_ndjson_path_extractor_native(*paths)
    except Exception:
        native_extractor = None
    if native_extractor is not None:
        cases.append(("native_ndjson_path_extractor", lambda: native_extractor(payload)))
        cases.append(("native_ndjson_extract_once", lambda: extract_ndjson_paths_native(payload, *paths)))

    if simdjson is not None:
        cases.append(
            (
                "simdjson_proxy_manual",
                lambda: [
                    (doc["row"]["id"], doc["row"]["value"])
                    for doc in (simdjson.Parser().parse(line).as_dict() for line in lines)
                ],
            )
        )

    if orjson is not None:
        cases.append(
            (
                "orjson_full_then_select",
                lambda: [(doc["row"]["id"], doc["row"]["value"]) for doc in (orjson.loads(line) for line in lines)],
            )
        )

    if msgspec is not None:
        decoder = msgspec.json.Decoder()
        cases.append(
            (
                "msgspec_full_then_select",
                lambda: [(doc["row"]["id"], doc["row"]["value"]) for doc in (decoder.decode(line) for line in lines)],
            )
        )

    for name, func in cases:
        started = time.perf_counter()
        for _ in range(iterations):
            func()
        elapsed = time.perf_counter() - started
        print("ndjson_selective_access", f"name={name}", f"iterations={iterations}", f"seconds={elapsed:.6f}")


def collect_ndjson_selective_access_snapshot(iterations: int = 25) -> dict[str, object]:
    payload = (
        b"\n".join(
            [
                json.dumps(
                    {
                        "meta": {"src": "x"},
                        "row": {"id": i, "value": "xyz", "ok": True, "arr": [1, 2, 3]},
                    }
                ).encode()
                for i in range(5_000)
            ]
        )
        + b"\n"
    )
    lines = payload.splitlines()
    paths = (("row", "id"), ("row", "value"))
    typed_sample = {"meta": {"src": "x"}, "row": {"id": 1, "value": "xyz", "ok": True, "arr": [1, 2, 3]}}

    cases: list[tuple[str, Callable[[], object]]] = []

    if msgspec is not None:
        typed_extractor = make_ndjson_typed_path_extractor(*paths, sample=typed_sample)
        cases.append(("typed_ndjson_path_extractor", lambda: typed_extractor(payload)))
        cases.append(("typed_ndjson_extract_once", lambda: extract_ndjson_typed_paths(payload, *paths, sample=typed_sample)))
        tuned_extractor = make_tuned_ndjson_path_extractor(*paths, sample=typed_sample, payload_size_hint=len(payload))
        cases.append(("tuned_ndjson_path_extractor", lambda: tuned_extractor(payload)))
        cases.append(("tuned_ndjson_extract_once", lambda: extract_tuned_ndjson_paths(payload, *paths, sample=typed_sample)))
        unified_tuned_extractor = make_tuned_json_path_extractor(
            *paths,
            framing="ndjson",
            sample=typed_sample,
            payload_size_hint=len(payload),
        )
        cases.append(("tuned_json_path_extractor", lambda: unified_tuned_extractor(payload)))
        cases.append(("tuned_json_extract_once", lambda: extract_tuned_json_paths(payload, *paths, framing="ndjson", sample=typed_sample)))

    generic_extractor = make_ndjson_path_extractor(*paths)
    cases.append(("generic_ndjson_path_extractor", lambda: generic_extractor(payload)))
    cases.append(("generic_ndjson_extract_once", lambda: extract_ndjson_paths(payload, *paths)))

    try:
        native_extractor = make_ndjson_path_extractor_native(*paths)
    except Exception:
        native_extractor = None
    if native_extractor is not None:
        cases.append(("native_ndjson_path_extractor", lambda: native_extractor(payload)))
        cases.append(("native_ndjson_extract_once", lambda: extract_ndjson_paths_native(payload, *paths)))

    if simdjson is not None:
        cases.append(
            (
                "simdjson_proxy_manual",
                lambda: [
                    (doc["row"]["id"], doc["row"]["value"])
                    for doc in (simdjson.Parser().parse(line).as_dict() for line in lines)
                ],
            )
        )

    if orjson is not None:
        cases.append(
            (
                "orjson_full_then_select",
                lambda: [(doc["row"]["id"], doc["row"]["value"]) for doc in (orjson.loads(line) for line in lines)],
            )
        )

    if msgspec is not None:
        decoder = msgspec.json.Decoder()
        cases.append(
            (
                "msgspec_full_then_select",
                lambda: [(doc["row"]["id"], doc["row"]["value"]) for doc in (decoder.decode(line) for line in lines)],
            )
        )

    results = [{"name": name, "seconds": elapsed} for name, elapsed in (_measure(name, iterations, func) for name, func in cases)]
    results.sort(key=lambda item: item["seconds"])
    return {
        "section": "ndjson_selective_extraction",
        "iterations": iterations,
        "results": results,
    }


def collect_current_snapshot() -> dict[str, object]:
    return {
        "date": time.strftime("%Y-%m-%d"),
        "sections": [
            collect_complete_baseline_snapshot(),
            collect_selective_access_snapshot(),
            collect_ndjson_selective_access_snapshot(),
        ],
    }


def _format_snapshot_markdown(snapshot: dict[str, object]) -> str:
    lines = [
        "# Benchmark Snapshot",
        "",
        f"Date: {snapshot['date']}",
        "",
        "Times are median process CPU seconds from seven warmed samples; they are not wall-clock latency.",
        "",
        "Generated by:",
        "",
        "- `make benchmark-artifacts`",
    ]
    section_titles = {
        "complete_1mb_object": "Complete 1 MB Object",
        "complete_selective_extraction": "Complete Selective Extraction",
        "ndjson_selective_extraction": "NDJSON Selective Extraction",
    }
    for section in snapshot["sections"]:
        lines.extend(["", f"## {section_titles.get(section['section'], section['section'])}", ""])
        if "payload_size" in section:
            lines.append(f"{section['iterations']} iterations, payload size `{section['payload_size']}` bytes.")
        else:
            lines.append(f"{section['iterations']} iterations.")
        lines.append("")
        for result in section["results"]:
            lines.append(f"- `{result['name']}`: `{result['seconds']:.6f}s`")
    return "\n".join(lines) + "\n"


def _render_snapshot(snapshot: dict[str, object], snapshot_format: str) -> str:
    if snapshot_format == "json":
        return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    return _format_snapshot_markdown(snapshot)


def _result_map(snapshot: dict[str, object]) -> dict[str, dict[str, float]]:
    result_sections: dict[str, dict[str, float]] = {}
    for section in snapshot["sections"]:
        result_sections[section["section"]] = {result["name"]: result["seconds"] for result in section["results"]}
    return result_sections


def _markdown_link(path: Path) -> str:
    try:
        label = str(path.relative_to(REPO_ROOT))
        target = label
    except ValueError:
        label = path.name
        target = str(path)
    return f"[{label}]({target})"


def _format_current_api_scorecard(
    snapshot: dict[str, object],
    docs_dir: Path,
    *,
    stable_links: bool = False,
) -> str:
    snapshot_date = str(snapshot["date"])
    if stable_links:
        snapshot_markdown_path = docs_dir / "benchmark-snapshot.md"
        snapshot_json_path = docs_dir / "benchmark-snapshot.json"
    else:
        snapshot_markdown_path = docs_dir / f"benchmark-snapshot-{snapshot_date}.md"
        snapshot_json_path = docs_dir / f"benchmark-snapshot-{snapshot_date}.json"
    results = _result_map(snapshot)
    iterations = {
        section["section"]: section.get("iterations")
        for section in snapshot["sections"]
    }

    def format_seconds(section_name: str, result_name: str) -> str:
        return f"{results[section_name][result_name]:.6f}s"

    native_once = results["ndjson_selective_extraction"]["native_ndjson_extract_once"]
    native_reused = results["ndjson_selective_extraction"]["native_ndjson_path_extractor"]
    native_low = min(native_once, native_reused)
    native_high = max(native_once, native_reused)
    complete_facade_lines = [
        f"  - `{label}`: `{format_seconds('complete_1mb_object', name)}`"
        for name, label in (
            ("facade_decode_complete_json", "facade_decode_complete_json"),
            ("facade_reusable_complete_decoder", "facade_reusable_complete_decoder"),
        )
        if name in results["complete_1mb_object"]
    ]
    snapshot_description = "current benchmark snapshot" if stable_links else "dated benchmark snapshot"

    lines = [
        "# Current API Scorecard",
        "",
        f"Date: {snapshot_date}",
        "",
        'This scorecard is the shortest honest answer to "what should I use from this repo today?"',
        "",
        f"For the {snapshot_description} behind these recommendations, see {_markdown_link(snapshot_markdown_path)} and {_markdown_link(snapshot_json_path)}. To regenerate all tracked artifacts from the current harness, run `make benchmark-artifacts`. To verify that those tracked generated artifacts are current without rewriting them, run `make verify-benchmark-artifacts`.",
        "",
        "## Recommended APIs",
        "",
        "- Strict incremental partial streaming:",
        "  - Use `StreamingJsonParser`",
        "  - Best when you need real delta-chunk correctness and explicit `EMPTY` / `PARTIAL` / `COMPLETE` / `INVALID` states",
        "  - With the optional `streaming_json_parser_native` wheel, single-document partial modes use the Rust incremental core",
        "  - Call `finish()` when the source is exhausted, especially for root scalars or a final NDJSON line without a newline",
        "  - Use `parser.feed(chunk)` when each chunk is consumed and polled immediately; it collapses the native boundary",
        "",
        "- Structural partial snapshots without unfinished-string semantics:",
        "  - Use `StreamingJsonParser(partial_mode=\"structural\")`",
        "  - For an already available prefix, use `decode_structural_partial_json(...)` to avoid parser-object overhead",
        "  - For repeated prefixes with a stable input representation, use `make_tuned_structural_partial_decoder(sample=...)`",
        "  - Prefer the parser for fine-grained delta chunks; prefer the one-shot or tuned finisher when prefixes arrive in coarse batches",
        "  - Uses the calibrated native facade, Pydantic Core, or Jiter finisher path according to the representative workload",
        "  - Omits unfinished strings and may complete scalar prefixes before `finish()`",
        "  - One-shot structural finishers return `None` for syntactically valid but incomplete root scalars",
        "  - Use `partial_mode=\"structural_trailing_strings\"` when the trailing unfinished string must be retained",
        "",
        "Use the structural parser when the caller needs a stateful snapshot after many small delta chunks. If the caller already has coarse prefixes, use `decode_structural_partial_json(...)` or a sample-tuned finisher instead; reparsing a coarse prefix can be cheaper than constructing and synchronizing an incremental tree. This distinction is workload-driven and is not collapsed into one universal route because the crossover varies with chunk size, document shape, and whether unfinished strings are retained.",
        "",
        "- Complete document, detached Python objects:",
        "  - Use `decode_complete_json(...)`",
        "  - If you know the payload size band or have a representative sample and will reuse the decoder, prefer `make_tuned_complete_json_decoder(...)`",
        "  - Pass both `sample=` and `payload_size_hint=` to validate and benchmark strict compatible backends once at construction for representatives at least 64 bytes; calibration uses the sample's input representation and replaces the static fallback only after a 10% measured speed margin for complete JSON or a 20% margin for NDJSON",
        "",
        "- Complete document, fastest in-repo large-payload path:",
        "  - Use `decode_complete_json_view(...)` or `make_complete_json_view_decoder(...)`",
        "  - Best when `simdjson` view/proxy semantics are acceptable",
        "",
        "- Complete document, selective field extraction:",
        "  - Reused extractor: `make_tuned_json_path_extractor(..., framing=\"single\")`",
        "  - One-shot call: `extract_tuned_json_paths(..., framing=\"single\")`",
        "  - For large documents this effectively tracks the existing `simdjson` view extractor",
        "",
        "- NDJSON full-record decode:",
        "  - Generic: `decode_ndjson(...)`",
        "  - Schema-adaptive typed option: `decode_ndjson_adaptive(...)` (returns inferred msgspec records when the lines are type-stable)",
        "  - Typed: `make_ndjson_decoder(record_type=...)`",
        "  - Stable repeated workload: `make_tuned_ndjson_decoder(sample=..., payload_size_hint=...)`",
        "",
        "- NDJSON selective field extraction:",
        "  - Reused extractor: `make_tuned_json_path_extractor(..., framing=\"ndjson\")`",
        "  - One-shot call: `extract_tuned_json_paths(..., framing=\"ndjson\")`",
        "  - This is the clearest top-level selective API in the repo right now",
        "",
        "## Latest Snapshot",
        "",
        f"These numbers come from the current repo benchmark slices run on {snapshot_date}; they report median process CPU seconds from seven warmed samples, not wall-clock latency.",
        "",
        f"- Complete 1 MB object, {iterations['complete_1mb_object']} iterations:",
        f"  - `simdjson_parse`: `{format_seconds('complete_1mb_object', 'simdjson_parse')}`",
        *complete_facade_lines,
        f"  - `msgspec_decode`: `{format_seconds('complete_1mb_object', 'msgspec_decode')}`",
        f"  - `orjson_loads`: `{format_seconds('complete_1mb_object', 'orjson_loads')}`",
        f"  - `hybrid_complete_once`: `{format_seconds('complete_1mb_object', 'hybrid_complete_once')}`",
        "",
        f"- Complete selective extraction, {iterations['complete_selective_extraction']} iterations:",
        f"  - `simdjson_proxy_manual`: `{format_seconds('complete_selective_extraction', 'simdjson_proxy_manual')}`",
        f"  - `tuned_complete_path_extractor`: `{format_seconds('complete_selective_extraction', 'tuned_complete_path_extractor')}`",
        f"  - `tuned_json_path_extractor` with `framing=\"single\"`: `{format_seconds('complete_selective_extraction', 'tuned_json_path_extractor')}`",
        f"  - `repo_path_extractor`: `{format_seconds('complete_selective_extraction', 'repo_path_extractor')}`",
        f"  - `orjson_full_then_select`: `{format_seconds('complete_selective_extraction', 'orjson_full_then_select')}`",
        "",
        f"- NDJSON selective extraction, {iterations['ndjson_selective_extraction']} iterations:",
        f"  - `tuned_ndjson_path_extractor`: `{format_seconds('ndjson_selective_extraction', 'tuned_ndjson_path_extractor')}`",
        f"  - `tuned_json_path_extractor` with `framing=\"ndjson\"`: `{format_seconds('ndjson_selective_extraction', 'tuned_json_path_extractor')}`",
        f"  - `typed_ndjson_path_extractor`: `{format_seconds('ndjson_selective_extraction', 'typed_ndjson_path_extractor')}`",
        f"  - `orjson_full_then_select`: `{format_seconds('ndjson_selective_extraction', 'orjson_full_then_select')}`",
        f"  - `msgspec_full_then_select`: `{format_seconds('ndjson_selective_extraction', 'msgspec_full_then_select')}`",
        f"  - `generic_ndjson_path_extractor`: `{format_seconds('ndjson_selective_extraction', 'generic_ndjson_path_extractor')}`",
        f"  - native `sonic-rs` path: `{native_low:.6f}s-{native_high:.6f}s`",
        "",
        "## Non-Recommendations",
        "",
        "- Do not compare Pydantic Core `allow_partial` as a strict partial-value peer; it is a fast structural finisher but does not preserve unfinished string values.",
        "- Do not recommend the native selective NDJSON path as the default. Current evidence still does not justify it.",
        "- Do not recommend the typed complete selective extractor as the universal complete selective path. It helps on smaller object-shaped documents, but the tuned selector is the practical recommendation.",
    ]
    return "\n".join(lines) + "\n"


def emit_snapshot(snapshot_format: str, output_path: Path | None = None, snapshot: dict[str, object] | None = None) -> str:
    current_snapshot = collect_current_snapshot() if snapshot is None else snapshot
    rendered = _render_snapshot(current_snapshot, snapshot_format)

    if output_path is not None:
        resolved_output_path = output_path.resolve()
        resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_output_path.write_text(rendered)
    return rendered


def write_snapshot_bundle(output_dir: Path, snapshot: dict[str, object] | None = None) -> dict[str, Path]:
    current_snapshot = collect_current_snapshot() if snapshot is None else snapshot
    resolved_output_dir = output_dir.resolve()
    snapshot_date = str(current_snapshot["date"])
    markdown_path = resolved_output_dir / f"benchmark-snapshot-{snapshot_date}.md"
    json_path = resolved_output_dir / f"benchmark-snapshot-{snapshot_date}.json"
    emit_snapshot("markdown", markdown_path, snapshot=current_snapshot)
    emit_snapshot("json", json_path, snapshot=current_snapshot)
    return {"markdown": markdown_path, "json": json_path}


def write_artifact_bundle(output_dir: Path, snapshot: dict[str, object] | None = None) -> dict[str, Path]:
    current_snapshot = collect_current_snapshot() if snapshot is None else snapshot
    resolved_output_dir = output_dir.resolve()
    snapshot_date = str(current_snapshot["date"])
    snapshot_paths = write_snapshot_bundle(resolved_output_dir, snapshot=current_snapshot)
    scorecard_path = resolved_output_dir / f"current-api-scorecard-{snapshot_date}.md"
    scorecard_path.write_text(_format_current_api_scorecard(current_snapshot, resolved_output_dir))
    current_markdown_path = resolved_output_dir / "benchmark-snapshot.md"
    current_json_path = resolved_output_dir / "benchmark-snapshot.json"
    current_scorecard_path = resolved_output_dir / "current-api-scorecard.md"
    emit_snapshot("markdown", current_markdown_path, snapshot=current_snapshot)
    emit_snapshot("json", current_json_path, snapshot=current_snapshot)
    current_scorecard_path.write_text(
        _format_current_api_scorecard(current_snapshot, resolved_output_dir, stable_links=True)
    )
    return {
        "markdown": snapshot_paths["markdown"],
        "json": snapshot_paths["json"],
        "scorecard": scorecard_path,
        "current_markdown": current_markdown_path,
        "current_json": current_json_path,
        "current_scorecard": current_scorecard_path,
    }


def render_artifact_bundle(output_dir: Path, snapshot: dict[str, object] | None = None) -> dict[str, tuple[Path, str]]:
    current_snapshot = collect_current_snapshot() if snapshot is None else snapshot
    resolved_output_dir = output_dir.resolve()
    snapshot_date = str(current_snapshot["date"])
    markdown_path = resolved_output_dir / f"benchmark-snapshot-{snapshot_date}.md"
    json_path = resolved_output_dir / f"benchmark-snapshot-{snapshot_date}.json"
    scorecard_path = resolved_output_dir / f"current-api-scorecard-{snapshot_date}.md"
    current_markdown_path = resolved_output_dir / "benchmark-snapshot.md"
    current_json_path = resolved_output_dir / "benchmark-snapshot.json"
    current_scorecard_path = resolved_output_dir / "current-api-scorecard.md"
    return {
        "markdown": (markdown_path, _render_snapshot(current_snapshot, "markdown")),
        "json": (json_path, _render_snapshot(current_snapshot, "json")),
        "scorecard": (scorecard_path, _format_current_api_scorecard(current_snapshot, resolved_output_dir)),
        "current_markdown": (current_markdown_path, _render_snapshot(current_snapshot, "markdown")),
        "current_json": (current_json_path, _render_snapshot(current_snapshot, "json")),
        "current_scorecard": (
            current_scorecard_path,
            _format_current_api_scorecard(current_snapshot, resolved_output_dir, stable_links=True),
        ),
    }


def _compare_snapshots(
    tracked_snapshot: dict[str, object],
    current_snapshot: dict[str, object],
    *,
    rel_tol: float = 0.5,
    abs_tol: float = 0.01,
) -> list[str]:
    mismatches: list[str] = []
    tracked_sections = {section["section"]: section for section in tracked_snapshot["sections"]}
    current_sections = {section["section"]: section for section in current_snapshot["sections"]}

    if set(tracked_sections) != set(current_sections):
        missing = sorted(set(tracked_sections) ^ set(current_sections))
        mismatches.append(f"structure:sections:{','.join(missing)}")
        return mismatches

    for section_name, tracked_section in tracked_sections.items():
        current_section = current_sections[section_name]
        if tracked_section.get("iterations") != current_section.get("iterations"):
            mismatches.append(f"structure:iterations:{section_name}")
            continue
        if tracked_section.get("payload_size") != current_section.get("payload_size"):
            mismatches.append(f"structure:payload_size:{section_name}")
            continue

        tracked_results = {result["name"]: result["seconds"] for result in tracked_section["results"]}
        current_results = {result["name"]: result["seconds"] for result in current_section["results"]}
        if set(tracked_results) != set(current_results):
            missing = sorted(set(tracked_results) ^ set(current_results))
            mismatches.append(f"structure:results:{section_name}:{','.join(missing)}")
            continue

        ratios = [
            current_results[name] / tracked_seconds
            for name, tracked_seconds in tracked_results.items()
            if tracked_seconds > 0 and current_results[name] > 0
        ]
        common_slowdown = statistics.median(ratios) if ratios else 1.0
        normalize_common_slowdown = len(ratios) >= 3 and common_slowdown > 1.0 + rel_tol
        for result_name, tracked_seconds in tracked_results.items():
            current_seconds = current_results[result_name]
            expected_seconds = (
                tracked_seconds * common_slowdown
                if normalize_common_slowdown
                else tracked_seconds
            )
            tolerance = max(abs_tol, abs(expected_seconds) * rel_tol)
            if current_seconds - expected_seconds > tolerance:
                mismatches.append(
                    f"drift:{section_name}:{result_name}:{tracked_seconds:.6f}:{current_seconds:.6f}"
                )
    return mismatches


def verify_artifact_bundle(output_dir: Path, snapshot: dict[str, object] | None = None) -> list[str]:
    resolved_output_dir = output_dir.resolve()
    current_snapshot = collect_current_snapshot() if snapshot is None else snapshot
    markdown_path = resolved_output_dir / "benchmark-snapshot.md"
    json_path = resolved_output_dir / "benchmark-snapshot.json"
    scorecard_path = resolved_output_dir / "current-api-scorecard.md"

    mismatches: list[str] = []
    for label, path in (("markdown", markdown_path), ("json", json_path), ("scorecard", scorecard_path)):
        if not path.exists():
            mismatches.append(f"missing:{label}:{path}")
    if mismatches:
        return mismatches

    tracked_snapshot = json.loads(json_path.read_text())

    expected_markdown = _render_snapshot(tracked_snapshot, "markdown")
    if markdown_path.read_text() != expected_markdown:
        mismatches.append(f"stale:markdown:{markdown_path}")

    expected_scorecard = _format_current_api_scorecard(tracked_snapshot, resolved_output_dir, stable_links=True)
    if scorecard_path.read_text() != expected_scorecard:
        mismatches.append(f"stale:scorecard:{scorecard_path}")

    mismatches.extend(_compare_snapshots(tracked_snapshot, current_snapshot))
    return mismatches


def _run_full_benchmark() -> None:
    print("# complete object fast path")
    benchmark_complete_parse_baselines(payload_size=1_000_000, iterations=50)

    print("\n# concatenated object throughput")
    benchmark_concatenated_complete_objects(count=50_000)
    benchmark_streaming_baselines(count=50_000)

    print("\n# Partial state semantics")
    show_hybrid_partial_state_semantics()

    print("\n# Hybrid delta benchmark")
    for value_size in (1_000, 10_000):
        for chunk_size in (8, 64):
            benchmark_hybrid_delta_stream(value_size=value_size, chunk_size=chunk_size)

    print("\n# Hybrid reuse benchmark")
    benchmark_hybrid_reuse(payload_size=64, iterations=10_000)
    benchmark_hybrid_reuse(payload_size=30_000, iterations=200)

    print("\n# Direct helper benchmark")
    benchmark_direct_helpers(payload_size=64, iterations=10_000)
    benchmark_direct_helpers(payload_size=30_000, iterations=200)

    print("\n# NDJSON mode benchmark")
    benchmark_ndjson_modes(count=5_000, iterations=5)

    print("\n# Compiled decoder benchmark")
    benchmark_compiled_decoders(iterations=10_000, ndjson_iterations=5)

    print("\n# Selective access benchmark")
    benchmark_selective_access(iterations=200)

    print("\n# NDJSON selective access benchmark")
    benchmark_ndjson_selective_access(iterations=5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark streaming-json-parser and related fast paths.")
    parser.add_argument(
        "--snapshot",
        choices=("json", "markdown"),
        help="Emit the current concise benchmark snapshot instead of the full benchmark suite.",
    )
    parser.add_argument(
        "--snapshot-output",
        type=Path,
        help="Optional file path for snapshot output. Requires --snapshot.",
    )
    parser.add_argument(
        "--snapshot-bundle-dir",
        type=Path,
        help="Write both Markdown and JSON snapshot artifacts into this directory.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help="Write the Markdown snapshot, JSON snapshot, and dated current API scorecard into this directory.",
    )
    parser.add_argument(
        "--artifacts",
        action="store_true",
        help="Write the Markdown snapshot, JSON snapshot, and dated current API scorecard into the repo's docs directory.",
    )
    parser.add_argument(
        "--verify-artifacts-dir",
        type=Path,
        help="Verify that the tracked Markdown snapshot, JSON snapshot, and dated scorecard match current generated content.",
    )
    parser.add_argument(
        "--verify-artifacts",
        action="store_true",
        help="Verify the tracked Markdown snapshot, JSON snapshot, and dated scorecard in the repo's docs directory.",
    )
    args = parser.parse_args()

    if args.artifacts and args.artifacts_dir is not None:
        parser.error("--artifacts cannot be combined with --artifacts-dir")
    if args.verify_artifacts and args.verify_artifacts_dir is not None:
        parser.error("--verify-artifacts cannot be combined with --verify-artifacts-dir")
    if args.artifacts_dir is not None and (
        args.snapshot is not None
        or args.snapshot_output is not None
        or args.snapshot_bundle_dir is not None
        or args.verify_artifacts_dir is not None
        or args.verify_artifacts
    ):
        parser.error("--artifacts-dir cannot be combined with --snapshot, --snapshot-output, --snapshot-bundle-dir, or --verify-artifacts-dir")
    if args.artifacts and (
        args.snapshot is not None
        or args.snapshot_output is not None
        or args.snapshot_bundle_dir is not None
        or args.verify_artifacts_dir is not None
        or args.verify_artifacts
    ):
        parser.error("--artifacts cannot be combined with --snapshot, --snapshot-output, --snapshot-bundle-dir, --verify-artifacts-dir, or --verify-artifacts")
    if args.verify_artifacts_dir is not None and (
        args.snapshot is not None or args.snapshot_output is not None or args.snapshot_bundle_dir is not None or args.artifacts
    ):
        parser.error("--verify-artifacts-dir cannot be combined with --snapshot, --snapshot-output, or --snapshot-bundle-dir")
    if args.verify_artifacts and (
        args.snapshot is not None or args.snapshot_output is not None or args.snapshot_bundle_dir is not None or args.artifacts
    ):
        parser.error("--verify-artifacts cannot be combined with --snapshot, --snapshot-output, --snapshot-bundle-dir, or --artifacts")
    if args.snapshot_bundle_dir is not None and (args.snapshot is not None or args.snapshot_output is not None):
        parser.error("--snapshot-bundle-dir cannot be combined with --snapshot or --snapshot-output")
    if args.snapshot_output is not None and args.snapshot is None:
        parser.error("--snapshot-output requires --snapshot")
    if args.verify_artifacts:
        mismatches = verify_artifact_bundle(DOCS_ROOT)
        if mismatches:
            for mismatch in mismatches:
                print(mismatch)
            raise SystemExit(1)
        print(f"ok={DOCS_ROOT.resolve()}")
        return
    if args.verify_artifacts_dir is not None:
        mismatches = verify_artifact_bundle(args.verify_artifacts_dir)
        if mismatches:
            for mismatch in mismatches:
                print(mismatch)
            raise SystemExit(1)
        print(f"ok={args.verify_artifacts_dir.resolve()}")
        return
    if args.artifacts:
        created = write_artifact_bundle(DOCS_ROOT)
        print(f"markdown={created['markdown']}")
        print(f"json={created['json']}")
        print(f"scorecard={created['scorecard']}")
        return
    if args.artifacts_dir is not None:
        created = write_artifact_bundle(args.artifacts_dir)
        print(f"markdown={created['markdown']}")
        print(f"json={created['json']}")
        print(f"scorecard={created['scorecard']}")
        return
    if args.snapshot_bundle_dir is not None:
        created = write_snapshot_bundle(args.snapshot_bundle_dir)
        print(f"markdown={created['markdown']}")
        print(f"json={created['json']}")
        return

    if args.snapshot is not None:
        print(emit_snapshot(args.snapshot, args.snapshot_output), end="")
        return

    _run_full_benchmark()


if __name__ == "__main__":
    main()
