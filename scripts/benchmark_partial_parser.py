#!/usr/bin/env python3

import argparse
import asyncio
import json
import statistics
import sys
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
    HighPerformanceStreamingJsonParser,
    decode_structural_partial_json,
    make_tuned_structural_partial_decoder,
)

try:
    import streaming_json_parser_native
except ImportError:
    streaming_json_parser_native = None

try:
    from partialjson import JSONParser as PartialJsonParser
except ImportError:
    PartialJsonParser = None

try:
    from partial_json_parser import loads as partial_json_loads
except ImportError:
    partial_json_loads = None

try:
    from json_repair import repair_json
except ImportError:
    repair_json = None

try:
    import jsonriver
except ImportError:
    jsonriver = None

try:
    import ijson
    _ijson_yajl2_c = ijson.get_backend("yajl2_c")
except (ImportError, ValueError):
    ijson = None
    _ijson_yajl2_c = None

try:
    import untruncate_json
except ImportError:
    untruncate_json = None

try:
    from pydantic_core import from_json as pydantic_core_from_json
except ImportError:
    pydantic_core_from_json = None

try:
    import jiter
except ImportError:
    jiter = None

_PYDANTIC_CORE_TRAILING_STRINGS = False
if pydantic_core_from_json is not None:
    try:
        _PYDANTIC_CORE_TRAILING_STRINGS = (
            pydantic_core_from_json(b'{"text":"x', allow_partial="trailing-strings")
            == {"text": "x"}
        )
    except (TypeError, ValueError):
        pass


def _payload(size: int) -> str:
    return json.dumps(
        {
            "name": "Alice",
            "age": 30,
            "message": "x" * size,
            "items": [1, 2, 3, 4, 5],
            "nested": {"ok": True, "note": "y" * (size // 4)},
        },
        separators=(",", ":"),
    )


def _chunks(payload: str, chunk_size: int) -> list[str]:
    return [payload[offset : offset + chunk_size] for offset in range(0, len(payload), chunk_size)]


def _prefixes(payload: str, chunk_size: int) -> list[str]:
    return [
        payload[: min(offset + chunk_size, len(payload))]
        for offset in range(0, len(payload), chunk_size)
    ]


def _run_facade(chunks: list[str]) -> Any:
    parser = HighPerformanceStreamingJsonParser()
    for chunk in chunks:
        parser.feed(chunk, copy_value=False)
    return parser.poll(copy_value=False).value


def _run_structural_facade(chunks: list[str], partial_mode: str = "structural") -> Any:
    parser = HighPerformanceStreamingJsonParser(partial_mode=partial_mode)
    for chunk in chunks:
        parser.consume(chunk)
        parser.poll(copy_value=False)
    return parser.poll(copy_value=False).value


def _run_structural_finisher(prefixes: list[str | bytes]) -> Any:
    decoder = make_tuned_structural_partial_decoder(
        sample=prefixes[0] if prefixes else None,
    )
    return [decoder(prefix) for prefix in prefixes]


def _run_partialjson(prefixes: list[str]) -> Any:
    parser = PartialJsonParser()
    return [parser.parse(prefix) for prefix in prefixes]


def _run_partial_json_parser(prefixes: list[str]) -> Any:
    return [partial_json_loads(prefix) for prefix in prefixes]


def _run_json_repair(prefixes: list[str]) -> Any:
    return [repair_json(prefix, return_objects=True) for prefix in prefixes]


def _run_untruncate(prefixes: list[str]) -> Any:
    return [json.loads(untruncate_json.complete(prefix)) for prefix in prefixes]


def _run_pydantic_core(prefixes: list[str]) -> Any:
    return [pydantic_core_from_json(prefix, allow_partial=True) for prefix in prefixes]


def _run_pydantic_core_trailing_strings(prefixes: list[str]) -> Any:
    return [
        pydantic_core_from_json(prefix, allow_partial="trailing-strings")
        for prefix in prefixes
    ]


def _run_jiter(prefixes: list[str | bytes], partial_mode: object) -> Any:
    return [
        jiter.from_json(
            prefix if isinstance(prefix, bytes) else prefix.encode("utf-8"),
            partial_mode=partial_mode,
        )
        for prefix in prefixes
    ]


async def _run_jsonriver_async(chunks: list[str]) -> Any:
    async def stream():
        for chunk in chunks:
            yield chunk

    final = None
    async for value in jsonriver.parse(stream()):
        final = value
    return final


def _run_jsonriver(chunks: list[str]) -> Any:
    return asyncio.run(_run_jsonriver_async(chunks))


def _run_ijson_event_driven(chunks: list[str | bytes]) -> Any:
    if ijson is None or _ijson_yajl2_c is None:
        raise RuntimeError("ijson yajl2_c backend is unavailable")

    builder = ijson.ObjectBuilder()

    @ijson.coroutine
    def target():
        while True:
            _prefix, event, value = yield
            builder.event(event, value)

    parser = _ijson_yajl2_c.parse_coro(target(), use_float=True)
    for chunk in chunks:
        parser.send(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
    parser.close()
    return builder.value


def _measure(function: Callable[[], Any], repeats: int) -> float:
    function()
    samples = []
    for _ in range(repeats):
        started = time.process_time()
        function()
        samples.append(time.process_time() - started)
    return statistics.median(samples)


def main() -> None:
    argument_parser = argparse.ArgumentParser(
        description="Compare true incremental partial parsing with cumulative-reparse finishers.",
    )
    argument_parser.add_argument("--payload-size", type=int, default=512)
    argument_parser.add_argument("--chunk-size", type=int, nargs="+", default=[1, 8, 64])
    argument_parser.add_argument("--repeats", type=int, default=5)
    args = argument_parser.parse_args()

    payload = _payload(args.payload_size)
    print(f"payload_bytes={len(payload.encode('utf-8'))}")
    print("clock=process_cpu_seconds")
    backend = "rust" if streaming_json_parser_native is not None else "python"
    print(f"facade_incremental_backend={backend}")
    print(
        "note=pydantic_core and jiter finishers are not strict semantic peers"
    )
    for chunk_size in args.chunk_size:
        chunks = _chunks(payload, chunk_size)
        prefixes = _prefixes(payload, chunk_size)
        cases: list[tuple[str, Callable[[], Any]]] = [
            ("facade_incremental", lambda: _run_facade(chunks)),
        ]
        if pydantic_core_from_json is not None:
            cases.append(("facade_structural_finisher", lambda: _run_structural_facade(chunks)))
            if _PYDANTIC_CORE_TRAILING_STRINGS:
                cases.append(
                    (
                        "facade_structural_trailing_finisher",
                        lambda: _run_structural_facade(
                            chunks, "structural_trailing_strings"
                        ),
                    )
                )
            cases.append(("facade_structural_one_shot", lambda: _run_structural_finisher(prefixes)))
        if PartialJsonParser is not None:
            cases.append(("partialjson_cumulative_reparse", lambda: _run_partialjson(prefixes)))
        if partial_json_loads is not None:
            cases.append(("partial_json_parser_cumulative_reparse", lambda: _run_partial_json_parser(prefixes)))
        if repair_json is not None:
            cases.append(("json_repair_cumulative_reparse", lambda: _run_json_repair(prefixes)))
        if untruncate_json is not None:
            cases.append(("untruncate_json_cumulative_reparse", lambda: _run_untruncate(prefixes)))
        if pydantic_core_from_json is not None:
            cases.append(("pydantic_core_partial_finisher", lambda: _run_pydantic_core(prefixes)))
        if _PYDANTIC_CORE_TRAILING_STRINGS:
            cases.append(
                (
                    "pydantic_core_trailing_strings_finisher",
                    lambda: _run_pydantic_core_trailing_strings(prefixes),
                )
            )
        if jiter is not None:
            cases.append(
                (
                    "jiter_partial_finisher",
                    lambda: _run_jiter(prefixes, True),
                )
            )
            cases.append(
                (
                    "jiter_trailing_strings_finisher",
                    lambda: _run_jiter(prefixes, "trailing-strings"),
                )
            )
        if jsonriver is not None:
            cases.append(("jsonriver_incremental", lambda: _run_jsonriver(chunks)))

        print(f"chunk_size={chunk_size} chunks={len(chunks)}")
        for name, function in cases:
            elapsed = _measure(function, args.repeats)
            print(f"partial_benchmark name={name} seconds={elapsed:.6f}")


if __name__ == "__main__":
    main()
