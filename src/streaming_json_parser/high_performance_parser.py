from __future__ import annotations

import copy
import dataclasses
import json
import keyword
import time
from collections import deque
from enum import Enum
from typing import Any

try:
    import orjson as _backend_orjson
except Exception:  # pragma: no cover - optional fast backend
    _backend_orjson = None

try:
    import msgspec as _backend_msgspec
except Exception:  # pragma: no cover - optional fast backend
    _backend_msgspec = None

try:
    import simdjson as _backend_simdjson
except Exception:  # pragma: no cover - optional fast backend
    _backend_simdjson = None

try:
    import yyjson as _backend_yyjson
except Exception:  # pragma: no cover - optional fast backend
    _backend_yyjson = None

try:
    import ujson as _backend_ujson
except Exception:  # pragma: no cover - optional benchmark backend
    _backend_ujson = None

try:
    import rapidjson as _backend_rapidjson
except Exception:  # pragma: no cover - optional benchmark backend
    _backend_rapidjson = None

try:
    import streaming_json_parser_native as _backend_native
except Exception:  # pragma: no cover - optional experimental native backend
    _backend_native = None

try:
    from pydantic_core import from_json as _backend_pydantic_from_json
except Exception:  # pragma: no cover - optional structural partial backend
    _backend_pydantic_from_json = None

try:
    import jiter as _backend_jiter
except Exception:  # pragma: no cover - optional faster structural partial backend
    _backend_jiter = None

_PYDANTIC_TRAILING_STRINGS = False
if _backend_pydantic_from_json is not None:
    try:
        _PYDANTIC_TRAILING_STRINGS = (
            _backend_pydantic_from_json(
                b'{"text":"x', allow_partial="trailing-strings"
            )
            == {"text": "x"}
        )
    except (TypeError, ValueError):
        pass

_GLOBAL_SIMD_PARSER = _backend_simdjson.Parser() if _backend_simdjson is not None else None
_GLOBAL_MSGSPEC_DECODER = _backend_msgspec.json.Decoder() if _backend_msgspec is not None else None
_STRUCT_CACHE: dict[tuple[tuple[str, Any], ...], type[Any]] = {}
_ADAPTIVE_NDJSON_DECODER_CACHE: dict[tuple[Any, ...], Any] = {}
_ADAPTIVE_NDJSON_CACHE_LIMIT = 64
_NO_ADAPTIVE_NDJSON_DECODER = object()
_LAST_ADAPTIVE_NDJSON_DECODER: Any | None = None
_DECODER_CACHE: dict[Any, Any] = {}
_COMPLETE_PATH_EXTRACTOR_CACHE: dict[tuple[tuple[str | int, ...], ...], Any] = {}
_NDJSON_PATH_EXTRACTOR_CACHE: dict[tuple[tuple[str | int, ...], ...], Any] = {}
_COMPLETE_TYPED_PATH_EXTRACTOR_CACHE: dict[tuple[Any, tuple[tuple[str, ...], ...]], Any] = {}
_NDJSON_TYPED_PATH_EXTRACTOR_CACHE: dict[tuple[Any, tuple[tuple[str, ...], ...]], Any] = {}
_INCOMPLETE = object()
_INVALID = object()
_ORJSON_TINY_THRESHOLD = 256
_ORJSON_ARRAY_THRESHOLD = 65536
_NDJSON_ORJSON_ESCAPE_THRESHOLD = 256
_NDJSON_ORJSON_ARRAY_THRESHOLD = 512
_NDJSON_ESCAPE_PROBE_BYTES = 4096
_NDJSON_ESCAPE_PROBE_COUNT = 8
_NATIVE_ROOT_STRING_THRESHOLD = 4096
_NATIVE_FLAT_STRING_OBJECT_THRESHOLD = 4096
# Unicode text can occupy more native input bytes than its Python length.
_NATIVE_FLAT_STRING_TEXT_THRESHOLD = 4096
_NATIVE_UNICODE_CHUNK_THRESHOLD = 32
_ROOT_BOUNDARY_SCAN_THRESHOLD = 8192
_STRUCTURAL_JITER_TEXT_THRESHOLD = 128
_STRUCTURAL_JITER_BYTEARRAY_OBJECT_THRESHOLD = 8_192
_TYPED_COMPLETE_PATH_THRESHOLD = 16384
_TYPED_NDJSON_RECORD_THRESHOLD = 16384
_ORJSON_WIDE_OBJECT_FIELDS = 8
_ORJSON_WIDE_OBJECT_PROBE_BYTES = 65_536
_NUMERIC_JSON_BYTES = frozenset(b"-0123456789")
_TUNED_PROBE_BYTE_TARGET = 500_000
_TUNED_PROBE_MAX_REPETITIONS = 128
_TUNED_PROBE_MIN_REPETITIONS = 3
_TUNED_PROBE_SAMPLES = 7
# Representative tuned decoders can amortize a small construction-time probe
# even for compact records; the previous 4 KiB floor left common small shapes
# on static heuristics despite a compatible backend being measurably faster.
_TUNED_CALIBRATION_THRESHOLD = 64
_STRUCTURAL_TUNED_CALIBRATION_THRESHOLD = 128
# A caller opting into sample calibration has supplied a stable workload, but
# process-time samples can still be noisy. Require a material win before
# replacing the static fallback so calibration cannot regress a stable route.
_TUNED_MIN_SPEEDUP_RATIO = 0.90
# NDJSON construction-time samples are line-loop workloads, where small
# scheduling differences can otherwise promote a slower backend. Require a
# 20% win before replacing a stable static route.
_TUNED_NDJSON_MIN_SPEEDUP_RATIO = 0.80
_SIMPLE_STRING_MAX_VALUE_LENGTH = 4_096
_SIMPLE_STRING_NATIVE_HANDOFF_LENGTH = 4
_STRICT_CALIBRATION_INVALID_DOCUMENTS = (
    b'{"value":NaN}',
    b'{"value":01}',
    b'{"value":1e400}',
    b'{"value":1,}',
    b'{"value":1} trailing',
)
_STRICT_CALIBRATION_INVALID_LINES = tuple(
    payload + b"\n" for payload in _STRICT_CALIBRATION_INVALID_DOCUMENTS
)
_STRUCTURAL_CALIBRATION_INVALID_DOCUMENTS = (
    b'{"value":@}',
    b'{"value":{]}',
)


class ParseStatus(str, Enum):
    EMPTY = "empty"
    PARTIAL = "partial"
    COMPLETE = "complete"
    INVALID = "invalid"


@dataclasses.dataclass(slots=True)
class _PythonParseResult:
    status: ParseStatus
    value: Any | None
    complete: bool
    error: str | None = None


_NATIVE_RESULT_TYPE = (
    getattr(_backend_native, "ParseResult", None)
    if _backend_native is not None
    else None
)
ParseResult = _NATIVE_RESULT_TYPE or _PythonParseResult
_NATIVE_STRICT_RESULT_METHODS = (
    "configure_statuses",
    "consume",
    "consume_and_poll_result",
    "poll_result_value",
    "finish_result",
    "reset",
)


def _native_strict_result_available() -> bool:
    return bool(
        _NATIVE_RESULT_TYPE is not None
        and _backend_native is not None
        and hasattr(_backend_native, "IncrementalJsonParser")
        and all(
            hasattr(_backend_native.IncrementalJsonParser, method)
            for method in _NATIVE_STRICT_RESULT_METHODS
        )
    )


_NATIVE_STRICT_BACKEND = _backend_native
_NATIVE_STRICT_AVAILABLE = _native_strict_result_available()
_NATIVE_NDJSON_DECODER = (
    getattr(_backend_native, "decode_ndjson", None)
    if _backend_native is not None
    else None
)
_NATIVE_INCREMENTAL_TYPE = (
    getattr(_backend_native, "IncrementalJsonParser", None)
    if _backend_native is not None
    else None
)
_NATIVE_PUBLIC_METHODS = (
    "configure_public_api",
    "feed",
    "poll",
    "finish",
    "reset",
    "poll_many",
)
_NATIVE_PUBLIC_AVAILABLE = bool(
    _NATIVE_RESULT_TYPE is not None
    and _NATIVE_INCREMENTAL_TYPE is not None
    and all(hasattr(_NATIVE_INCREMENTAL_TYPE, method) for method in _NATIVE_PUBLIC_METHODS)
)
_NATIVE_FACADE_TYPE = (
    getattr(_backend_native, "FacadeIncrementalJsonParser", None)
    if _backend_native is not None
    else None
)
_NATIVE_FACADE_METHODS = (
    "configure_statuses",
    "consume",
    "feed",
    "poll",
    "finish",
    "reset",
    "poll_many",
    "configure_partial_mode",
)
_NATIVE_FACADE_AVAILABLE = bool(
    _NATIVE_RESULT_TYPE is not None
    and _NATIVE_FACADE_TYPE is not None
    and all(hasattr(_NATIVE_FACADE_TYPE, method) for method in _NATIVE_FACADE_METHODS)
)


def _new_native_incremental(
    *,
    public_api: bool = False,
    partial_mode: str = "strict",
) -> Any:
    native = _backend_native.IncrementalJsonParser()
    if _NATIVE_RESULT_TYPE is not None:
        native.configure_statuses(
            ParseStatus.EMPTY,
            ParseStatus.PARTIAL,
            ParseStatus.COMPLETE,
            ParseStatus.INVALID,
        )
    if public_api:
        native.configure_public_api(
            partial_mode != "structural",
            partial_mode != "strict",
        )
    return native


def _new_native_facade_incremental(partial_mode: str = "strict") -> Any:
    native = _NATIVE_FACADE_TYPE()
    native.configure_statuses(
        ParseStatus.EMPTY,
        ParseStatus.PARTIAL,
        ParseStatus.COMPLETE,
        ParseStatus.INVALID,
    )
    native.configure_partial_mode(
        partial_mode != "structural",
        partial_mode != "strict",
    )
    return native


@dataclasses.dataclass(slots=True)
class _SimpleStringFeedState:
    raw_parts: list[str] = dataclasses.field(default_factory=list)
    key: str | None = None
    value: str = ""
    value_start: int = 0
    scan_index: int = 0
    phase: int = 0


def _coerce_bytes(data: str | bytes | bytearray) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    return data.encode("utf-8")


def _has_dense_json_escapes(payload: bytes) -> bool:
    prefix_end = min(len(payload), _NDJSON_ESCAPE_PROBE_BYTES)
    if payload.count(b"\\", 0, prefix_end) >= _NDJSON_ESCAPE_PROBE_COUNT:
        return True
    if len(payload) <= _NDJSON_ESCAPE_PROBE_BYTES:
        return False
    return (
        payload.count(b"\\", len(payload) - _NDJSON_ESCAPE_PROBE_BYTES)
        >= _NDJSON_ESCAPE_PROBE_COUNT
    )


def _has_dense_json_escapes_text(payload: str) -> bool:
    prefix_end = min(len(payload), _NDJSON_ESCAPE_PROBE_BYTES)
    if payload.count("\\", 0, prefix_end) >= _NDJSON_ESCAPE_PROBE_COUNT:
        return True
    if len(payload) <= _NDJSON_ESCAPE_PROBE_BYTES:
        return False
    return (
        payload.count("\\", len(payload) - _NDJSON_ESCAPE_PROBE_BYTES)
        >= _NDJSON_ESCAPE_PROBE_COUNT
    )


def _has_non_ascii_unicode_escape(payload: str | bytes | bytearray) -> bool:
    """Return whether a JSON string contains a ``\\u`` escape above ASCII."""
    is_bytes = isinstance(payload, (bytes, bytearray))
    backslash = ord("\\") if is_bytes else "\\"
    marker = b"\\u" if is_bytes else r"\u"
    index = 0
    while True:
        index = payload.find(marker, index)
        if index < 0:
            return False
        preceding_backslashes = 0
        cursor = index - 1
        while cursor >= 0 and payload[cursor] == backslash:
            preceding_backslashes += 1
            cursor -= 1
        if preceding_backslashes % 2 == 0 and index + 6 <= len(payload):
            try:
                codepoint = int(payload[index + 2:index + 6], 16)
            except ValueError:
                pass
            else:
                if codepoint > 0x7F:
                    return True
        index += 2


def _looks_plain_ascii_text(payload: str) -> bool:
    if len(payload) <= _NDJSON_ESCAPE_PROBE_BYTES:
        return payload.isascii() and "\\" not in payload
    probe_end = min(len(payload), _NDJSON_ESCAPE_PROBE_BYTES)
    prefix = payload[:probe_end]
    if not prefix.isascii() or "\\" in prefix:
        return False
    if len(payload) <= _NDJSON_ESCAPE_PROBE_BYTES:
        return True
    suffix = payload[-_NDJSON_ESCAPE_PROBE_BYTES:]
    return suffix.isascii() and "\\" not in suffix


def _should_use_orjson_for_escaped_payload(
    data: str | bytes | bytearray,
) -> bool:
    if isinstance(data, str):
        if "\\" not in data:
            return False
        return _has_dense_json_escapes_text(data)
    if b"\\" not in data:
        return False
    return _has_dense_json_escapes(bytes(data))


def _has_numeric_array_record(payload: bytes | bytearray) -> bool:
    line_end = payload.find(b"\n")
    line = payload if line_end == -1 else payload[:line_end]
    cursor = 0
    while True:
        colon = line.find(b":", cursor)
        if colon == -1:
            return False
        cursor = colon + 1
        while cursor < len(line) and line[cursor] in b" \t\r\n":
            cursor += 1
        if cursor >= len(line) or line[cursor] != ord("["):
            continue
        cursor += 1
        while cursor < len(line) and line[cursor] in b" \t\r\n":
            cursor += 1
        return cursor < len(line) and line[cursor] in b"-0123456789"


def _has_numeric_array_record_text(payload: str) -> bool:
    line_end = payload.find("\n")
    line = payload if line_end == -1 else payload[:line_end]
    cursor = 0
    while True:
        colon = line.find(":", cursor)
        if colon == -1:
            return False
        cursor = colon + 1
        while cursor < len(line) and line[cursor] in " \t\r\n":
            cursor += 1
        if cursor >= len(line) or line[cursor] != "[":
            continue
        cursor += 1
        while cursor < len(line) and line[cursor] in " \t\r\n":
            cursor += 1
        return cursor < len(line) and line[cursor] in "-0123456789"


def _should_use_orjson_ndjson(payload: bytes | bytearray) -> bool:
    return (
        _backend_orjson is not None
        and _GLOBAL_MSGSPEC_DECODER is not None
        and hasattr(_GLOBAL_MSGSPEC_DECODER, "decode_lines")
        and (
            (len(payload) >= _NDJSON_ORJSON_ESCAPE_THRESHOLD and _has_dense_json_escapes(payload))
            or (len(payload) >= _NDJSON_ORJSON_ARRAY_THRESHOLD and _has_numeric_array_record(payload))
        )
    )


def _should_use_orjson_ndjson_text(payload: str) -> bool:
    return (
        _backend_orjson is not None
        and _GLOBAL_MSGSPEC_DECODER is not None
        and hasattr(_GLOBAL_MSGSPEC_DECODER, "decode_lines")
        and (
            (len(payload) >= _NDJSON_ORJSON_ESCAPE_THRESHOLD and _has_dense_json_escapes_text(payload))
            or (len(payload) >= _NDJSON_ORJSON_ARRAY_THRESHOLD and _has_numeric_array_record_text(payload))
        )
    )


def _decode_ndjson_with_line_decoder(
    payload: str | bytes | bytearray,
    line_decoder: Any,
) -> list[Any]:
    separator = "\n" if isinstance(payload, str) else b"\n"
    return list(map(line_decoder, filter(None, payload.split(separator))))


def _decode_ndjson_with_orjson_text(payload: str) -> list[Any]:
    line_decoder = _backend_orjson.loads
    return list(map(line_decoder, filter(None, payload.split("\n"))))


def _decode_ndjson_with_orjson_binary(payload: bytes | bytearray) -> list[Any]:
    line_decoder = _backend_orjson.loads
    return list(map(line_decoder, filter(None, payload.split(b"\n"))))


def _make_orjson_ndjson_text_decoder() -> Any:
    line_decoder = _backend_orjson.loads

    def decode(payload: str) -> list[Any]:
        return list(map(line_decoder, filter(None, payload.split("\n"))))

    return decode


def _make_orjson_ndjson_binary_decoder() -> Any:
    line_decoder = _backend_orjson.loads

    def decode(payload: bytes | bytearray) -> list[Any]:
        return list(map(line_decoder, filter(None, payload.split(b"\n"))))

    return decode


def _decode_ndjson_with_orjson(payload: str | bytes | bytearray) -> list[Any]:
    if isinstance(payload, str):
        return _decode_ndjson_with_orjson_text(payload)
    return _decode_ndjson_with_orjson_binary(payload)


def _orjson_ndjson_decoder_for(
    payload: str | bytes | bytearray,
) -> Any:
    return (
        _make_orjson_ndjson_text_decoder()
        if isinstance(payload, str)
        else _make_orjson_ndjson_binary_decoder()
    )


def _decode_ndjson_with_yyjson(payload: str | bytes | bytearray) -> list[Any]:
    line_decoder = _backend_yyjson.loads
    return _decode_ndjson_with_line_decoder(payload, line_decoder)


def _decode_ndjson_with_ujson(payload: str | bytes | bytearray) -> list[Any]:
    line_decoder = _backend_ujson.loads
    return _decode_ndjson_with_line_decoder(payload, line_decoder)


def _decode_ndjson_with_rapidjson(payload: str | bytes | bytearray) -> list[Any]:
    line_decoder = _backend_rapidjson.loads
    return _decode_ndjson_with_line_decoder(payload, line_decoder)


def _rejects_invalid_inputs(candidate: Any, invalid_inputs: tuple[Any, ...]) -> bool:
    for invalid_payload in invalid_inputs:
        try:
            candidate(invalid_payload)
        except Exception:
            continue
        return False
    return True


def _invalid_inputs_for_probe(
    invalid_inputs: tuple[bytes, ...],
    probe_payload: str | bytes | bytearray,
) -> tuple[str | bytes | bytearray, ...]:
    if isinstance(probe_payload, str):
        return tuple(payload.decode("utf-8") for payload in invalid_inputs)
    if isinstance(probe_payload, bytearray):
        return tuple(bytearray(payload) for payload in invalid_inputs)
    return invalid_inputs


def _candidate_variants(
    candidate: Any,
    probe_payload: str | bytes | bytearray,
) -> tuple[Any, ...]:
    if isinstance(probe_payload, bytes):
        return (candidate,)
    if isinstance(probe_payload, bytearray) and (
        candidate is getattr(_backend_yyjson, "loads", None)
        or candidate is _decode_ndjson_with_yyjson
    ):
        # yyjson rejects bytearray; do not benchmark a copy-producing wrapper
        # when a direct mutable-buffer candidate is available.
        return (candidate,)

    def coerce_for_candidate(data: str | bytes | bytearray) -> Any:
        return candidate(_coerce_bytes(data))

    return (candidate, coerce_for_candidate)


def _same_callable(left: Any, right: Any) -> bool:
    if left is right:
        return True
    left_self = getattr(left, "__self__", None)
    right_self = getattr(right, "__self__", None)
    if left_self is None or left_self is not right_self:
        return False
    left_function = getattr(left, "__func__", None)
    right_function = getattr(right, "__func__", None)
    if left_function is not None or right_function is not None:
        return left_function is right_function
    return getattr(left, "__name__", None) == getattr(right, "__name__", None)


def _select_calibrated_candidate(
    payload: bytes,
    candidates: tuple[Any, ...],
    reference: Any,
    invalid_inputs: tuple[bytes, ...],
    fallback: Any,
    *,
    probe_payload: str | bytes | bytearray | None = None,
    min_speedup_ratio: float = _TUNED_MIN_SPEEDUP_RATIO,
) -> Any:
    probe = payload if probe_payload is None else probe_payload
    probe_invalid_inputs = _invalid_inputs_for_probe(invalid_inputs, probe)
    compatible: list[Any] = []
    fallback_variant: Any | None = None
    for candidate in candidates:
        for variant_index, variant in enumerate(_candidate_variants(candidate, probe)):
            try:
                if variant(probe) != reference:
                    if variant_index == 0:
                        break
                    continue
                if _rejects_invalid_inputs(variant, probe_invalid_inputs):
                    compatible.append(variant)
                    if _same_callable(candidate, fallback):
                        fallback_variant = variant
                    break
            except Exception:
                continue
            if variant_index == 0:
                # A direct candidate accepted this representation but failed
                # strict validation; converting it cannot improve semantics.
                break
    if not compatible:
        return fallback

    repetitions = min(
        _TUNED_PROBE_MAX_REPETITIONS,
        max(_TUNED_PROBE_MIN_REPETITIONS, _TUNED_PROBE_BYTE_TARGET // len(payload)),
    )
    samples_by_candidate: list[list[float]] = [[] for _ in compatible]
    for sample_index in range(_TUNED_PROBE_SAMPLES):
        for offset in range(len(compatible)):
            candidate_index = (sample_index + offset) % len(compatible)
            candidate = compatible[candidate_index]
            started = time.process_time()
            for _ in range(repetitions):
                candidate(probe)
            samples_by_candidate[candidate_index].append(
                (time.process_time() - started) / repetitions
            )
    timings = [
        (sorted(samples)[len(samples) // 2], candidate)
        for candidate, samples in zip(compatible, samples_by_candidate)
    ]
    best_time, best_candidate = min(timings, key=lambda item: item[0])
    fallback_time = next(
        (
            sample_time
            for sample_time, candidate in timings
            if candidate is fallback_variant
        ),
        None,
    )
    if (
        fallback_time is not None
        and best_candidate is not fallback_variant
        and best_time >= fallback_time * min_speedup_ratio
    ):
        return fallback_variant
    return best_candidate


def _calibrate_ndjson_decoder(
    payload: bytes,
    fallback: Any,
    *,
    probe_payload: str | bytes | bytearray | None = None,
) -> Any:
    """Choose the fastest strict line decoder for a stable representative payload."""
    if len(payload) < _TUNED_CALIBRATION_THRESHOLD:
        return fallback
    try:
        reference = [json.loads(line) for line in payload.split(b"\n") if line]
    except Exception:
        return fallback

    candidates: list[Any] = []
    if _GLOBAL_MSGSPEC_DECODER is not None and hasattr(
        _GLOBAL_MSGSPEC_DECODER, "decode_lines"
    ):
        candidates.append(_GLOBAL_MSGSPEC_DECODER.decode_lines)
    if _backend_orjson is not None:
        candidates.append(
            _orjson_ndjson_decoder_for(
                payload if probe_payload is None else probe_payload
            )
        )
    if _backend_yyjson is not None:
        candidates.append(_decode_ndjson_with_yyjson)
    if _backend_ujson is not None:
        candidates.append(_decode_ndjson_with_ujson)
    if _backend_rapidjson is not None:
        candidates.append(_decode_ndjson_with_rapidjson)

    return _select_calibrated_candidate(
        payload,
        tuple(candidates),
        reference,
        _STRICT_CALIBRATION_INVALID_LINES,
        fallback,
        probe_payload=probe_payload,
        min_speedup_ratio=_TUNED_NDJSON_MIN_SPEEDUP_RATIO,
    )


def _first_json_token(payload: bytes) -> int | None:
    for byte in payload:
        if byte not in b" \n\r\t":
            return byte
    return None


def _first_object_value_token(payload: bytes) -> int | None:
    index = 0
    while index < len(payload) and payload[index] in b" \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] != ord("{"):
        return None
    index += 1
    while index < len(payload) and payload[index] in b" \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] != ord('"'):
        return None
    index += 1

    # Most JSON keys are unescaped. Let the C-level byte search handle that
    # hot path and retain the character scan for escaped keys.
    candidate = payload.find(b'":', index)
    if candidate != -1 and payload[candidate - 1] != ord("\\"):
        index = candidate + 2
        while index < len(payload) and payload[index] in b" \n\r\t":
            index += 1
        return payload[index] if index < len(payload) else None

    escaped = False
    while index < len(payload):
        byte = payload[index]
        index += 1
        if escaped:
            escaped = False
        elif byte == ord("\\"):
            escaped = True
        elif byte == ord('"'):
            break
    while index < len(payload) and payload[index] in b" \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] != ord(":"):
        return None
    index += 1
    while index < len(payload) and payload[index] in b" \n\r\t":
        index += 1
    return payload[index] if index < len(payload) else None


def _first_array_value_token(payload: bytes) -> int | None:
    index = 0
    while index < len(payload) and payload[index] in b" \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] != ord("["):
        return None
    index += 1
    while index < len(payload) and payload[index] in b" \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] == ord("]"):
        return None
    return payload[index]


def _first_json_token_text(payload: str) -> str | None:
    for char in payload:
        if char not in " \n\r\t":
            return char
    return None


def _first_array_value_token_text(payload: str) -> str | None:
    index = 0
    while index < len(payload) and payload[index] in " \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] != "[":
        return None
    index += 1
    while index < len(payload) and payload[index] in " \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] == "]":
        return None
    return payload[index]


def _first_object_value_token_text(payload: str) -> str | None:
    index = 0
    while index < len(payload) and payload[index] in " \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] != "{":
        return None
    index += 1
    while index < len(payload) and payload[index] in " \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] != '"':
        return None
    index += 1
    candidate = payload.find("\":", index)
    if candidate != -1 and payload[candidate - 1] != "\\":
        index = candidate + 2
        while index < len(payload) and payload[index] in " \n\r\t":
            index += 1
        return payload[index] if index < len(payload) else None

    escaped = False
    while index < len(payload):
        char = payload[index]
        index += 1
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            break
    while index < len(payload) and payload[index] in " \n\r\t":
        index += 1
    if index >= len(payload) or payload[index] != ":":
        return None
    index += 1
    while index < len(payload) and payload[index] in " \n\r\t":
        index += 1
    return payload[index] if index < len(payload) else None


def _has_many_object_fields(payload: bytes) -> bool:
    # Wide-object dispatch only needs a positive signal; avoid scanning a
    # megabyte-sized single-field string object before the real decoder runs.
    probe_end = min(len(payload), _ORJSON_WIDE_OBJECT_PROBE_BYTES)
    return payload.count(b":", 0, probe_end) >= _ORJSON_WIDE_OBJECT_FIELDS


def _has_many_object_fields_text(payload: str) -> bool:
    probe_end = min(len(payload), _ORJSON_WIDE_OBJECT_PROBE_BYTES)
    return payload.count(":", 0, probe_end) >= _ORJSON_WIDE_OBJECT_FIELDS


def _is_numeric_array_data(data: str | bytes | bytearray) -> bool:
    if isinstance(data, str):
        stripped = data.lstrip(" \n\r\t")
        if not stripped.startswith("["):
            return False
        value = stripped[1:].lstrip(" \n\r\t")
        return bool(value) and value[0] in "-0123456789"
    payload = data if isinstance(data, bytes) else bytes(data)
    return _first_array_value_token(payload) in _NUMERIC_JSON_BYTES


def _is_root_scalar_prefix(data: str | bytes | bytearray) -> bool:
    if isinstance(data, str):
        token = _first_json_token_text(data)
        return token is not None and token in "-0123456789tfn"
    payload = data if isinstance(data, bytes) else bytes(data)
    token = _first_json_token(payload)
    return token is not None and token in b"-0123456789tfn"


def _is_root_string_prefix(data: str | bytes | bytearray) -> bool:
    if isinstance(data, str):
        return _first_json_token_text(data) == '"'
    payload = data if isinstance(data, bytes) else data
    return _first_json_token(payload) == ord('"')


def _is_incomplete_root_scalar(data: str | bytes | bytearray) -> bool:
    if isinstance(data, str):
        first = _first_json_token_text(data)
        if first is None or first not in "-0123456789tfn":
            return False
        stripped = data.strip(" \n\r\t")
        if first in "tfn":
            return any(
                stripped != literal and literal.startswith(stripped)
                for literal in ("true", "false", "null")
            )
        return first in "-0123456789" and stripped[-1] in "-.eE+"

    payload = data if isinstance(data, (bytes, bytearray)) else bytes(data)
    first = _first_json_token(payload)
    if first is None or first not in b"-0123456789tfn":
        return False
    stripped = payload.strip(b" \n\r\t")
    if first in b"tfn":
        return any(
            stripped != literal and literal.startswith(stripped)
            for literal in (b"true", b"false", b"null")
        )
    return first in b"-0123456789" and stripped[-1:] in (
        b"-", b".", b"e", b"E", b"+"
    )


def _should_use_jiter_structural_text(
    data: str,
    *,
    trailing_strings: bool = False,
) -> bool:
    if _backend_jiter is None:
        return False
    if trailing_strings and _is_root_scalar_prefix(data):
        return False
    stripped = data.lstrip(" \n\r\t")
    if stripped and stripped[0] in "-0123456789":
        return True
    if stripped.startswith("[") and _is_numeric_array_data(data):
        return True
    if len(data) < _STRUCTURAL_JITER_TEXT_THRESHOLD:
        return False
    return not data.isascii() or "\\" in data or stripped.startswith("[")


def _should_use_jiter_structural_bytearray(
    data: bytes | bytearray,
    *,
    trailing_strings: bool = False,
) -> bool:
    if trailing_strings and _is_root_scalar_prefix(data):
        return False
    payload = data if isinstance(data, bytes) else bytes(data)
    first_token = _first_json_token(payload)
    if first_token is None:
        return False
    if first_token in b"-0123456789tfn[":
        return True
    if not payload.isascii() or b"\\" in payload:
        return True
    return len(payload) >= _STRUCTURAL_JITER_BYTEARRAY_OBJECT_THRESHOLD


def _is_incomplete_root_string(payload: str | bytes | bytearray) -> bool:
    if isinstance(payload, str):
        stripped = payload.strip(" \n\r\t")
        quote = '"'
        if not stripped.startswith(quote):
            return False
        if "\\" not in stripped:
            return stripped.count(quote) == 1
        escaped = False
        for char in stripped[1:]:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                return False
            elif ord(char) < 0x20:
                return False
        return True

    data = payload if isinstance(payload, bytes) else bytes(payload)
    stripped = data.strip(b" \n\r\t")
    if not stripped.startswith(b'"'):
        return False
    if b"\\" not in stripped:
        return stripped.count(b'"') == 1
    escaped = False
    for byte in stripped[1:]:
        if escaped:
            escaped = False
        elif byte == ord("\\"):
            escaped = True
        elif byte == ord('"'):
            return False
        elif byte < 0x20:
            return False
    return True


def _has_unescaped_trailing_quote(payload: str | bytes | bytearray) -> bool:
    if isinstance(payload, str):
        stripped = payload.rstrip(" \n\r\t")
        quote = '"'
        if len(stripped) < 2 or not stripped.endswith(quote):
            return False
        index = len(stripped) - 2
        backslashes = 0
        while index >= 0 and stripped[index] == "\\":
            backslashes += 1
            index -= 1
        return backslashes % 2 == 0
    data = payload if isinstance(payload, bytes) else bytes(payload)
    stripped = data.rstrip(b" \n\r\t")
    if len(stripped) < 2 or not stripped.endswith(b'"'):
        return False
    index = len(stripped) - 2
    backslashes = 0
    while index >= 0 and stripped[index] == ord("\\"):
        backslashes += 1
        index -= 1
    return backslashes % 2 == 0


def _should_probe_structural_completion(
    payload: str | bytes | bytearray,
) -> bool:
    """Use strict decoding when the prefix contains a possible root close."""
    if isinstance(payload, str):
        if payload and payload[0] not in " \n\r\t":
            first = payload[0]
            if first in "tfn-0123456789":
                return True
            if first == '"':
                return '"' in payload[1:]
            if first == "{":
                return "}" in payload[1:]
            if first == "[":
                return "]" in payload[1:]
            return False
        stripped = payload.lstrip(" \n\r\t")
        if not stripped:
            return False
        first = stripped[0]
        if first in "tfn-0123456789":
            return True
        if first == '"':
            return '"' in stripped[1:]
        if first == "{":
            return "}" in stripped[1:]
        if first == "[":
            return "]" in stripped[1:]
        return False

    data = payload if isinstance(payload, bytes) else bytes(payload)
    if data and data[0] not in b" \n\r\t":
        first = data[0]
        if first in b"tfn-0123456789":
            return True
        if first == ord('"'):
            return ord('"') in data[1:]
        if first == ord("{"):
            return ord("}") in data[1:]
        if first == ord("["):
            return ord("]") in data[1:]
        return False
    stripped = data.lstrip(b" \n\r\t")
    if not stripped:
        return False
    first = stripped[0]
    if first in b"tfn-0123456789":
        return True
    if first == ord('"'):
        return ord('"') in stripped[1:]
    if first == ord("{"):
        return ord("}") in stripped[1:]
    if first == ord("["):
        return ord("]") in stripped[1:]
    return False


def _is_structural_eof_error(error: ValueError) -> bool:
    return str(error).startswith("EOF while parsing")


def _decode_pydantic_structural(
    payload: str | bytes | bytearray,
    *,
    allow_partial: bool | str,
) -> Any:
    backend = _backend_pydantic_from_json
    if not _should_probe_structural_completion(payload):
        return backend(payload, allow_partial=allow_partial)
    try:
        return backend(payload, allow_partial=False)
    except ValueError as error:
        if not _is_structural_eof_error(error):
            raise
        return backend(payload, allow_partial=allow_partial)


def _decode_jiter_structural(
    payload: bytes,
    *,
    allow_partial: bool | str,
) -> Any:
    backend = _backend_jiter.from_json
    if not _should_probe_structural_completion(payload):
        return backend(payload, partial_mode=allow_partial)
    try:
        return backend(payload, partial_mode=False)
    except ValueError as error:
        if not _is_structural_eof_error(error):
            raise
        return backend(payload, partial_mode=allow_partial)


def _is_flat_string_object(payload: bytes, first_value_token: int | None) -> bool:
    if first_value_token != ord('"'):
        return False
    # Bounded probes avoid making one-shot dispatch scan a large string twice.
    # A nested tail is still rejected in the common mixed-document shapes.
    probes = (payload,) if len(payload) <= 8192 else (payload[:4096], payload[-4096:])
    return (
        sum(probe.count(b"{") for probe in probes) == 1
        and all(b"[" not in probe for probe in probes)
    )


def _is_flat_string_object_text(payload: str, first_value_token: str | None) -> bool:
    if first_value_token != '"':
        return False
    probes = (payload,) if len(payload) <= 8192 else (payload[:4096], payload[-4096:])
    return (
        sum(probe.count("{") for probe in probes) == 1
        and all("[" not in probe for probe in probes)
    )


def _decode_pending_utf8(payload: bytes) -> tuple[str, bytes]:
    try:
        return payload.decode("utf-8"), b""
    except UnicodeDecodeError as exc:
        if exc.reason != "unexpected end of data" or exc.end != len(payload):
            raise
        split_at = exc.start
        return payload[:split_at].decode("utf-8"), payload[split_at:]


def _has_complete_root_boundary(payload: str | bytes | bytearray) -> bool:
    if len(payload) >= _ROOT_BOUNDARY_SCAN_THRESHOLD:
        raw = payload if isinstance(payload, (bytes, bytearray)) else payload.encode("utf-8")
        first = _first_json_token(raw)
        stripped = raw.rstrip(b" \n\r\t")
        if first == ord("{") and raw.count(b"{") == 1 and raw.count(b"[") == 0:
            return bool(stripped) and stripped[-1] == ord("}")
        if first == ord("[") and raw.count(b"[") == 1 and raw.count(b"{") == 0:
            return bool(stripped) and stripped[-1] == ord("]")
    if (
        len(payload) >= _ROOT_BOUNDARY_SCAN_THRESHOLD
        and _backend_native is not None
        and hasattr(_backend_native, "is_complete_document")
    ):
        return bool(_backend_native.is_complete_document(_coerce_bytes(payload)))
    byte_payload = isinstance(payload, (bytes, bytearray))
    if isinstance(payload, str):
        whitespace = " \n\r\t"
        length = len(payload)

        def at(index: int) -> str:
            return payload[index]

        def is_whitespace(value: str) -> bool:
            return value in whitespace

        quote = '"'
        opening = {"{": "}", "[": "]"}
    else:
        whitespace = b" \n\r\t"
        length = len(payload)

        def at(index: int) -> int:
            return payload[index]

        def is_whitespace(value: int) -> bool:
            return value in whitespace

        quote = ord('"')
        opening = {ord("{"): ord("}"), ord("["): ord("]")}

    index = 0
    while index < length and is_whitespace(at(index)):
        index += 1
    if index >= length:
        return False

    first = at(index)
    if first == quote:
        escaped = False
        index += 1
        while index < length:
            current = at(index)
            index += 1
            if escaped:
                escaped = False
            elif current == (ord("\\") if byte_payload else "\\"):
                escaped = True
            elif current == quote:
                return all(is_whitespace(at(rest)) for rest in range(index, length))
        return False

    expected_closes = []
    if first not in opening:
        return False
    expected_closes.append(opening[first])
    index += 1
    escaped = False
    in_string = False
    while index < length:
        current = at(index)
        index += 1
        if in_string:
            if escaped:
                escaped = False
            elif current == (ord("\\") if byte_payload else "\\"):
                escaped = True
            elif current == quote:
                in_string = False
            continue
        if current == quote:
            in_string = True
            continue
        if current in opening:
            expected_closes.append(opening[current])
            continue
        if current == expected_closes[-1]:
            expected_closes.pop()
            if not expected_closes:
                return all(is_whitespace(at(rest)) for rest in range(index, length))
            continue
        if current == (ord("}") if byte_payload else "}") or current == (
            ord("]") if byte_payload else "]"
        ):
            return False
    return False


def _may_be_complete(payload: str | bytes | bytearray, *, allow_scalars: bool = False) -> bool:
    if not payload:
        return False
    if isinstance(payload, str):
        stripped = payload.strip(" \n\r\t")
        if not stripped:
            return False
        if not allow_scalars and stripped[-1] not in "}]\"":
            return False
    else:
        stripped = payload.strip(b" \n\r\t")
        if not stripped:
            return False
        if not allow_scalars and stripped[-1] not in b'}]"':
            return False
    if _has_closed_root_hint(payload):
        return True
    if _has_complete_root_boundary(payload):
        return True
    return bool(allow_scalars and stripped)


def _has_closed_root_hint(payload: str | bytes | bytearray) -> bool:
    if len(payload) >= _ROOT_BOUNDARY_SCAN_THRESHOLD:
        return False
    return _has_closed_root_suffix_hint(payload)


def _has_closed_root_suffix_hint(payload: str | bytes | bytearray) -> bool:
    if isinstance(payload, str):
        stripped = payload.strip(" \n\r\t")
        if len(stripped) < 2:
            return False
        first, last = stripped[0], stripped[-1]
        return (first, last) in {("{", "}"), ("[", "]"), ('"', '"')}
    stripped = payload.strip(b" \n\r\t")
    if len(stripped) < 2:
        return False
    first, last = stripped[0], stripped[-1]
    return (first, last) in {
        (ord("{"), ord("}")),
        (ord("["), ord("]")),
        (ord('"'), ord('"')),
    }


def _decode_simdjson_bytes(payload: bytes) -> Any:
    parsed = _GLOBAL_SIMD_PARSER.parse(payload)
    if hasattr(parsed, "as_dict"):
        return parsed.as_dict()
    if hasattr(parsed, "as_list"):
        return parsed.as_list()
    return parsed


def _complete_decoder_candidates(payload: bytes) -> tuple[Any, ...]:
    candidates: list[Any] = []

    def add(candidate: Any | None) -> None:
        if candidate is not None and not any(candidate is existing for existing in candidates):
            candidates.append(candidate)

    if _GLOBAL_MSGSPEC_DECODER is not None:
        add(_GLOBAL_MSGSPEC_DECODER.decode)
    if _backend_orjson is not None:
        add(_backend_orjson.loads)
    if _backend_yyjson is not None:
        add(_backend_yyjson.loads)
    if _backend_ujson is not None:
        add(_backend_ujson.loads)
    if _backend_rapidjson is not None:
        add(_backend_rapidjson.loads)
    if (
        _backend_native is not None
        and hasattr(_backend_native, "decode_complete")
    ):
        add(_backend_native.decode_complete)
    if _GLOBAL_SIMD_PARSER is not None:
        add(_decode_simdjson_bytes)
    return tuple(candidates)


def _calibrate_complete_decoder(
    payload: bytes,
    fallback: Any,
    *,
    probe_payload: str | bytes | bytearray | None = None,
) -> Any:
    """Choose the fastest strict decoder for a stable representative payload."""
    if len(payload) < _TUNED_CALIBRATION_THRESHOLD:
        return fallback
    try:
        reference = json.loads(payload)
    except Exception:
        return fallback

    return _select_calibrated_candidate(
        payload,
        _complete_decoder_candidates(payload),
        reference,
        _STRICT_CALIBRATION_INVALID_DOCUMENTS,
        fallback,
        probe_payload=probe_payload,
    )


def _select_complete_decoder(
    payload: bytes | bytearray,
    value_type: Any | None = None,
) -> Any:
    if value_type is not None:
        decoder = _get_cached_msgspec_decoder(value_type)
        if decoder is not None:
            return decoder.decode
    if b"\\" in payload and _has_dense_json_escapes(payload):
        if (
            _backend_yyjson is not None
            and isinstance(payload, bytes)
            and payload.isascii()
            and not _has_non_ascii_unicode_escape(payload)
        ):
            return _backend_yyjson.loads
        if _backend_orjson is not None:
            return _backend_orjson.loads
    first_token = _first_json_token(payload)
    if (
        _backend_orjson is not None
        and first_token == ord("{")
        and _has_many_object_fields(payload)
    ):
        return _backend_orjson.loads
    first_array_value_token = (
        _first_array_value_token(payload)
        if first_token == ord("[")
        else None
    )
    if (
        _backend_orjson is not None
        and first_array_value_token == ord("[")
    ):
        return _backend_orjson.loads
    if len(payload) < _ORJSON_TINY_THRESHOLD:
        if (
            _backend_orjson is not None
            and first_array_value_token is not None
            and first_array_value_token in _NUMERIC_JSON_BYTES
        ):
            return _backend_orjson.loads
        if _GLOBAL_MSGSPEC_DECODER is not None:
            return _GLOBAL_MSGSPEC_DECODER.decode
        if _backend_orjson is not None:
            return _backend_orjson.loads
    if (
        _backend_orjson is not None
        and first_token == ord("[")
        and len(payload) < _ORJSON_ARRAY_THRESHOLD
    ):
        return _backend_orjson.loads
    first_value_token = (
        _first_object_value_token(payload)
        if first_token == ord("{")
        else None
    )
    if first_token != ord("[") or len(payload) < _ORJSON_ARRAY_THRESHOLD:
        first_array_value_token = None
    if (
        _backend_orjson is not None
        and first_token == ord("{")
        and first_value_token == ord('"')
        and not payload.isascii()
        and _is_flat_string_object(payload, first_value_token)
    ):
        return _backend_orjson.loads
    if (
        _backend_native is not None
        and hasattr(_backend_native, "decode_complete")
        and (
            (
                first_token == ord('"')
                and len(payload) >= _NATIVE_ROOT_STRING_THRESHOLD
                and payload.isascii()
            )
            or (
                first_token == ord("{")
                and len(payload) >= _NATIVE_FLAT_STRING_OBJECT_THRESHOLD
                and _is_flat_string_object(payload, first_value_token)
                and payload.isascii()
            )
        )
    ):
        return _backend_native.decode_complete
    if _backend_orjson is not None and (
        (
            first_token == ord("[")
            and (
                len(payload) < _ORJSON_ARRAY_THRESHOLD
                or first_array_value_token == ord("[")
                or (
                    first_array_value_token is not None
                    and first_array_value_token in _NUMERIC_JSON_BYTES
                )
            )
        )
        or (
            first_token == ord("{")
            and first_value_token in {ord("["), ord("{")}
        )
    ):
        return _backend_orjson.loads
    if _GLOBAL_MSGSPEC_DECODER is not None:
        return _GLOBAL_MSGSPEC_DECODER.decode
    if _GLOBAL_SIMD_PARSER is not None:
        return _decode_simdjson_bytes
    if (
        _backend_yyjson is not None
        and payload.isascii()
        and not _has_non_ascii_unicode_escape(payload)
    ):
        return _backend_yyjson.loads
    if _backend_orjson is not None:
        return _backend_orjson.loads
    if _backend_native is not None and hasattr(_backend_native, "decode_complete"):
        return _backend_native.decode_complete
    return json.loads


def _select_complete_decoder_text(data: str, value_type: Any | None = None) -> Any:
    if value_type is not None:
        decoder = _get_cached_msgspec_decoder(value_type)
        if decoder is not None:
            return decoder.decode
    if "\\" in data and _has_dense_json_escapes_text(data):
        if (
            _backend_yyjson is not None
            and data.isascii()
            and not _has_non_ascii_unicode_escape(data)
        ):
            return _backend_yyjson.loads
        if _backend_orjson is not None:
            return _backend_orjson.loads
    first_token = _first_json_token_text(data)
    if (
        _backend_orjson is not None
        and first_token == "{"
        and _has_many_object_fields_text(data)
    ):
        return _backend_orjson.loads
    first_array_value_token = (
        _first_array_value_token_text(data)
        if first_token == "["
        else None
    )
    if (
        _backend_orjson is not None
        and first_array_value_token == "["
    ):
        return _backend_orjson.loads
    if len(data) < _ORJSON_TINY_THRESHOLD:
        if (
            _backend_orjson is not None
            and first_array_value_token is not None
            and first_array_value_token in "-0123456789"
        ):
            return _backend_orjson.loads
        if _GLOBAL_MSGSPEC_DECODER is not None:
            return _GLOBAL_MSGSPEC_DECODER.decode
        if _backend_orjson is not None:
            return _backend_orjson.loads
    if (
        _backend_orjson is not None
        and first_token == "["
        and len(data) < _ORJSON_ARRAY_THRESHOLD
    ):
        return _backend_orjson.loads
    first_value_token = (
        _first_object_value_token_text(data)
        if first_token == "{"
        else None
    )
    if first_token != "[" or len(data) < _ORJSON_ARRAY_THRESHOLD:
        first_array_value_token = None
    if (
        _backend_orjson is not None
        and first_token == "{"
        and first_value_token == '"'
        and not data.isascii()
        and _is_flat_string_object_text(data, first_value_token)
    ):
        return _backend_orjson.loads
    if (
        _backend_native is not None
        and hasattr(_backend_native, "decode_complete")
        and (
            (
                first_token == '"'
                and len(data) >= _NATIVE_ROOT_STRING_THRESHOLD
                and data.isascii()
            )
            or (
                first_token == "{"
                and len(data) >= _NATIVE_FLAT_STRING_TEXT_THRESHOLD
                and _is_flat_string_object_text(data, first_value_token)
                and data.isascii()
            )
        )
    ):
        return _backend_native.decode_complete
    if _backend_orjson is not None and (
        (
            first_token == "["
            and (
                len(data) < _ORJSON_ARRAY_THRESHOLD
                or first_array_value_token == "["
                or (
                    first_array_value_token is not None
                    and first_array_value_token in "-0123456789"
                )
            )
        )
        or (
            first_token == "{"
            and first_value_token in {"[", "{"}
        )
    ):
        return _backend_orjson.loads
    if _GLOBAL_MSGSPEC_DECODER is not None:
        return _GLOBAL_MSGSPEC_DECODER.decode
    if _GLOBAL_SIMD_PARSER is not None:
        return _decode_simdjson_bytes
    if (
        _backend_yyjson is not None
        and data.isascii()
        and not _has_non_ascii_unicode_escape(data)
    ):
        return _backend_yyjson.loads
    if _backend_orjson is not None:
        return _backend_orjson.loads
    if _backend_native is not None and hasattr(_backend_native, "decode_complete"):
        return _backend_native.decode_complete
    return json.loads


def _decode_complete_bytes(payload: bytes, value_type: Any | None = None) -> Any:
    if (
        value_type is None
        and len(payload) < _ORJSON_TINY_THRESHOLD
    ):
        if (
            _backend_orjson is not None
            and b"\\" in payload
            and _has_dense_json_escapes(payload)
        ):
            return _backend_orjson.loads(payload)
        if _GLOBAL_MSGSPEC_DECODER is not None:
            return _GLOBAL_MSGSPEC_DECODER.decode(payload)
        if _backend_orjson is not None:
            return _backend_orjson.loads(payload)
    return _select_complete_decoder(payload, value_type=value_type)(payload)


def _invoke_complete_decoder(
    decoder: Any,
    data: str | bytes | bytearray,
    payload: bytes | bytearray,
) -> Any:
    if isinstance(data, bytes):
        return decoder(payload)
    try:
        return decoder(data)
    except TypeError:
        if isinstance(data, bytearray):
            return decoder(bytes(data))
        return decoder(payload)


def decode_complete_json(data: str | bytes | bytearray, *, value_type: Any | None = None) -> Any:
    # Scalar roots have no shape information to inspect. Keep this path below
    # the generic dispatcher so tiny scalar calls pay only the strict decoder
    # selection cost, while larger strings still reach native shape routing.
    if value_type is None and _GLOBAL_MSGSPEC_DECODER is not None:
        if isinstance(data, str):
            if (
                len(data) < _ORJSON_TINY_THRESHOLD
                and data
                and data[0] in '-0123456789tfn"'
            ):
                return _GLOBAL_MSGSPEC_DECODER.decode(data)
        elif isinstance(data, bytes):
            if (
                len(data) < _ORJSON_TINY_THRESHOLD
                and data
                and data[0] in b'-0123456789tfn"'
            ):
                return _GLOBAL_MSGSPEC_DECODER.decode(data)
    # Avoid the adaptive probe when the established tiny-payload winner is
    # already known and the input can be passed through without conversion.
    if value_type is None and isinstance(data, str) and len(data) < _ORJSON_TINY_THRESHOLD:
        msgspec_decode = (
            _GLOBAL_MSGSPEC_DECODER.decode
            if _GLOBAL_MSGSPEC_DECODER is not None
            else None
        )
        orjson_loads = (
            _backend_orjson.loads if _backend_orjson is not None else None
        )
        first = data[0] if data else ""
        if (
            orjson_loads is not None
            and first == "{"
            and "\\" in data
            and _has_dense_json_escapes_text(data)
        ):
            return orjson_loads(data)
        if (
            orjson_loads is not None
            and first == "["
            and _first_array_value_token_text(data) == "["
        ):
            return orjson_loads(data)
        if (
            orjson_loads is not None
            and first == "["
            and _is_numeric_array_data(data)
        ):
            return orjson_loads(data)
        if msgspec_decode is not None:
            return msgspec_decode(data)
        if orjson_loads is not None:
            return orjson_loads(data)
    elif value_type is None and isinstance(data, bytes) and len(data) < _ORJSON_TINY_THRESHOLD:
        msgspec_decode = (
            _GLOBAL_MSGSPEC_DECODER.decode
            if _GLOBAL_MSGSPEC_DECODER is not None
            else None
        )
        orjson_loads = (
            _backend_orjson.loads if _backend_orjson is not None else None
        )
        first = data[0] if data else None
        if (
            orjson_loads is not None
            and first == ord("{")
            and b"\\" in data
            and _has_dense_json_escapes(data)
        ):
            return orjson_loads(data)
        if (
            orjson_loads is not None
            and first == ord("[")
            and _first_array_value_token(data) == ord("[")
        ):
            return orjson_loads(data)
        if (
            orjson_loads is not None
            and first == ord("[")
            and _is_numeric_array_data(data)
        ):
            return orjson_loads(data)
        if msgspec_decode is not None:
            return msgspec_decode(data)
        if orjson_loads is not None:
            return orjson_loads(data)
    elif value_type is None and isinstance(data, bytearray) and len(data) < _ORJSON_TINY_THRESHOLD:
        if (
            _backend_orjson is not None
            and _first_json_token(data) == ord("[")
            and _first_array_value_token(data) == ord("[")
        ):
            return _backend_orjson.loads(data)
        if _GLOBAL_MSGSPEC_DECODER is not None:
            return _GLOBAL_MSGSPEC_DECODER.decode(data)
        if _backend_orjson is not None:
            return _backend_orjson.loads(data)
    # Scalar and root-string documents have no container shape to inspect.
    # Avoid paying the general dispatcher probes for the common sub-native-size
    # cases while preserving the native route for large ASCII root strings.
    if value_type is None and _GLOBAL_MSGSPEC_DECODER is not None:
        if isinstance(data, str):
            first_token = _first_json_token_text(data)
            if first_token is not None and (
                first_token in "-0123456789tfn"
                or (
                    first_token == '"'
                    and len(data) < _NATIVE_ROOT_STRING_THRESHOLD
                )
            ):
                return _GLOBAL_MSGSPEC_DECODER.decode(data)
        elif isinstance(data, bytes):
            first_token = _first_json_token(data)
            if first_token is not None and (
                first_token in b"-0123456789tfn"
                or (
                    first_token == ord('"')
                    and len(data) < _NATIVE_ROOT_STRING_THRESHOLD
                )
            ):
                return _GLOBAL_MSGSPEC_DECODER.decode(data)
        elif isinstance(data, bytearray):
            payload = data
            first_token = _first_json_token(payload)
            if first_token is not None and (
                first_token in b"-0123456789tfn"
                or (
                    first_token == ord('"')
                    and len(payload) < _NATIVE_ROOT_STRING_THRESHOLD
                )
            ):
                return _GLOBAL_MSGSPEC_DECODER.decode(data)
    if isinstance(data, str):
        decoder = _select_complete_decoder_text(data, value_type=value_type)
        try:
            return decoder(data)
        except TypeError:
            return decoder(_coerce_bytes(data))
    payload = data if isinstance(data, bytearray) else _coerce_bytes(data)
    decoder = _select_complete_decoder(payload, value_type=value_type)
    return _invoke_complete_decoder(decoder, data, payload)


def decode_structural_partial_json(
    data: str | bytes | bytearray,
    *,
    trailing_strings: bool = False,
) -> Any:
    """Decode an available structural prefix with optional trailing strings."""
    if _backend_pydantic_from_json is None:
        raise RuntimeError("pydantic-core is required for structural partial decoding")
    if trailing_strings is False:
        allow_partial = True
    else:
        if not isinstance(trailing_strings, bool):
            raise TypeError("trailing_strings must be a bool")
        if not _PYDANTIC_TRAILING_STRINGS:
            raise RuntimeError(
                "pydantic-core with trailing string support is required for "
                "trailing_strings=True"
            )
        allow_partial = "trailing-strings"
    if isinstance(data, str):
        stripped = data.lstrip(" \n\r\t")
        first = stripped[0] if stripped else None
        if first is None:
            return None
        if first == "{" and _looks_plain_ascii_text(data):
            return _decode_pydantic_structural(data, allow_partial=allow_partial)
        if first == "{" and len(data) < _STRUCTURAL_JITER_TEXT_THRESHOLD:
            return _decode_pydantic_structural(data, allow_partial=allow_partial)
        if (
            first == "["
            and _backend_jiter is not None
            and _is_numeric_array_data(data)
        ):
            return _decode_jiter_structural(
                data.encode("utf-8"), allow_partial=allow_partial
            )
        if first in "-0123456789tfn":
            scalar = data.strip(" \n\r\t")
            if first in "tfn":
                if any(
                    scalar != literal and literal.startswith(scalar)
                    for literal in ("true", "false", "null")
                ):
                    return None
            elif scalar[-1:] in "-.eE+":
                return None
            return _decode_pydantic_structural(data, allow_partial=allow_partial)
        if first == '"':
            if _has_unescaped_trailing_quote(data):
                if _looks_plain_ascii_text(data):
                    return _decode_pydantic_structural(
                        data, allow_partial=allow_partial
                    )
                return _decode_structural_text(data, trailing_strings=trailing_strings)
            if not trailing_strings and _is_incomplete_root_string(data):
                return None
            return _decode_structural_text(data, trailing_strings=trailing_strings)
        return _decode_structural_text(data, trailing_strings=trailing_strings)
    payload = data if isinstance(data, (bytes, bytearray)) else bytes(data)
    first = _first_json_token(payload)
    if first is None:
        return None
    if (
        first == ord("{")
        and len(payload) >= _STRUCTURAL_JITER_BYTEARRAY_OBJECT_THRESHOLD
        and _backend_jiter is not None
    ):
        if isinstance(data, bytes):
            return _decode_jiter_structural(data, allow_partial=allow_partial)
        return _decode_jiter_structural(bytes(payload), allow_partial=allow_partial)
    if (
        first == ord("{")
        and len(payload) < _STRUCTURAL_JITER_BYTEARRAY_OBJECT_THRESHOLD
    ):
        return _decode_pydantic_structural(data, allow_partial=allow_partial)
    if first == ord("[") and _backend_jiter is not None:
        return _decode_jiter_structural(
            payload if isinstance(payload, bytes) else bytes(payload),
            allow_partial=allow_partial,
        )
    if first in b"-0123456789tfn":
        scalar = payload.strip(b" \n\r\t")
        if first in b"tfn":
            if any(
                scalar != literal and literal.startswith(scalar)
                for literal in (b"true", b"false", b"null")
            ):
                return None
        elif scalar[-1:] in (b"-", b".", b"e", b"E", b"+"):
            return None
        return _decode_pydantic_structural(data, allow_partial=allow_partial)
    if first == ord('"'):
        if _has_unescaped_trailing_quote(payload):
            if len(payload) < _STRUCTURAL_JITER_BYTEARRAY_OBJECT_THRESHOLD:
                return _decode_pydantic_structural(data, allow_partial=allow_partial)
        elif not trailing_strings and _is_incomplete_root_string(payload):
            return None
    if isinstance(data, bytes) and _backend_jiter is not None:
        if _should_use_jiter_structural_bytearray(
            data,
            trailing_strings=trailing_strings,
        ):
            return _decode_jiter_structural(data, allow_partial=allow_partial)
        return _decode_pydantic_structural(data, allow_partial=allow_partial)
    if _backend_jiter is not None and _should_use_jiter_structural_bytearray(
        data,
        trailing_strings=trailing_strings,
    ):
        return _decode_jiter_structural(
            payload if isinstance(payload, bytes) else bytes(payload),
            allow_partial=allow_partial,
        )
    return _decode_pydantic_structural(
        data if isinstance(data, bytearray) else payload,
        allow_partial=allow_partial,
    )


def _decode_pydantic_partial(data: str | bytes | bytearray) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    return _decode_pydantic_structural(data, allow_partial=True)


def _decode_pydantic_trailing_strings(data: str | bytes | bytearray) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    return _decode_pydantic_structural(data, allow_partial="trailing-strings")


def _make_native_structural_partial_decoder(allow_partial: bool | str) -> Any | None:
    if not _NATIVE_FACADE_AVAILABLE:
        return None
    if allow_partial not in (True, "trailing-strings"):
        raise ValueError("unsupported structural partial mode")

    native = _NATIVE_FACADE_TYPE()
    native.configure_statuses(
        ParseStatus.EMPTY,
        ParseStatus.PARTIAL,
        ParseStatus.COMPLETE,
        ParseStatus.INVALID,
    )
    native.configure_partial_mode(allow_partial == "trailing-strings", True)

    def decode(data: str | bytes | bytearray) -> Any:
        try:
            result = native.feed(data)
            if result.status is ParseStatus.INVALID:
                raise ValueError(result.error or "invalid JSON")
            if result.status is ParseStatus.PARTIAL and _is_incomplete_root_scalar(data):
                return None
            return result.value
        finally:
            native.reset()

    return decode


def _make_pydantic_partial_decoder(allow_partial: bool | str) -> Any:
    backend = _backend_pydantic_from_json

    def decode(data: str | bytes | bytearray) -> Any:
        if not _should_probe_structural_completion(data):
            return backend(data, allow_partial=allow_partial)
        try:
            return backend(data, allow_partial=False)
        except ValueError as error:
            if not _is_structural_eof_error(error):
                raise
            return backend(data, allow_partial=allow_partial)

    return decode


def _make_jiter_partial_bytes_decoder(allow_partial: bool | str) -> Any:
    backend = _backend_jiter.from_json

    def decode(data: bytes) -> Any:
        if not _should_probe_structural_completion(data):
            return backend(data, partial_mode=allow_partial)
        try:
            return backend(data, partial_mode=False)
        except ValueError as error:
            if not _is_structural_eof_error(error):
                raise
            return backend(data, partial_mode=allow_partial)

    return decode


def _make_jiter_partial_text_decoder(allow_partial: bool | str) -> Any:
    backend = _backend_jiter.from_json

    def decode(data: str) -> Any:
        payload = data.encode("utf-8")
        if not _should_probe_structural_completion(data):
            return backend(payload, partial_mode=allow_partial)
        try:
            return backend(payload, partial_mode=False)
        except ValueError as error:
            if not _is_structural_eof_error(error):
                raise
            return backend(payload, partial_mode=allow_partial)

    return decode


def _make_jiter_partial_bytearray_decoder(allow_partial: bool | str) -> Any:
    backend = _backend_jiter.from_json

    def decode(data: bytearray) -> Any:
        payload = bytes(data)
        if not _should_probe_structural_completion(payload):
            return backend(payload, partial_mode=allow_partial)
        try:
            return backend(payload, partial_mode=False)
        except ValueError as error:
            if not _is_structural_eof_error(error):
                raise
            return backend(payload, partial_mode=allow_partial)

    return decode


def _decode_jiter_partial(data: str | bytes | bytearray) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    payload = data if isinstance(data, (bytes, bytearray)) else data.encode("utf-8")
    return _decode_jiter_structural(bytes(payload), allow_partial=True)


def _decode_jiter_trailing_strings(data: str | bytes | bytearray) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    payload = data if isinstance(data, (bytes, bytearray)) else data.encode("utf-8")
    return _decode_jiter_structural(
        bytes(payload), allow_partial="trailing-strings"
    )


def _decode_jiter_partial_text(data: str) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    return _decode_jiter_structural(data.encode("utf-8"), allow_partial=True)


def _decode_jiter_trailing_strings_text(data: str) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    return _decode_jiter_structural(
        data.encode("utf-8"), allow_partial="trailing-strings"
    )


def _decode_jiter_partial_bytes(data: bytes) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    return _decode_jiter_structural(data, allow_partial=True)


def _decode_jiter_partial_bytearray(data: bytearray) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    return _decode_jiter_structural(bytes(data), allow_partial=True)


def _decode_jiter_trailing_strings_bytes(data: bytes) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    return _decode_jiter_structural(data, allow_partial="trailing-strings")


def _decode_jiter_trailing_strings_bytearray(data: bytearray) -> Any:
    if _is_incomplete_root_scalar(data):
        return None
    return _decode_jiter_structural(
        bytes(data), allow_partial="trailing-strings"
    )


def _calibrate_structural_partial_decoder(
    sample: str | bytes | bytearray,
    *,
    allow_partial: bool | str,
) -> Any | None:
    if _backend_jiter is None and not _NATIVE_FACADE_AVAILABLE:
        return None
    payload = _coerce_bytes(sample)
    if len(payload) < _STRUCTURAL_TUNED_CALIBRATION_THRESHOLD:
        return None
    root_string = allow_partial is True and _is_incomplete_root_string(sample)
    root_scalar = _is_root_scalar_prefix(sample)

    if root_string:
        def decode_pydantic(data: str | bytes | bytearray) -> Any:
            if _is_incomplete_root_string(data):
                return None
            return _decode_pydantic_structural(data, allow_partial=allow_partial)

        def decode_jiter(data: str | bytes | bytearray) -> Any:
            if _is_incomplete_root_string(data):
                return None
            return _decode_jiter_structural(
                data if isinstance(data, bytes) else _coerce_bytes(data),
                allow_partial=allow_partial,
            )
    else:
        decode_pydantic = (
            _decode_pydantic_partial
            if allow_partial is True
            else _decode_pydantic_trailing_strings
        ) if root_scalar else _make_pydantic_partial_decoder(allow_partial)
        if isinstance(sample, str):
            if _backend_jiter is not None:
                decode_jiter = (
                    _decode_jiter_partial_text
                    if allow_partial is True
                    else _decode_jiter_trailing_strings_text
                ) if root_scalar else _make_jiter_partial_text_decoder(allow_partial)
        elif isinstance(sample, bytes):
            if _backend_jiter is not None:
                decode_jiter = (
                    _decode_jiter_partial_bytes
                    if allow_partial is True
                    else _decode_jiter_trailing_strings_bytes
                ) if root_scalar else _make_jiter_partial_bytes_decoder(allow_partial)
        elif _backend_jiter is not None:
            decode_jiter = (
                _decode_jiter_partial_bytearray
                if allow_partial is True
                else _decode_jiter_trailing_strings_bytearray
            ) if root_scalar else _make_jiter_partial_bytearray_decoder(allow_partial)

    try:
        reference = decode_pydantic(sample)
    except Exception:
        return None
    candidates = [decode_pydantic]
    if _backend_jiter is not None:
        candidates.append(decode_jiter)
    native_decoder = _make_native_structural_partial_decoder(allow_partial)
    if native_decoder is not None:
        candidates.append(native_decoder)
    return _select_calibrated_candidate(
        payload,
        tuple(candidates),
        reference,
        _STRUCTURAL_CALIBRATION_INVALID_DOCUMENTS,
        decode_pydantic,
        probe_payload=sample,
    )


def make_tuned_structural_partial_decoder(
    *,
    sample: str | bytes | bytearray | None = None,
    trailing_strings: bool = False,
) -> Any:
    """Bind structural partial decoding to a stable input representation and shape."""
    if _backend_pydantic_from_json is None:
        raise RuntimeError("pydantic-core is required for structural partial decoding")
    if not isinstance(trailing_strings, bool):
        raise TypeError("trailing_strings must be a bool")

    allow_partial = "trailing-strings" if trailing_strings else True
    if isinstance(sample, str):
        calibrated = _calibrate_structural_partial_decoder(
            sample,
            allow_partial=allow_partial,
        )
        if calibrated is not None:
            return calibrated
        use_jiter = _should_use_jiter_structural_text(
            sample,
            trailing_strings=trailing_strings,
        )
        root_string = allow_partial is True and _is_incomplete_root_string(sample)
        root_scalar = _is_root_scalar_prefix(sample)
        if use_jiter and _backend_jiter is not None:
            if not root_string and not root_scalar:
                return (
                    _decode_jiter_partial_text
                    if allow_partial is True
                    else _decode_jiter_trailing_strings_text
                )

            def decode_string(data: str) -> Any:
                if (
                    root_string and _is_incomplete_root_string(data)
                ) or (root_scalar and _is_incomplete_root_scalar(data)):
                    return None
                return _decode_jiter_structural(
                    data.encode("utf-8"), allow_partial=allow_partial
                )

            return decode_string
        if root_string:
            def decode_string(data: str) -> Any:
                if _is_incomplete_root_string(data):
                    return None
                return _decode_pydantic_structural(
                    data, allow_partial=allow_partial
                )

            return decode_string
        if not root_scalar:
            return _make_pydantic_partial_decoder(allow_partial)
        return (
            _decode_pydantic_partial
            if allow_partial is True
            else _decode_pydantic_trailing_strings
        )
    if isinstance(sample, bytes) and _backend_jiter is not None:
        calibrated = _calibrate_structural_partial_decoder(
            sample,
            allow_partial=allow_partial,
        )
        if calibrated is not None:
            return calibrated

        if (
            allow_partial == "trailing-strings"
            and _is_root_scalar_prefix(sample)
        ):
            return _decode_pydantic_trailing_strings
        root_string = allow_partial is True and _is_incomplete_root_string(sample)
        root_scalar = _is_root_scalar_prefix(sample)
        use_jiter = _should_use_jiter_structural_bytearray(
            sample,
            trailing_strings=trailing_strings,
        )
        if not root_string and not root_scalar and not use_jiter:
            return _make_pydantic_partial_decoder(allow_partial)
        if not root_string and not root_scalar:
            return _make_jiter_partial_bytes_decoder(allow_partial)
        if not root_string:
            return (
                _decode_jiter_partial_bytes
                if allow_partial is True
                else _decode_jiter_trailing_strings_bytes
            )

        def decode_bytes(data: bytes) -> Any:
            if _is_incomplete_root_string(data):
                return None
            return _decode_jiter_structural(data, allow_partial=allow_partial)

        return decode_bytes
    if isinstance(sample, bytearray):
        calibrated = _calibrate_structural_partial_decoder(
            sample,
            allow_partial=allow_partial,
        )
        if calibrated is not None:
            return calibrated

        root_string = allow_partial is True and _is_incomplete_root_string(sample)
        root_scalar = _is_root_scalar_prefix(sample)
        if (
            _backend_jiter is not None
            and not root_string
            and not root_scalar
            and _should_use_jiter_structural_bytearray(
                sample,
                trailing_strings=trailing_strings,
            )
        ):
            return _make_jiter_partial_bytearray_decoder(allow_partial)
        if not root_string and not root_scalar:
            return _make_pydantic_partial_decoder(allow_partial)
        if (
            _backend_jiter is not None
            and not root_string
            and _should_use_jiter_structural_bytearray(
                sample,
                trailing_strings=trailing_strings,
            )
        ):
            return (
                _decode_jiter_partial_bytearray
                if allow_partial is True
                else _decode_jiter_trailing_strings_bytearray
            )

        if not root_string:
            return (
                _decode_pydantic_partial
                if allow_partial is True
                else _decode_pydantic_trailing_strings
            )

        def decode_bytearray(data: bytearray) -> Any:
            if _is_incomplete_root_string(data):
                return None
            return _decode_pydantic_structural(data, allow_partial=allow_partial)

        return decode_bytearray
    if sample is None and not trailing_strings:
        return decode_structural_partial_json

    def decode_fallback(data: str | bytes | bytearray) -> Any:
        return _decode_pydantic_structural(data, allow_partial=allow_partial)

    return decode_fallback


def _decode_structural_prefix(payload: str | bytes, *, trailing_strings: bool) -> Any:
    allow_partial = "trailing-strings" if trailing_strings else True
    if isinstance(payload, str):
        stripped = payload.lstrip(" \n\r\t")
        first = stripped[0] if stripped else None
        if first is None:
            return None
        if first == "{" and _looks_plain_ascii_text(payload):
            return _decode_pydantic_structural(payload, allow_partial=allow_partial)
        if first == "{" and len(payload) < _STRUCTURAL_JITER_TEXT_THRESHOLD:
            return _decode_pydantic_structural(payload, allow_partial=allow_partial)
        if (
            first == "["
            and _backend_jiter is not None
            and _is_numeric_array_data(payload)
        ):
            return _decode_jiter_structural(
                payload.encode("utf-8"), allow_partial=allow_partial
            )
        if first in "-0123456789tfn":
            scalar = payload.strip(" \n\r\t")
            if first in "tfn":
                if any(
                    scalar != literal and literal.startswith(scalar)
                    for literal in ("true", "false", "null")
                ):
                    return None
            elif scalar[-1:] in "-.eE+":
                return None
            return _decode_pydantic_structural(payload, allow_partial=allow_partial)
        if first == '"':
            if _has_unescaped_trailing_quote(payload):
                if _looks_plain_ascii_text(payload):
                    return _decode_pydantic_structural(
                        payload, allow_partial=allow_partial
                    )
                return _decode_structural_text(payload, trailing_strings=trailing_strings)
            if not trailing_strings and _is_incomplete_root_string(payload):
                return None
            return _decode_structural_text(payload, trailing_strings=trailing_strings)
        return _decode_structural_text(payload, trailing_strings=trailing_strings)
    first = _first_json_token(payload)
    if first is None:
        return None
    if (
        first == ord("{")
        and len(payload) >= _STRUCTURAL_JITER_BYTEARRAY_OBJECT_THRESHOLD
        and _backend_jiter is not None
    ):
        if isinstance(payload, bytes):
            return _decode_jiter_structural(payload, allow_partial=allow_partial)
        return _decode_jiter_structural(bytes(payload), allow_partial=allow_partial)
    if (
        first == ord("{")
        and len(payload) < _STRUCTURAL_JITER_BYTEARRAY_OBJECT_THRESHOLD
    ):
        return _decode_pydantic_structural(payload, allow_partial=allow_partial)
    if first == ord("[") and _backend_jiter is not None:
        return _decode_jiter_structural(payload, allow_partial=allow_partial)
    if first in b"-0123456789tfn":
        scalar = payload.strip(b" \n\r\t")
        if first in b"tfn":
            if any(
                scalar != literal and literal.startswith(scalar)
                for literal in (b"true", b"false", b"null")
            ):
                return None
        elif scalar[-1:] in (b"-", b".", b"e", b"E", b"+"):
            return None
        return _decode_pydantic_structural(payload, allow_partial=allow_partial)
    if first == ord('"'):
        if _has_unescaped_trailing_quote(payload):
            if len(payload) < _STRUCTURAL_JITER_BYTEARRAY_OBJECT_THRESHOLD:
                return _decode_pydantic_structural(payload, allow_partial=allow_partial)
        elif not trailing_strings and _is_incomplete_root_string(payload):
            return None
    if (
        _backend_jiter is not None
        and _should_use_jiter_structural_bytearray(
            payload,
            trailing_strings=trailing_strings,
        )
    ):
        return _decode_jiter_structural(payload, allow_partial=allow_partial)
    return _decode_pydantic_structural(
        payload,
        allow_partial=allow_partial,
    )


def _decode_structural_text(data: str, *, trailing_strings: bool) -> Any:
    allow_partial = "trailing-strings" if trailing_strings else True
    stripped = data.lstrip(" \n\r\t")
    first = stripped[0] if stripped else None
    if first is None:
        return None
    if first == "{" and _looks_plain_ascii_text(data):
        return _decode_pydantic_structural(data, allow_partial=allow_partial)
    # Short ordinary objects and strings are consistently faster on Pydantic;
    # avoid the more expensive Jiter shape probe on this common path.
    if (
        len(data) < _STRUCTURAL_JITER_TEXT_THRESHOLD
        and (first is None or first not in "-0123456789[")
    ):
        return _decode_pydantic_structural(data, allow_partial=allow_partial)
    if _backend_jiter is not None and _should_use_jiter_structural_text(
        data,
        trailing_strings=trailing_strings,
    ):
        return _decode_jiter_structural(
            data.encode("utf-8"),
            allow_partial=allow_partial,
        )
    return _decode_pydantic_structural(data, allow_partial=allow_partial)


def _get_cached_msgspec_decoder(decoder_type: Any) -> Any | None:
    if _backend_msgspec is None:
        return None
    decoder = _DECODER_CACHE.get(decoder_type)
    if decoder is not None:
        return decoder
    try:
        decoder = _backend_msgspec.json.Decoder(decoder_type)
    except Exception:
        return None
    _DECODER_CACHE[decoder_type] = decoder
    return decoder


def make_complete_json_decoder(*, value_type: Any | None = None) -> Any:
    if value_type is not None:
        decoder = _get_cached_msgspec_decoder(value_type)
        if decoder is not None:
            return decoder.decode

    cached_input: str | bytes | None = None
    cached_payload: bytes | None = None
    cached_decoder: Any | None = None

    def decoder(data: str | bytes | bytearray) -> Any:
        nonlocal cached_input, cached_payload, cached_decoder
        if (
            value_type is None
            and isinstance(data, (str, bytes))
            and data is cached_input
            and cached_decoder is not None
        ):
            if isinstance(data, str) and cached_payload is not None:
                return cached_decoder(cached_payload)
            return cached_decoder(data)

        if value_type is None and isinstance(data, str):
            cached_decoder = _select_complete_decoder_text(data)
            cached_input = data
            cached_payload = None
            try:
                return cached_decoder(data)
            except TypeError:
                cached_payload = _coerce_bytes(data)
                return cached_decoder(cached_payload)

        # Bytearrays are mutable, so do not cache a decoder by object identity;
        # preserve the buffer for the backend and reselect safely on each call.
        if isinstance(data, bytearray):
            return _invoke_complete_decoder(
                _select_complete_decoder(data, value_type=value_type),
                data,
                data,
            )

        payload = data if isinstance(data, bytes) else _coerce_bytes(data)
        if (
            value_type is None
            and isinstance(data, (str, bytes, bytearray))
            and len(payload) < _ORJSON_TINY_THRESHOLD
        ):
            if _backend_orjson is not None and _should_use_orjson_for_escaped_payload(data):
                cached_decoder = _backend_orjson.loads
            elif _backend_orjson is not None and _is_numeric_array_data(data):
                cached_decoder = _backend_orjson.loads
            elif _GLOBAL_MSGSPEC_DECODER is not None:
                cached_decoder = _GLOBAL_MSGSPEC_DECODER.decode
            elif _backend_orjson is not None:
                cached_decoder = _backend_orjson.loads
            else:
                cached_decoder = json.loads
            cached_payload = payload
            cached_input = data if isinstance(data, (str, bytes)) else None
            return cached_decoder(data)
        if payload is not cached_payload:
            cached_payload = payload
            cached_decoder = _select_complete_decoder(payload, value_type=value_type)
            cached_input = data if isinstance(data, (str, bytes)) else None
        return _invoke_complete_decoder(cached_decoder, data, payload)

    return decoder


def make_tuned_complete_json_decoder(
    *,
    value_type: Any | None = None,
    payload_size_hint: int | None = None,
    sample: str | bytes | bytearray | None = None,
    mode: str = "materialize",
) -> Any:
    if mode not in {"materialize", "view"}:
        raise ValueError("mode must be 'materialize' or 'view'")
    if mode == "view":
        return make_complete_json_view_decoder()

    if value_type is not None:
        decoder = _get_cached_msgspec_decoder(value_type)
        if decoder is not None:
            return decoder.decode

    if sample is not None:
        payload = _coerce_bytes(sample)
        fallback = _select_complete_decoder(payload, value_type=value_type)
        if value_type is None and payload_size_hint is not None:
            if isinstance(sample, bytes):
                return _calibrate_complete_decoder(payload, fallback)
            return _calibrate_complete_decoder(
                payload,
                fallback,
                probe_payload=sample,
            )
        return fallback

    return make_complete_json_decoder(value_type=value_type)


def decode_complete_json_view(data: str | bytes | bytearray) -> Any:
    if _backend_simdjson is None:
        return decode_complete_json(data)
    parser = _backend_simdjson.Parser()
    return parser.parse(_coerce_bytes(data))


def make_complete_json_view_decoder() -> Any:
    if _backend_simdjson is None:
        return make_complete_json_decoder()

    parser = _backend_simdjson.Parser()

    def decoder(data: str | bytes | bytearray) -> Any:
        return parser.parse(_coerce_bytes(data))

    return decoder


def extract_complete_json_paths(
    data: str | bytes | bytearray,
    *paths: tuple[str | int, ...],
) -> Any:
    extractor = make_json_path_extractor(*paths)
    return extractor(data)


def extract_tuned_json_paths(
    data: str | bytes | bytearray,
    *paths: tuple[str | int, ...],
    framing: str = "single",
    sample: dict[str, Any] | None = None,
) -> Any:
    if framing == "single":
        return extract_tuned_complete_json_paths(data, *paths, sample=sample)
    if framing == "ndjson":
        return extract_tuned_ndjson_paths(data, *paths, sample=sample)
    raise ValueError("framing must be 'single' or 'ndjson'")


def extract_tuned_complete_json_paths(
    data: str | bytes | bytearray,
    *paths: tuple[str | int, ...],
    sample: dict[str, Any] | None = None,
) -> Any:
    payload = _coerce_bytes(data)
    # One-shot complete extraction does not amortize typed extractor setup well.
    # The reusable tuned factory is the right API for repeated small-document calls.
    return make_json_path_extractor(*paths)(payload)


def extract_complete_json_typed_paths(
    data: str | bytes | bytearray,
    *paths: tuple[str, ...],
    sample: dict[str, Any] | None = None,
) -> Any:
    if sample is None:
        decoded_sample = decode_complete_json(data)
        if not isinstance(decoded_sample, dict):
            raise ValueError("typed complete path extraction requires an object document")
        sample = decoded_sample
    extractor = make_complete_json_typed_path_extractor(*paths, sample=sample)
    return extractor(data)


def extract_ndjson_paths_native(
    data: str | bytes | bytearray,
    *paths: tuple[str | int, ...],
) -> list[Any]:
    extractor = make_ndjson_path_extractor_native(*paths)
    return extractor(data)


def extract_ndjson_paths(
    data: str | bytes | bytearray,
    *paths: tuple[str | int, ...],
) -> list[Any]:
    extractor = make_ndjson_path_extractor(*paths)
    return extractor(data)


def extract_ndjson_typed_paths(
    data: str | bytes | bytearray,
    *paths: tuple[str, ...],
    sample: dict[str, Any] | None = None,
) -> list[Any]:
    if sample is None:
        first_line = next((line for line in _coerce_bytes(data).splitlines() if line), None)
        if first_line is None:
            return []
        decoded_sample = decode_complete_json(first_line)
        if not isinstance(decoded_sample, dict):
            raise ValueError("typed NDJSON path extraction requires object records")
        sample = decoded_sample
    extractor = make_ndjson_typed_path_extractor(*paths, sample=sample)
    return extractor(data)


def extract_tuned_ndjson_paths(
    data: str | bytes | bytearray,
    *paths: tuple[str | int, ...],
    sample: dict[str, Any] | None = None,
) -> list[Any]:
    payload = _coerce_bytes(data)
    if sample is None:
        first_line = next((line for line in payload.splitlines() if line), None)
        if first_line is not None:
            decoded_sample = decode_complete_json(first_line)
            if isinstance(decoded_sample, dict):
                sample = decoded_sample
    extractor = make_tuned_ndjson_path_extractor(
        *paths,
        sample=sample,
        payload_size_hint=len(payload),
    )
    return extractor(payload)


def make_json_path_extractor(*paths: tuple[str | int, ...]) -> Any:
    normalized = tuple(tuple(path) for path in paths)
    if not normalized:
        raise ValueError("at least one path is required")
    cached = _COMPLETE_PATH_EXTRACTOR_CACHE.get(normalized)
    if cached is not None:
        return cached
    projector = _compile_path_projector(normalized)

    if _backend_simdjson is not None:
        parser = _backend_simdjson.Parser()

        def extractor(data: str | bytes | bytearray) -> Any:
            doc = parser.parse(_coerce_bytes(data))
            return projector(doc)

        _COMPLETE_PATH_EXTRACTOR_CACHE[normalized] = extractor
        return extractor

    def extractor(data: str | bytes | bytearray) -> Any:
        doc = decode_complete_json(data)
        return projector(doc)

    _COMPLETE_PATH_EXTRACTOR_CACHE[normalized] = extractor
    return extractor


def make_tuned_json_path_extractor(
    *paths: tuple[str | int, ...],
    framing: str = "single",
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Any:
    if framing == "single":
        return make_tuned_complete_json_path_extractor(
            *paths,
            sample=sample,
            payload_size_hint=payload_size_hint,
        )
    if framing == "ndjson":
        return make_tuned_ndjson_path_extractor(
            *paths,
            sample=sample,
            payload_size_hint=payload_size_hint,
        )
    raise ValueError("framing must be 'single' or 'ndjson'")


def make_tuned_complete_json_path_extractor(
    *paths: tuple[str | int, ...],
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Any:
    normalized = tuple(tuple(path) for path in paths)
    if not normalized:
        raise ValueError("at least one path is required")

    can_use_typed = (
        sample is not None
        and payload_size_hint is not None
        and payload_size_hint < _TYPED_COMPLETE_PATH_THRESHOLD
        and all(path and all(isinstance(segment, str) for segment in path) for path in normalized)
    )
    if can_use_typed:
        return make_complete_json_typed_path_extractor(*normalized, sample=sample)
    return make_json_path_extractor(*normalized)


def make_complete_json_typed_path_extractor(
    *paths: tuple[str, ...],
    sample: dict[str, Any],
) -> Any:
    normalized = tuple(tuple(path) for path in paths)
    if not normalized:
        raise ValueError("at least one path is required")
    if _backend_msgspec is None:
        raise RuntimeError("msgspec is required for typed complete path extraction")
    if not isinstance(sample, dict):
        raise ValueError("sample must be a dict-like object document")
    if not all(path and all(isinstance(segment, str) for segment in path) for path in normalized):
        raise ValueError("typed complete path extraction only supports non-empty string paths")
    if not all(segment.isidentifier() and not keyword.iskeyword(segment) for path in normalized for segment in path):
        raise ValueError("typed complete path extraction requires identifier-safe string paths")

    projected = _project_dict_sample_for_paths(sample, normalized)
    record_type = _infer_msgspec_type(projected)
    if not hasattr(record_type, "__struct_fields__"):
        raise ValueError("sample could not be represented as a typed msgspec struct")

    decoder = _get_cached_msgspec_decoder(record_type)
    if decoder is None:
        raise RuntimeError("failed to construct typed msgspec decoder")
    cache_key = (record_type, normalized)
    cached = _COMPLETE_TYPED_PATH_EXTRACTOR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    projector = _compile_single_record_projector(normalized)

    def extractor(data: str | bytes | bytearray) -> Any:
        source = data if isinstance(data, str) else _coerce_bytes(data)
        record = decoder.decode(source)
        return projector(record)

    _COMPLETE_TYPED_PATH_EXTRACTOR_CACHE[cache_key] = extractor
    return extractor


def make_ndjson_typed_path_extractor(
    *paths: tuple[str, ...],
    sample: dict[str, Any],
) -> Any:
    normalized = tuple(tuple(path) for path in paths)
    if not normalized:
        raise ValueError("at least one path is required")
    if _backend_msgspec is None:
        raise RuntimeError("msgspec is required for typed NDJSON path extraction")
    if not isinstance(sample, dict):
        raise ValueError("sample must be a dict-like object record")
    if not all(path and all(isinstance(segment, str) for segment in path) for path in normalized):
        raise ValueError("typed NDJSON path extraction only supports non-empty string paths")
    if not all(segment.isidentifier() and not keyword.iskeyword(segment) for path in normalized for segment in path):
        raise ValueError("typed NDJSON path extraction requires identifier-safe string paths")

    projected = _project_dict_sample_for_paths(sample, normalized)
    record_type = _infer_msgspec_type(projected)
    if not hasattr(record_type, "__struct_fields__"):
        raise ValueError("sample could not be represented as a typed msgspec struct")

    decoder = _get_cached_msgspec_decoder(record_type)
    if decoder is None:
        raise RuntimeError("failed to construct typed msgspec decoder")
    cache_key = (record_type, normalized)
    cached = _NDJSON_TYPED_PATH_EXTRACTOR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    projector = _compile_record_projector(normalized)

    def extractor(data: str | bytes | bytearray) -> list[Any]:
        source = data if isinstance(data, str) else _coerce_bytes(data)
        records = (
            decoder.decode_lines(source)
            if hasattr(decoder, "decode_lines")
            else [
                decoder.decode(line)
                for line in source.split("\n" if isinstance(source, str) else b"\n")
                if line
            ]
        )
        return projector(records)

    _NDJSON_TYPED_PATH_EXTRACTOR_CACHE[cache_key] = extractor
    return extractor


def make_ndjson_path_extractor(*paths: tuple[str | int, ...]) -> Any:
    normalized = tuple(tuple(path) for path in paths)
    if not normalized:
        raise ValueError("at least one path is required")
    cached = _NDJSON_PATH_EXTRACTOR_CACHE.get(normalized)
    if cached is not None:
        return cached
    projector = _compile_mapping_record_projector(normalized)

    def extractor(data: str | bytes | bytearray) -> list[Any]:
        records = decode_ndjson(data)
        return projector(records)

    _NDJSON_PATH_EXTRACTOR_CACHE[normalized] = extractor
    return extractor


def make_tuned_ndjson_path_extractor(
    *paths: tuple[str | int, ...],
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Any:
    normalized = tuple(tuple(path) for path in paths)
    if not normalized:
        raise ValueError("at least one path is required")

    record_size_hint = None
    if sample is not None:
        try:
            record_size_hint = len(json.dumps(sample))
        except Exception:
            record_size_hint = None

    can_use_typed = (
        sample is not None
        and (
            record_size_hint is None
            or record_size_hint < _TYPED_NDJSON_RECORD_THRESHOLD
        )
        and all(path and all(isinstance(segment, str) for segment in path) for path in normalized)
    )
    if can_use_typed:
        return make_ndjson_typed_path_extractor(*normalized, sample=sample)
    return make_ndjson_path_extractor(*normalized)


def make_ndjson_path_extractor_native(*paths: tuple[str | int, ...]) -> Any:
    normalized = tuple(tuple(path) for path in paths)
    if not normalized:
        raise ValueError("at least one path is required")
    if _backend_native is None:
        raise RuntimeError("experimental native backend is not available")

    def extractor(data: str | bytes | bytearray) -> list[Any]:
        return _backend_native.extract_ndjson_paths(data, normalized)

    return extractor


def _compile_path_projector(paths: tuple[tuple[str | int, ...], ...]) -> Any:
    def path_expr(path: tuple[str | int, ...]) -> str:
        expression = "doc"
        for segment in path:
            expression += f"[{segment!r}]"
        return expression

    if len(paths) == 1:
        expression = path_expr(paths[0])
    else:
        expression = "(" + ", ".join(path_expr(path) for path in paths) + ")"
    return eval(f"lambda doc: {expression}", {})


def _compile_record_projector(paths: tuple[tuple[str, ...], ...]) -> Any:
    def path_expr(path: tuple[str, ...]) -> str:
        return "record." + ".".join(path)

    if len(paths) == 1:
        expression = f"[{path_expr(paths[0])} for record in records]"
    else:
        tuple_expr = ", ".join(path_expr(path) for path in paths)
        expression = f"[({tuple_expr}) for record in records]"
    return eval(f"lambda records: {expression}", {})


def _compile_mapping_record_projector(paths: tuple[tuple[str | int, ...], ...]) -> Any:
    def path_expr(path: tuple[str | int, ...]) -> str:
        expr = "record"
        for segment in path:
            expr += f"[{segment!r}]"
        return expr

    if len(paths) == 1:
        expression = f"[{path_expr(paths[0])} for record in records]"
    else:
        tuple_expr = ", ".join(path_expr(path) for path in paths)
        expression = f"[({tuple_expr}) for record in records]"
    return eval(f"lambda records: {expression}", {})


def _compile_single_record_projector(paths: tuple[tuple[str, ...], ...]) -> Any:
    def path_expr(path: tuple[str, ...]) -> str:
        return "record." + ".".join(path)

    if len(paths) == 1:
        expression = path_expr(paths[0])
    else:
        expression = "(" + ", ".join(path_expr(path) for path in paths) + ")"
    return eval(f"lambda record: {expression}", {})


def _project_dict_sample_for_paths(
    sample: dict[str, Any],
    paths: tuple[tuple[str, ...], ...],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for path in paths:
        source: Any = sample
        target: dict[str, Any] = projected
        for index, segment in enumerate(path):
            if not isinstance(source, dict) or segment not in source:
                raise ValueError(f"sample is missing path segment {segment!r} in {path!r}")
            source = source[segment]
            if index == len(path) - 1:
                target[segment] = source
            else:
                next_target = target.get(segment)
                if next_target is None:
                    next_target = {}
                    target[segment] = next_target
                elif not isinstance(next_target, dict):
                    raise ValueError(f"conflicting projected path {path!r}")
                target = next_target
    return projected


def _detach_extracted_value(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if hasattr(value, "as_list"):
        return value.as_list()
    return value


def decode_ndjson(data: str | bytes | bytearray, *, record_type: Any | None = None) -> list[Any]:
    if isinstance(data, str):
        if record_type is not None:
            decoder = _get_cached_msgspec_decoder(record_type)
            if decoder is not None:
                return _decode_ndjson_complete_prefix_with_decoder(data, decoder)
        if _should_use_orjson_ndjson_text(data):
            return _decode_ndjson_with_orjson_text(data)
        if _GLOBAL_MSGSPEC_DECODER is not None and hasattr(
            _GLOBAL_MSGSPEC_DECODER, "decode_lines"
        ):
            return _GLOBAL_MSGSPEC_DECODER.decode_lines(data)
        if _GLOBAL_MSGSPEC_DECODER is not None:
            return _decode_ndjson_with_line_decoder(data, _GLOBAL_MSGSPEC_DECODER.decode)
        if _backend_orjson is not None:
            return _decode_ndjson_with_orjson(data)
        if _NATIVE_NDJSON_DECODER is not None:
            return _NATIVE_NDJSON_DECODER(data)
        return _decode_ndjson_with_line_decoder(data, json.loads)

    payload = data if isinstance(data, bytearray) else _coerce_bytes(data)
    if record_type is not None:
        decoder = _get_cached_msgspec_decoder(record_type)
        if decoder is not None:
            return _decode_ndjson_complete_prefix_with_decoder(payload, decoder)
    if _should_use_orjson_ndjson(payload):
        return _decode_ndjson_with_orjson_binary(payload)
    if _GLOBAL_MSGSPEC_DECODER is not None and hasattr(_GLOBAL_MSGSPEC_DECODER, "decode_lines"):
        return _GLOBAL_MSGSPEC_DECODER.decode_lines(payload)
    if _GLOBAL_MSGSPEC_DECODER is not None:
        line_decoder = _GLOBAL_MSGSPEC_DECODER.decode
    elif _backend_orjson is not None:
        line_decoder = _backend_orjson.loads
    elif _NATIVE_NDJSON_DECODER is not None:
        return _NATIVE_NDJSON_DECODER(payload)
    else:
        line_decoder = json.loads
    return _decode_ndjson_with_line_decoder(payload, line_decoder)


def make_ndjson_decoder(*, record_type: Any | None = None) -> Any:
    if record_type is not None:
        decoder = _get_cached_msgspec_decoder(record_type)
        if decoder is not None and hasattr(decoder, "decode_lines"):
            return decoder.decode_lines
    if _GLOBAL_MSGSPEC_DECODER is not None and hasattr(_GLOBAL_MSGSPEC_DECODER, "decode_lines"):
        cached_input: str | None = None
        cached_payload: bytes | bytearray | None = None
        cached_decoder: Any | None = None

        def decoder(data: str | bytes | bytearray) -> list[Any]:
            nonlocal cached_input, cached_payload, cached_decoder
            if isinstance(data, str):
                if (
                    data is cached_input
                    and cached_payload is None
                    and cached_decoder is not None
                ):
                    return cached_decoder(data)
                cached_input = data
                cached_payload = None
                cached_decoder = (
                    _make_orjson_ndjson_text_decoder()
                    if _should_use_orjson_ndjson_text(data)
                    else _GLOBAL_MSGSPEC_DECODER.decode_lines
                )
                return cached_decoder(data)

            payload = (
                data
                if isinstance(data, (bytes, bytearray))
                else _coerce_bytes(data)
            )
            if payload is not cached_payload:
                cached_input = None
                cached_payload = payload
                cached_decoder = (
                    _make_orjson_ndjson_binary_decoder()
                    if _should_use_orjson_ndjson(payload)
                    else _GLOBAL_MSGSPEC_DECODER.decode_lines
                )
            return cached_decoder(payload)

        return decoder

    def decoder(data: str | bytes | bytearray) -> list[Any]:
        return decode_ndjson(data, record_type=record_type)

    return decoder


def make_tuned_ndjson_decoder(
    *,
    record_type: Any | None = None,
    sample: str | bytes | bytearray | None = None,
    payload_size_hint: int | None = None,
) -> Any:
    """Bind NDJSON decoding to a representative workload when available."""
    if record_type is not None:
        return make_ndjson_decoder(record_type=record_type)

    if sample is not None:
        sample_payload = _coerce_bytes(sample)
        fallback: Any | None = None
        if isinstance(sample, str) and _should_use_orjson_ndjson_text(sample):
            fallback = _make_orjson_ndjson_text_decoder()
        elif isinstance(sample, str) and _GLOBAL_MSGSPEC_DECODER is not None and hasattr(
            _GLOBAL_MSGSPEC_DECODER, "decode_lines"
        ):
            fallback = _GLOBAL_MSGSPEC_DECODER.decode_lines
        elif isinstance(sample, str) and _backend_orjson is not None:
            fallback = _make_orjson_ndjson_text_decoder()
        elif isinstance(sample, str) and _backend_yyjson is not None and sample.isascii():
            fallback = _decode_ndjson_with_yyjson
        elif isinstance(sample, str):
            fallback = decode_ndjson
        elif _should_use_orjson_ndjson(sample_payload):
            fallback = _make_orjson_ndjson_binary_decoder()
        elif _GLOBAL_MSGSPEC_DECODER is not None and hasattr(
            _GLOBAL_MSGSPEC_DECODER, "decode_lines"
        ):
            fallback = _GLOBAL_MSGSPEC_DECODER.decode_lines
        elif _backend_orjson is not None:
            fallback = _make_orjson_ndjson_binary_decoder()
        elif _backend_yyjson is not None:
            if isinstance(sample, bytes):
                fallback = _decode_ndjson_with_yyjson
            else:
                def decode_yyjson(data: str | bytes | bytearray) -> list[Any]:
                    return _decode_ndjson_with_yyjson(_coerce_bytes(data))

                fallback = decode_yyjson
        if fallback is not None:
            if payload_size_hint is not None:
                if isinstance(sample, bytes):
                    return _calibrate_ndjson_decoder(sample_payload, fallback)
                return _calibrate_ndjson_decoder(
                    sample_payload,
                    fallback,
                    probe_payload=sample,
                )
            return fallback

    if (
        payload_size_hint is not None
        and payload_size_hint < _NDJSON_ORJSON_ARRAY_THRESHOLD
        and _GLOBAL_MSGSPEC_DECODER is not None
        and hasattr(_GLOBAL_MSGSPEC_DECODER, "decode_lines")
    ):
        return _GLOBAL_MSGSPEC_DECODER.decode_lines
    if _NATIVE_NDJSON_DECODER is not None:
        return _NATIVE_NDJSON_DECODER
    return make_ndjson_decoder()


def decode_ndjson_adaptive(data: str | bytes | bytearray) -> list[Any]:
    global _LAST_ADAPTIVE_NDJSON_DECODER
    payload = _coerce_bytes(data)
    if _GLOBAL_MSGSPEC_DECODER is None or not hasattr(_GLOBAL_MSGSPEC_DECODER, "decode_lines"):
        return decode_ndjson(payload)

    if _LAST_ADAPTIVE_NDJSON_DECODER is not None:
        try:
            return _decode_ndjson_complete_prefix_with_decoder(
                payload,
                _LAST_ADAPTIVE_NDJSON_DECODER,
            )
        except Exception:
            _LAST_ADAPTIVE_NDJSON_DECODER = None

    first_line = next((line for line in payload.split(b"\n") if line), b"")
    if not first_line:
        return []

    sample = _GLOBAL_MSGSPEC_DECODER.decode(first_line)
    decoder = _build_specialized_ndjson_decoder(sample)
    if decoder is None:
        return decode_ndjson(payload)
    _LAST_ADAPTIVE_NDJSON_DECODER = decoder
    try:
        return _decode_ndjson_complete_prefix_with_decoder(payload, decoder)
    except Exception:
        return decode_ndjson(payload)


def _decode_ndjson_complete_prefix(payload: str | bytes) -> list[Any]:
    return decode_ndjson(payload)


def _decode_ndjson_complete_prefix_with_decoder(
    payload: str | bytes,
    decoder: Any | None,
) -> list[Any]:
    if decoder is not None and hasattr(decoder, "decode_lines"):
        return decoder.decode_lines(payload)
    if decoder is not None:
        separator = "\n" if isinstance(payload, str) else b"\n"
        return [decoder.decode(line) for line in payload.split(separator) if line]
    return _decode_ndjson_complete_prefix(payload)


def _build_specialized_ndjson_decoder(sample: Any) -> Any | None:
    if _backend_msgspec is None:
        return None
    cache_key = _adaptive_schema_key(sample)
    cached = _ADAPTIVE_NDJSON_DECODER_CACHE.get(cache_key)
    if cached is not None:
        return (
            None
            if cached is _NO_ADAPTIVE_NDJSON_DECODER
            else cached
        )
    inferred = _infer_msgspec_type(sample)
    if inferred in (Any, dict[str, Any], list[Any]):
        _cache_adaptive_ndjson_decoder(cache_key, None)
        return None
    decoder = _get_cached_msgspec_decoder(inferred)
    _cache_adaptive_ndjson_decoder(cache_key, decoder)
    return decoder


def _cache_adaptive_ndjson_decoder(
    cache_key: tuple[Any, ...],
    decoder: Any | None,
) -> None:
    if len(_ADAPTIVE_NDJSON_DECODER_CACHE) >= _ADAPTIVE_NDJSON_CACHE_LIMIT:
        _ADAPTIVE_NDJSON_DECODER_CACHE.pop(next(iter(_ADAPTIVE_NDJSON_DECODER_CACHE)))
    _ADAPTIVE_NDJSON_DECODER_CACHE[cache_key] = (
        _NO_ADAPTIVE_NDJSON_DECODER if decoder is None else decoder
    )


def _adaptive_schema_key(value: Any) -> tuple[Any, ...]:
    if isinstance(value, dict):
        return (
            "dict",
            tuple((key, _adaptive_schema_key(item)) for key, item in value.items()),
        )
    if isinstance(value, list):
        if not value:
            return ("list",)
        item_keys = tuple(_adaptive_schema_key(item) for item in value)
        if all(item_key == item_keys[0] for item_key in item_keys[1:]):
            return ("list", item_keys[0])
        return ("list", item_keys)
    return ("scalar", type(value))


def _infer_msgspec_type(value: Any) -> Any:
    if value is None:
        return type(None)
    if type(value) is bool:
        return bool
    if type(value) is int:
        return int
    if type(value) is float:
        return float
    if type(value) is str:
        return str
    if isinstance(value, list):
        if not value:
            return list[Any]
        item_types = [_infer_msgspec_type(item) for item in value]
        first_type = item_types[0]
        if all(item_type == first_type for item_type in item_types[1:]):
            return list[first_type]
        return list[Any]
    if isinstance(value, dict):
        if not value:
            return dict[str, Any]
        if not all(isinstance(key, str) and key.isidentifier() and not keyword.iskeyword(key) for key in value):
            return dict[str, Any]
        fields = tuple((key, _infer_msgspec_type(item)) for key, item in value.items())
        if any(field_type is Any for _, field_type in fields):
            return dict[str, Any]
        struct_type = _STRUCT_CACHE.get(fields)
        if struct_type is None:
            struct_type = _backend_msgspec.defstruct(
                f"AutoStruct{len(_STRUCT_CACHE)}",
                list(fields),
                module=__name__,
            )
            _STRUCT_CACHE[fields] = struct_type
        return struct_type
    return Any


class _HighPerformanceParserMeta(type):
    def __instancecheck__(cls, instance: Any) -> bool:
        if _NATIVE_FACADE_TYPE is not None and isinstance(instance, _NATIVE_FACADE_TYPE):
            return True
        if (
            _NATIVE_INCREMENTAL_TYPE is not None
            and isinstance(instance, _NATIVE_INCREMENTAL_TYPE)
            and getattr(instance, "_public_api", False)
        ):
            return True
        return super().__instancecheck__(instance)


class HighPerformanceStreamingJsonParser(metaclass=_HighPerformanceParserMeta):
    """
    Hybrid parser:
    - adaptive native-backed complete decode path
    - persistent incremental strict fallback for true streaming
    - optional structural partial finisher mode
    - optional NDJSON framing mode
    """

    __slots__ = (
        "_framing",
        "_schema_mode",
        "_partial_mode",
        "_record_type",
        "_value_type",
        "_pending",
        "_pending_bytes",
        "_pending_text",
        "_typed_payload",
        "_simple_string_state",
        "_incremental",
        "_native_incremental",
        "_native_feed",
        "__dict__",
        "_ndjson_decoder",
        "_ready_values",
        "_complete",
        "_completed_value",
        "_error",
        "_finished",
    )

    def __new__(
        cls,
        *,
        framing: str = "single",
        schema_mode: str = "generic",
        partial_mode: str = "strict",
        record_type: Any | None = None,
        value_type: Any | None = None,
    ) -> "HighPerformanceStreamingJsonParser":
        if (
            cls is HighPerformanceStreamingJsonParser
            and framing == "single"
            and schema_mode == "generic"
            and partial_mode in {"strict", "structural", "structural_trailing_strings"}
            and record_type is None
            and value_type is None
        ):
            if (
                _NATIVE_PUBLIC_AVAILABLE
                and _backend_native is _NATIVE_STRICT_BACKEND
            ):
                return _new_native_incremental(
                    public_api=True,
                    partial_mode=partial_mode,
                )
            if _NATIVE_FACADE_AVAILABLE and _backend_native is _NATIVE_STRICT_BACKEND:
                return _new_native_facade_incremental(partial_mode)
            if partial_mode == "strict" and _NATIVE_STRICT_AVAILABLE and _backend_native is _NATIVE_STRICT_BACKEND:
                return object.__new__(_NativeStrictFacade)
        return super().__new__(cls)

    def __init__(
        self,
        *,
        framing: str = "single",
        schema_mode: str = "generic",
        partial_mode: str = "strict",
        record_type: Any | None = None,
        value_type: Any | None = None,
    ) -> None:
        if (
            type(self) is _NativeStrictFacade
        ):
            native = _new_native_incremental()
            self._framing = framing
            self._schema_mode = schema_mode
            self._partial_mode = partial_mode
            self._record_type = record_type
            self._value_type = value_type
            self._simple_string_state = None
            self._native_incremental = native
            self._native_feed = native.consume_and_poll_result
            self.consume = native.consume
            self.feed = self._native_feed
            self.poll = native.poll_result_value
            self.finish = native.finish_result
            self.reset = native.reset
            return
        if framing not in {"single", "ndjson"}:
            raise ValueError("framing must be 'single' or 'ndjson'")
        if schema_mode not in {"generic", "adaptive"}:
            raise ValueError("schema_mode must be 'generic' or 'adaptive'")
        if partial_mode not in {"strict", "structural", "structural_trailing_strings"}:
            raise ValueError(
                "partial_mode must be 'strict', 'structural', or 'structural_trailing_strings'"
            )
        if framing == "ndjson" and partial_mode != "strict":
            raise ValueError(
                "partial_mode='structural' or 'structural_trailing_strings' requires framing='single'"
            )
        if value_type is not None and partial_mode != "strict":
            raise ValueError(
                "partial_mode='structural' or 'structural_trailing_strings' does not support value_type"
            )
        if partial_mode != "strict" and _backend_pydantic_from_json is None:
            raise RuntimeError(
                "pydantic-core is required for structural partial modes"
            )
        if partial_mode == "structural_trailing_strings" and not _PYDANTIC_TRAILING_STRINGS:
            raise RuntimeError(
                "pydantic-core with trailing string support is required for "
                "partial_mode='structural_trailing_strings'"
            )
        if framing == "single" and record_type is not None:
            raise ValueError("record_type requires framing='ndjson'")
        if framing == "ndjson" and value_type is not None:
            raise ValueError("value_type requires framing='single'")
        if value_type is not None and _get_cached_msgspec_decoder(value_type) is None:
            raise RuntimeError("msgspec is required for value_type decoding")
        if record_type is not None and _get_cached_msgspec_decoder(record_type) is None:
            raise RuntimeError("msgspec is required for record_type decoding")
        self._framing = framing
        self._schema_mode = schema_mode
        self._partial_mode = partial_mode
        self._record_type = record_type
        self._value_type = value_type
        self._pending = bytearray()
        self._pending_bytes: bytes | None = None
        self._pending_text = ""
        self._typed_payload = bytearray() if value_type is not None and framing == "single" else None
        self._simple_string_state: _SimpleStringFeedState | None = None
        self._incremental: _IncrementalStrictCore | None = None
        self._native_incremental: Any | None = None
        self._native_feed: Any | None = None
        self._ndjson_decoder = _get_cached_msgspec_decoder(record_type) if record_type is not None else None
        self._ready_values: deque[Any] = deque()
        self._complete = False
        self._completed_value: Any | None = None
        self._error: str | None = None
        self._finished = False
        self._install_eager_native_strict()

    def _install_eager_native_strict(self) -> None:
        if self._native_incremental is not None:
            return
        if self._partial_mode != "strict":
            return
        if _NATIVE_RESULT_TYPE is None or not self._can_use_native_incremental():
            return
        native = _new_native_incremental()
        self._native_incremental = native
        self._native_feed = native.consume_and_poll_result
        self.__dict__["feed"] = self._native_feed
        self.__dict__["poll"] = native.poll_result_value
        self.__dict__["finish"] = native.finish_result

    def consume(self, data: str | bytes | bytearray) -> None:
        if self._finished:
            raise RuntimeError("parser is finished; call reset() before consuming more data")
        if self._error:
            return
        if self._complete:
            if isinstance(data, str):
                has_trailing_data = bool(data.strip(" \n\r\t"))
            elif isinstance(data, (bytes, bytearray)):
                has_trailing_data = bool(bytes(data).strip(b" \n\r\t"))
            else:
                raise TypeError("data must be str, bytes, or bytearray")
            if has_trailing_data:
                self._error = "extra trailing data after complete document"
            return
        if self._simple_string_state is not None:
            self._feed_simple_string(data, copy_value=False)
            return
        if self._native_incremental is not None:
            self._native_incremental.consume(data)
            return
        if self._partial_mode == "strict" and self._can_use_native_incremental() and data:
            try:
                native = _new_native_incremental()
                native.consume(data)
            except Exception:
                pass
            else:
                self._native_incremental = native
                return
        if self._partial_mode != "strict" and self._can_use_native_incremental():
            try:
                native = _new_native_incremental()
                native.consume(data)
            except Exception:
                pass
            else:
                self._native_incremental = native
                return
        if isinstance(data, str):
            if self._partial_mode != "strict":
                self._materialize_pending_bytes()
                self._pending.extend(data.encode("utf-8"))
                return
            if (
                self._framing == "single"
                and self._typed_payload is None
                and not self._pending
                and self._pending_bytes is None
            ):
                self._pending_text += data
                return
            chunk = data.encode("utf-8")
            if (
                self._framing == "single"
                and not self._pending
                and self._pending_bytes is None
            ):
                self._pending_text += data
            else:
                self._materialize_pending_bytes()
                self._pending.extend(chunk)
        elif isinstance(data, (bytes, bytearray)):
            chunk = bytes(data)
            if self._pending_text:
                self._pending.extend(self._pending_text.encode("utf-8"))
                self._pending_text = ""
            self._materialize_pending_bytes()
            if (
                chunk
                and (
                    self._framing == "ndjson"
                    or (self._framing == "single" and self._typed_payload is None)
                )
                and not self._pending
            ):
                self._pending_bytes = data if isinstance(data, bytes) else chunk
            else:
                self._pending.extend(chunk)
        else:
            raise TypeError("data must be str, bytes, or bytearray")
        if self._typed_payload is not None:
            self._typed_payload.extend(chunk)

    def feed(self, data: str | bytes | bytearray, copy_value: bool = False) -> ParseResult:
        """Consume one chunk and return its current parse state."""
        if self._framing == "single" and self._partial_mode != "strict":
            if self._finished:
                raise RuntimeError("parser is finished; call reset() before consuming more data")
            if self._native_incremental is not None and _NATIVE_RESULT_TYPE is not None:
                if "feed" not in self.__dict__:
                    method = (
                        "consume_and_poll_structural_result"
                        if self._partial_mode == "structural"
                        else "consume_and_poll_partial_result"
                    )
                    self.__dict__["feed"] = getattr(self._native_incremental, method)
                return self.__dict__["feed"](data, copy_value)
            if self._error or self._complete:
                self.consume(data)
                return self.poll(copy_value=copy_value)
            if (
                self._native_incremental is None
                and self._can_use_native_incremental()
            ):
                try:
                    native = _new_native_incremental()
                    method = (
                        "consume_and_poll_structural_result"
                        if self._partial_mode == "structural"
                        else "consume_and_poll_partial_result"
                    )
                    if _NATIVE_RESULT_TYPE is None:
                        method = (
                            "consume_and_poll_structural"
                            if self._partial_mode == "structural"
                            else "consume_and_poll_partial"
                        )
                    self._native_feed = getattr(native, method)
                    result = self._native_feed(data)
                except Exception:
                    pass
                else:
                    self._native_incremental = native
                    if _NATIVE_RESULT_TYPE is not None:
                        self.__dict__["feed"] = getattr(native, method)
                    if _NATIVE_RESULT_TYPE is not None and not copy_value:
                        return result
                    return self._result_from_native(result, copy_value)
            if self._native_incremental is not None:
                if self._native_feed is None:
                    method = (
                        "consume_and_poll_structural_result"
                        if self._partial_mode == "structural"
                        else "consume_and_poll_partial_result"
                    )
                    if _NATIVE_RESULT_TYPE is None:
                        method = (
                            "consume_and_poll_structural"
                            if self._partial_mode == "structural"
                            else "consume_and_poll_partial"
                        )
                    self._native_feed = getattr(self._native_incremental, method)
                result = self._native_feed(data)
                if _NATIVE_RESULT_TYPE is not None and not copy_value:
                    return result
                return self._result_from_native(result, copy_value)
            self._consume_structural_chunk(data)
            return self._poll_structural(copy_value)
        if self._framing != "single" or self._partial_mode != "strict":
            self.consume(data)
            return self.poll(copy_value=copy_value)
        if self._finished:
            raise RuntimeError("parser is finished; call reset() before consuming more data")
        if self._native_incremental is not None and _NATIVE_RESULT_TYPE is not None:
            if "feed" not in self.__dict__:
                self.__dict__["feed"] = self._native_incremental.consume_and_poll_result
            return self.__dict__["feed"](data, copy_value)
        if self._error:
            return self.poll(copy_value=copy_value)
        if self._complete:
            self.consume(data)
            return self.poll(copy_value=copy_value)
        if self._native_incremental is not None:
            if self._native_feed is None:
                method = (
                    "consume_and_poll_result"
                    if _NATIVE_RESULT_TYPE is not None
                    else "consume_and_poll"
                )
                self._native_feed = getattr(self._native_incremental, method)
            result = self._native_feed(data)
            if _NATIVE_RESULT_TYPE is not None and not copy_value:
                return result
            return self._result_from_native(result, copy_value)
        if (
            self._can_use_native_incremental()
            and not (
                isinstance(data, str)
                and not data.isascii()
                and len(data) < _NATIVE_UNICODE_CHUNK_THRESHOLD
            )
            and data != "{"
            and self._simple_string_state is None
        ):
            try:
                native = _new_native_incremental()
                method = (
                    "consume_and_poll_result"
                    if _NATIVE_RESULT_TYPE is not None
                    else "consume_and_poll"
                )
                self._native_feed = getattr(native, method)
                result = self._native_feed(data)
            except Exception:
                pass
            else:
                self._native_incremental = native
                if _NATIVE_RESULT_TYPE is not None:
                    self.__dict__["feed"] = getattr(native, method)
                if _NATIVE_RESULT_TYPE is not None and not copy_value:
                    return result
                return self._result_from_native(result, copy_value)
        if (
            self._incremental is None
            and self._native_incremental is None
            and self._simple_string_state is None
            and not self._has_pending()
        ):
            payload = _coerce_bytes(data)
            if _may_be_complete(data):
                parsed, error = self._try_complete_decode(payload)
                if error is None and parsed is not _INCOMPLETE:
                    if parsed is _INVALID:
                        self._error = "value does not match value_type"
                        return self.poll(copy_value=copy_value)
                    self._completed_value = parsed
                    self._complete = True
                    value = copy.deepcopy(parsed) if copy_value else parsed
                    return ParseResult(ParseStatus.COMPLETE, value, True)
        if (
            self._incremental is None
            and self._native_incremental is None
            and not self._has_pending()
            and (self._simple_string_state is not None or isinstance(data, str))
        ):
            result = self._feed_simple_string(data, copy_value)
            if result is not None:
                return result
        if (
            self._native_incremental is not None
            and hasattr(self._native_incremental, "consume_and_poll")
        ):
            if self._native_feed is None:
                method = (
                    "consume_and_poll_result"
                    if _NATIVE_RESULT_TYPE is not None
                    else "consume_and_poll"
                )
                self._native_feed = getattr(self._native_incremental, method)
            result = self._native_feed(data)
            if _NATIVE_RESULT_TYPE is not None and not copy_value:
                return result
            return self._result_from_native(result, copy_value)
        self.consume(data)
        return self.poll(copy_value=copy_value)

    def finish(self, copy_value: bool = False) -> ParseResult:
        self._finished = True
        if self._framing == "ndjson":
            self._fill_ready_ndjson()
            if not self._error and self._has_pending():
                final_line = (
                    self._pending_bytes
                    if self._pending_bytes is not None
                    else bytes(self._pending)
                )
                self._clear_pending()
                if final_line.strip():
                    self._decode_ndjson_payload(final_line)
            return self._poll_ndjson(copy_value)
        if self._simple_string_state is not None:
            self._fallback_simple_string()
        return self.poll(copy_value=copy_value)

    def poll(self, copy_value: bool = False) -> ParseResult:
        if self._framing == "ndjson":
            return self._poll_ndjson(copy_value)

        if self._error:
            return ParseResult(ParseStatus.INVALID, None, False, self._error)
        if self._complete:
            value = copy.deepcopy(self._completed_value) if copy_value else self._completed_value
            return ParseResult(ParseStatus.COMPLETE, value, True)

        if self._simple_string_state is not None:
            return self._simple_string_result(copy_value)

        if self._partial_mode != "strict":
            if self._native_incremental is not None:
                return self._poll_native_incremental(copy_value)
            return self._poll_structural(copy_value)

        incremental = self._incremental

        if incremental is None and self._has_pending():
            payload = self._pending_payload_bytes()
            if _may_be_complete(payload, allow_scalars=self._finished):
                parsed, error = self._try_complete_decode(payload)
                if error is None and parsed is not _INCOMPLETE:
                    self._clear_pending()
                    if parsed is _INVALID:
                        self._error = "value does not match value_type"
                        return ParseResult(ParseStatus.INVALID, None, False, self._error)
                    self._completed_value = parsed
                    self._complete = True
                    value = copy.deepcopy(parsed) if copy_value else parsed
                    return ParseResult(ParseStatus.COMPLETE, value, True)

        if self._native_incremental is not None:
            return self._poll_native_incremental(copy_value)

        if incremental is None and self._has_pending():
            payload = self._pending_payload_bytes()
            if self._activate_native_incremental(payload):
                return self._poll_native_incremental(copy_value)

        if self._has_pending():
            if incremental is None:
                incremental = _IncrementalStrictCore()
                self._incremental = incremental
            if self._pending_text:
                text = self._pending_text
                self._pending_text = ""
                incremental.started = True
                incremental.consume(text)
            else:
                pending = self._pending_bytes if self._pending_bytes is not None else bytes(self._pending)
                self._pending_bytes = None
                self._pending.clear()
                try:
                    text, incomplete_utf8 = _decode_pending_utf8(pending)
                    if incomplete_utf8:
                        self._pending.extend(incomplete_utf8)
                except UnicodeDecodeError as exc:
                    incremental.error = f"invalid utf-8 at byte {exc.start}"
                else:
                    incremental.started = True
                    incremental.consume(text)

        if incremental is None:
            return ParseResult(ParseStatus.EMPTY, None, False)

        if self._finished:
            incremental.finish()
        incremental.prepare_for_poll()

        if incremental.error:
            return ParseResult(ParseStatus.INVALID, self._value(copy_value), False, incremental.error)
        if incremental.complete:
            if self._value_type is not None:
                try:
                    completed = _get_cached_msgspec_decoder(self._value_type).decode(bytes(self._typed_payload))
                except Exception:
                    self._error = "value does not match value_type"
                    return ParseResult(ParseStatus.INVALID, self._value(copy_value), False, self._error)
                self._completed_value = completed
                self._complete = True
                value = copy.deepcopy(completed) if copy_value else completed
                return ParseResult(ParseStatus.COMPLETE, value, True)
            completed = self._value(copy_value=False)
            self._completed_value = completed
            self._complete = True
            value = copy.deepcopy(completed) if copy_value else completed
            return ParseResult(ParseStatus.COMPLETE, value, True)
        if incremental.root is None:
            if incremental.state != "expect_value":
                return ParseResult(ParseStatus.PARTIAL, None, False)
            return ParseResult(ParseStatus.EMPTY, None, False)
        return ParseResult(ParseStatus.PARTIAL, self._value(copy_value), False)

    def poll_many(self, *, copy_value: bool = False, max_items: int | None = None) -> list[Any]:
        if self._framing != "ndjson":
            result = self.poll(copy_value=copy_value)
            if result.status == ParseStatus.COMPLETE:
                return [result.value]
            return []

        if (
            not self._error
            and not self._ready_values
            and max_items is None
            and not copy_value
            and self._has_pending()
        ):
            direct = self._drain_ndjson_prefix_direct()
            if direct is not None:
                return direct

        self._fill_ready_ndjson()
        if max_items is None or max_items >= len(self._ready_values):
            items = list(self._ready_values)
            self._ready_values.clear()
        else:
            items = [self._ready_values.popleft() for _ in range(max_items)]
        if copy_value:
            return [copy.deepcopy(item) for item in items]
        return items

    def reset(self) -> None:
        self._pending.clear()
        self._pending_bytes = None
        self._pending_text = ""
        if self._typed_payload is not None:
            self._typed_payload.clear()
        self._simple_string_state = None
        self._incremental = None
        self._native_incremental = None
        self._native_feed = None
        self.__dict__.pop("feed", None)
        self.__dict__.pop("poll", None)
        self.__dict__.pop("finish", None)
        self._ndjson_decoder = _get_cached_msgspec_decoder(self._record_type) if self._record_type is not None else None
        self._ready_values.clear()
        self._complete = False
        self._completed_value = None
        self._error = None
        self._finished = False
        self._install_eager_native_strict()

    def _value(self, copy_value: bool) -> Any | None:
        if self._incremental is None:
            return copy.deepcopy(self._completed_value) if copy_value else self._completed_value
        return copy.deepcopy(self._incremental.root) if copy_value else self._incremental.root

    def _simple_string_result(self, copy_value: bool) -> ParseResult:
        state = self._simple_string_state
        if state is None:
            return ParseResult(ParseStatus.EMPTY, None, False)
        value = {} if state.key is None else {state.key: state.value}
        if copy_value:
            value = copy.deepcopy(value)
        return ParseResult(ParseStatus.PARTIAL, value, False)

    def _fallback_simple_string(self, copy_value: bool = False) -> ParseResult:
        state = self._simple_string_state
        if state is None:
            return self.poll(copy_value=copy_value)
        self._simple_string_state = None
        raw = "".join(state.raw_parts)
        if self._can_use_native_incremental():
            try:
                native = _new_native_incremental()
                method = (
                    "consume_and_poll_result"
                    if _NATIVE_RESULT_TYPE is not None
                    else "consume_and_poll"
                )
                result = getattr(native, method)(raw)
            except Exception:
                pass
            else:
                self._native_incremental = native
                return self._result_from_native(result, copy_value)
        self._pending_text = raw
        return self.poll(copy_value=copy_value)

    def _feed_simple_string(
        self,
        data: str | bytes | bytearray,
        copy_value: bool,
    ) -> ParseResult | None:
        if not (
            self._framing == "single"
            and self._partial_mode == "strict"
            and self._value_type is None
            and self._schema_mode == "generic"
        ):
            return None
        if not isinstance(data, str):
            if self._simple_string_state is None:
                return None
            return self._fallback_simple_string(copy_value)
        if self._simple_string_state is None:
            if not data:
                return None
            self._simple_string_state = _SimpleStringFeedState()
        state = self._simple_string_state
        phase_before_append = state.phase
        state.raw_parts.append(data)
        tail_from_current_chunk: str | None = None

        if state.phase == 0:
            raw = "".join(state.raw_parts)
            if not raw.startswith('{"'):
                if raw == "{":
                    return self._simple_string_result(copy_value)
                return self._fallback_simple_string(copy_value)
            marker = raw.find('\":\"', 2)
            if marker == -1:
                key_colon = raw.find('\":', 2)
                if key_colon != -1 and raw[key_colon + 2 :]:
                    return self._fallback_simple_string(copy_value)
                return self._simple_string_result(copy_value)
            key = raw[2:marker]
            if not key or '"' in key or "\\" in key:
                return self._fallback_simple_string(copy_value)
            state.key = key
            state.value_start = marker + 3
            state.scan_index = state.value_start
            state.phase = 1

        if state.phase == 1:
            raw = "".join(state.raw_parts) if phase_before_append == 0 else data
            start_index = state.scan_index if phase_before_append == 0 else 0
            for index in range(start_index, len(raw)):
                char = raw[index]
                if char == "\\" or ord(char) < 0x20:
                    return self._fallback_simple_string(copy_value)
                if char == '"':
                    state.value += raw[start_index:index]
                    if (
                        len(state.value) > _SIMPLE_STRING_NATIVE_HANDOFF_LENGTH
                        and self._can_use_native_incremental()
                    ):
                        return self._fallback_simple_string(copy_value)
                    if len(state.value) > _SIMPLE_STRING_MAX_VALUE_LENGTH:
                        return self._fallback_simple_string(copy_value)
                    state.scan_index = index + 1 if phase_before_append == 0 else 0
                    tail_from_current_chunk = raw[index + 1 :]
                    state.phase = 2
                    break
            else:
                state.value += raw[start_index:]
                if (
                    len(state.value) > _SIMPLE_STRING_NATIVE_HANDOFF_LENGTH
                    and self._can_use_native_incremental()
                ):
                    return self._fallback_simple_string(copy_value)
                if len(state.value) > _SIMPLE_STRING_MAX_VALUE_LENGTH:
                    return self._fallback_simple_string(copy_value)
                state.scan_index = len(raw) if phase_before_append == 0 else 0
                return self._simple_string_result(copy_value)

        if state.phase == 2:
            if tail_from_current_chunk is not None:
                tail = tail_from_current_chunk
            elif phase_before_append < 2:
                raw = "".join(state.raw_parts)
                tail = raw[state.scan_index:]
            else:
                tail = data
            first_non_whitespace = next(
                (index for index, char in enumerate(tail) if char not in " \n\r\t"),
                None,
            )
            if first_non_whitespace is None:
                return self._simple_string_result(copy_value)
            if tail[first_non_whitespace] != "}":
                return self._fallback_simple_string(copy_value)
            if tail[first_non_whitespace + 1 :].strip(" \n\r\t"):
                return self._fallback_simple_string(copy_value)
            value = {state.key: state.value}
            self._simple_string_state = None
            self._completed_value = value
            self._complete = True
            completed = copy.deepcopy(value) if copy_value else value
            return ParseResult(ParseStatus.COMPLETE, completed, True)

        return self._simple_string_result(copy_value)

    def _can_use_native_incremental(self) -> bool:
        if not (
            self._framing == "single"
            and self._partial_mode in {"strict", "structural", "structural_trailing_strings"}
            and self._value_type is None
            and self._schema_mode == "generic"
            and _backend_native is not None
            and hasattr(_backend_native, "IncrementalJsonParser")
        ):
            return False
        if self._partial_mode == "strict":
            required = (
                (
                    "consume_and_poll_result",
                    "poll_result_value",
                    "finish_result",
                )
                if _NATIVE_RESULT_TYPE is not None
                else ("consume_and_poll", "poll", "finish")
            )
            return all(hasattr(_backend_native.IncrementalJsonParser, method) for method in required)
        parser_type = _backend_native.IncrementalJsonParser
        required = (
            ("poll_structural", "finish_structural")
            if self._partial_mode == "structural"
            else ("poll_partial", "finish_partial")
        )
        return all(hasattr(parser_type, method) for method in required)

    def _has_pending(self) -> bool:
        return bool(self._pending or self._pending_text or self._pending_bytes is not None)

    def _pending_payload_bytes(self) -> bytes:
        if self._pending_text:
            return self._pending_text.encode("utf-8")
        if self._pending_bytes is not None:
            return self._pending_bytes
        return bytes(self._pending)

    def _materialize_pending_bytes(self) -> None:
        if self._pending_bytes is not None:
            self._pending.extend(self._pending_bytes)
            self._pending_bytes = None

    def _clear_pending(self) -> None:
        self._pending.clear()
        self._pending_bytes = None
        self._pending_text = ""

    def _consume_structural_chunk(self, data: str | bytes | bytearray) -> None:
        self._materialize_pending_bytes()
        if isinstance(data, str):
            self._pending.extend(data.encode("utf-8"))
        elif isinstance(data, (bytes, bytearray)):
            self._pending.extend(data)
        else:
            raise TypeError("data must be str, bytes, or bytearray")

    def _poll_structural(self, copy_value: bool) -> ParseResult:
        if self._error:
            return ParseResult(ParseStatus.INVALID, None, False, self._error)
        if self._complete:
            value = copy.deepcopy(self._completed_value) if copy_value else self._completed_value
            return ParseResult(ParseStatus.COMPLETE, value, True)
        if not self._has_pending():
            return ParseResult(ParseStatus.EMPTY, None, False)
        payload: str | bytes = (
            self._pending_text
            if self._pending_text
            else self._pending_bytes
            if self._pending_bytes is not None
            else bytes(self._pending)
        )
        if self._finished or _has_closed_root_suffix_hint(payload):
            parsed, error = self._try_complete_decode(_coerce_bytes(payload))
            if error is None and parsed is not _INCOMPLETE:
                self._clear_pending()
                if parsed is _INVALID:
                    self._error = "invalid json document"
                    return ParseResult(ParseStatus.INVALID, None, False, self._error)
                self._completed_value = parsed
                self._complete = True
                value = copy.deepcopy(parsed) if copy_value else parsed
                return ParseResult(ParseStatus.COMPLETE, value, True)
        allow_partial = (
            "trailing-strings"
            if self._partial_mode == "structural_trailing_strings"
            else True
        )
        try:
            value = _decode_structural_prefix(
                payload,
                trailing_strings=allow_partial == "trailing-strings",
            )
        except Exception:
            self._error = "invalid json document"
            return ParseResult(ParseStatus.INVALID, None, False, self._error)
        if self._finished:
            self._error = "incomplete json document"
            partial = copy.deepcopy(value) if copy_value else value
            return ParseResult(ParseStatus.INVALID, partial, False, self._error)
        partial = copy.deepcopy(value) if copy_value else value
        return ParseResult(ParseStatus.PARTIAL, partial, False)

    def _activate_native_incremental(self, payload: bytes) -> bool:
        if not self._can_use_native_incremental():
            return False
        try:
            native = _new_native_incremental()
            native.consume(payload)
        except Exception:
            return False
        self._native_incremental = native
        self._clear_pending()
        return True

    def _poll_native_incremental(self, copy_value: bool) -> ParseResult:
        if self._partial_mode == "structural":
            result = (
                getattr(
                    self._native_incremental,
                    "finish_structural_result"
                    if _NATIVE_RESULT_TYPE is not None
                    else "finish_structural",
                )()
                if self._finished
                else getattr(
                    self._native_incremental,
                    "poll_structural_result"
                    if _NATIVE_RESULT_TYPE is not None
                    else "poll_structural",
                )()
            )
        elif self._partial_mode == "structural_trailing_strings":
            result = (
                getattr(
                    self._native_incremental,
                    "finish_partial_result"
                    if _NATIVE_RESULT_TYPE is not None
                    else "finish_partial",
                )()
                if self._finished
                else getattr(
                    self._native_incremental,
                    "poll_partial_result"
                    if _NATIVE_RESULT_TYPE is not None
                    else "poll_partial",
                )()
            )
        else:
            result = (
                getattr(
                    self._native_incremental,
                    "finish_result"
                    if _NATIVE_RESULT_TYPE is not None
                    else "finish",
                )()
                if self._finished
                else getattr(
                    self._native_incremental,
                    "poll_result_value"
                    if _NATIVE_RESULT_TYPE is not None
                    else "poll",
                )()
            )
        return self._result_from_native(result, copy_value)

    def _result_from_native(self, result: Any, copy_value: bool) -> ParseResult:
        if _NATIVE_RESULT_TYPE is not None:
            if not copy_value:
                return result
            status = result.status
            value = result.value
            return ParseResult(
                status,
                copy.deepcopy(value),
                result.complete,
                result.error,
            )
        status, value, error = result
        if status == "invalid":
            self._error = error or "invalid json document"
            return ParseResult(
                ParseStatus.INVALID,
                copy.deepcopy(value) if copy_value else value,
                False,
                self._error,
            )
        if status == "complete":
            self._completed_value = value
            self._complete = True
            completed = copy.deepcopy(value) if copy_value else value
            return ParseResult(ParseStatus.COMPLETE, completed, True)
        if status == "partial":
            partial = copy.deepcopy(value) if copy_value else value
            return ParseResult(ParseStatus.PARTIAL, partial, False)
        return ParseResult(ParseStatus.EMPTY, None, False)

    def _try_complete_decode(self, payload: bytes) -> tuple[Any, str | None]:
        if not payload.strip():
            return _INCOMPLETE, None
        if self._value_type is not None:
            try:
                return _decode_complete_bytes(payload, value_type=self._value_type), None
            except Exception:
                pass
            try:
                _decode_complete_bytes(payload)
            except Exception:
                return _INCOMPLETE, None
            else:
                return _INVALID, None
        try:
            return _decode_complete_bytes(payload), None
        except Exception:
            return _INCOMPLETE, None

    def _poll_ndjson(self, copy_value: bool) -> ParseResult:
        if self._error:
            return ParseResult(ParseStatus.INVALID, None, False, self._error)
        if self._ready_values:
            value = self._ready_values.popleft()
            return ParseResult(ParseStatus.COMPLETE, copy.deepcopy(value) if copy_value else value, True)

        self._fill_ready_ndjson()

        if self._error:
            return ParseResult(ParseStatus.INVALID, None, False, self._error)
        if self._ready_values:
            value = self._ready_values.popleft()
            return ParseResult(ParseStatus.COMPLETE, copy.deepcopy(value) if copy_value else value, True)
        if self._has_pending():
            return ParseResult(ParseStatus.PARTIAL, None, False)
        return ParseResult(ParseStatus.EMPTY, None, False)

    def _decode_ndjson_payload(self, payload: bytes) -> None:
        try:
            decoder = self._ndjson_decoder
            if self._schema_mode == "adaptive" and decoder is None and _GLOBAL_MSGSPEC_DECODER is not None:
                first_line = next((line for line in payload.split(b"\n") if line), b"")
                if first_line:
                    decoder = _build_specialized_ndjson_decoder(_GLOBAL_MSGSPEC_DECODER.decode(first_line))
                    self._ndjson_decoder = decoder
            self._ready_values.extend(_decode_ndjson_complete_prefix_with_decoder(payload, decoder))
        except Exception:
            if self._schema_mode == "adaptive":
                self._ndjson_decoder = None
                try:
                    self._ready_values.extend(_decode_ndjson_complete_prefix(payload))
                except Exception:
                    self._error = "invalid ndjson line"
            else:
                self._error = "invalid ndjson line"

    def _fill_ready_ndjson(self) -> None:
        if self._error or not self._has_pending():
            return
        complete_prefix = self._extract_complete_ndjson_prefix()
        if complete_prefix is not None:
            try:
                decoder = self._ndjson_decoder
                if self._schema_mode == "adaptive" and decoder is None and _GLOBAL_MSGSPEC_DECODER is not None:
                    first_line = next((line for line in complete_prefix.split(b"\n") if line), b"")
                    if first_line:
                        decoder = _build_specialized_ndjson_decoder(_GLOBAL_MSGSPEC_DECODER.decode(first_line))
                        self._ndjson_decoder = decoder
                self._ready_values.extend(_decode_ndjson_complete_prefix_with_decoder(complete_prefix, decoder))
            except Exception:
                if self._schema_mode == "adaptive":
                    self._ndjson_decoder = None
                    try:
                        self._ready_values.extend(_decode_ndjson_complete_prefix(complete_prefix))
                    except Exception:
                        self._error = "invalid ndjson line"
                else:
                    self._error = "invalid ndjson line"

    def _drain_ndjson_prefix_direct(self) -> list[Any] | None:
        complete_prefix = self._extract_complete_ndjson_prefix()
        if complete_prefix is None:
            return None
        try:
            decoder = self._ndjson_decoder
            if self._schema_mode == "adaptive" and decoder is None and _GLOBAL_MSGSPEC_DECODER is not None:
                first_line = next((line for line in complete_prefix.split(b"\n") if line), b"")
                if first_line:
                    decoder = _build_specialized_ndjson_decoder(_GLOBAL_MSGSPEC_DECODER.decode(first_line))
                    self._ndjson_decoder = decoder
            return _decode_ndjson_complete_prefix_with_decoder(complete_prefix, decoder)
        except Exception:
            if self._schema_mode == "adaptive":
                self._ndjson_decoder = None
                try:
                    return _decode_ndjson_complete_prefix(complete_prefix)
                except Exception:
                    self._error = "invalid ndjson line"
                    return None
            self._error = "invalid ndjson line"
            return None

    def _extract_complete_ndjson_prefix(self) -> bytes | None:
        if self._pending_bytes is not None:
            payload = self._pending_bytes
            last_newline_index = payload.rfind(b"\n")
            if last_newline_index == -1:
                return None
            self._pending_bytes = (
                payload[last_newline_index + 1 :]
                or None
            )
            return payload[: last_newline_index + 1]
        last_newline_index = self._pending.rfind(b"\n")
        if last_newline_index == -1:
            return None
        complete_prefix = bytes(self._pending[: last_newline_index + 1])
        del self._pending[: last_newline_index + 1]
        return complete_prefix


class _NativeStrictFacade(HighPerformanceStreamingJsonParser):
    """Slot-bound native methods for the default strict single-document path."""

    __slots__ = ("consume", "feed", "poll", "finish", "reset")


class _IncrementalStrictCore:
    __slots__ = (
        "root",
        "stack",
        "state",
        "current_key",
        "string_mode",
        "string_buffer",
        "escape",
        "unicode_escape",
        "unicode_digits",
        "pending_high_surrogate",
        "partial_string_attached",
        "partial_string_index",
        "number_buffer",
        "literal_buffer",
        "complete",
        "error",
        "started",
        "_partial_string_materialized",
    )

    def __init__(self) -> None:
        self.root: Any | None = None
        self.stack: list[dict[str, Any]] = []
        self.state = "expect_value"
        self.current_key: str | None = None
        self.string_mode: str | None = None
        self.string_buffer: list[str] = []
        self.escape = False
        self.unicode_escape = False
        self.unicode_digits: list[str] = []
        self.pending_high_surrogate: int | None = None
        self.partial_string_attached = False
        self.partial_string_index: int | None = None
        self.number_buffer: list[str] = []
        self.literal_buffer: list[str] = []
        self.complete = False
        self.error: str | None = None
        self.started = False
        self._partial_string_materialized = False

    def consume(self, chunk: str) -> None:
        if self.complete or self.error:
            return
        if chunk:
            self.started = True
        for ch in chunk:
            if self.state == "in_string":
                self._consume_string_char(ch)
                continue
            if self.state == "in_number":
                if ch in "0123456789+-.eE":
                    self.number_buffer.append(ch)
                    continue
                self._finalize_number()
                if self.error:
                    return
                self._consume_nonstring_char(ch)
                continue
            if self.state == "in_literal":
                if ch.isalpha():
                    self.literal_buffer.append(ch)
                    token = "".join(self.literal_buffer)
                    if not any(literal.startswith(token) for literal in ("true", "false", "null")):
                        self.error = f"invalid literal prefix {token[:16]!r}"
                    elif len(self.literal_buffer) > 5:
                        self.error = f"invalid literal prefix {token[:16]!r}"
                    continue
                self._finalize_literal()
                if self.error:
                    return
                self._consume_nonstring_char(ch)
                continue
            self._consume_nonstring_char(ch)

    def finish(self) -> None:
        if self.complete or self.error:
            return
        if self.state == "in_number":
            self._finalize_number()
        elif self.state == "in_literal":
            self._finalize_literal()
        if self.error or self.complete:
            return
        if self.started and not self.stack and self.state == "after_value":
            self.complete = True
            self.state = "done"
            return
        if self.root is None and self.state == "expect_value":
            return
        self.error = "incomplete json document"

    def prepare_for_poll(self) -> None:
        if self.state == "in_string" and self.string_mode == "value":
            self._materialize_partial_string_value()

    def _consume_nonstring_char(self, ch: str) -> None:
        if ch in " \n\r\t":
            return
        if self.complete:
            self.error = f"extra trailing data starting with {ch!r}"
            return
        if self.state == "expect_value":
            self._start_value(ch)
            return
        if self.state == "expect_key_or_end":
            if ch == "}":
                self._close_container("object")
            elif ch == '"':
                self._begin_string("key")
            else:
                self.error = f"expected object key or end, got {ch!r}"
            return
        if self.state == "after_key":
            if ch == ":":
                self.state = "expect_value"
            else:
                self.error = f"expected colon after key, got {ch!r}"
            return
        if self.state == "after_value":
            ctx = self.stack[-1] if self.stack else None
            if ctx is None:
                self.complete = True
                self.error = f"extra trailing data starting with {ch!r}"
            elif ctx["type"] == "object":
                if ch == ",":
                    self.state = "expect_key"
                elif ch == "}":
                    self._close_container("object")
                else:
                    self.error = f"expected comma or object end, got {ch!r}"
            else:
                if ch == ",":
                    self.state = "expect_value"
                elif ch == "]":
                    self._close_container("array")
                else:
                    self.error = f"expected comma or array end, got {ch!r}"
            return
        if self.state == "expect_key":
            if ch == '"':
                self._begin_string("key")
            else:
                self.error = f"expected object key, got {ch!r}"
            return
        if self.state == "expect_array_or_end":
            if ch == "]":
                self._close_container("array")
            else:
                self.state = "expect_value"
                self._consume_nonstring_char(ch)
            return
        self.error = f"unexpected parser state {self.state!r}"

    def _start_value(self, ch: str) -> None:
        if ch == "{":
            obj: dict[str, Any] = {}
            self._attach_value(obj)
            self.stack.append({"type": "object", "value": obj})
            self.state = "expect_key_or_end"
        elif ch == "[":
            arr: list[Any] = []
            self._attach_value(arr)
            self.stack.append({"type": "array", "value": arr})
            self.state = "expect_array_or_end"
        elif ch == '"':
            self._begin_string("value")
        elif ch in "-0123456789":
            self.state = "in_number"
            self.number_buffer = [ch]
        elif ch in "tfn":
            self.state = "in_literal"
            self.literal_buffer = [ch]
        else:
            self.error = f"expected value, got {ch!r}"

    def _attach_value(self, value: Any) -> None:
        if self.root is None:
            self.root = value
            if not isinstance(value, (dict, list)):
                self.state = "after_value"
            return
        if not self.stack:
            self.error = "received extra top-level value"
            return
        ctx = self.stack[-1]
        if ctx["type"] == "object":
            if self.current_key is None:
                self.error = "missing object key for value"
                return
            ctx["value"][self.current_key] = value
            self.current_key = None
        else:
            ctx["value"].append(value)
        self.state = "after_value"

    def _begin_string(self, mode: str) -> None:
        self.state = "in_string"
        self.string_mode = mode
        self.string_buffer = []
        self.escape = False
        self.unicode_escape = False
        self.unicode_digits = []
        self.pending_high_surrogate = None
        self.partial_string_attached = False
        self.partial_string_index = None
        self._partial_string_materialized = False

    def _append_unicode_code_unit(self, code_unit: int) -> None:
        if self.pending_high_surrogate is not None:
            if 0xDC00 <= code_unit <= 0xDFFF:
                scalar = 0x10000 + ((self.pending_high_surrogate - 0xD800) << 10) + (code_unit - 0xDC00)
                self.string_buffer.append(chr(scalar))
                self.pending_high_surrogate = None
                return
            self.error = "invalid unicode surrogate pair"
            return
        if 0xD800 <= code_unit <= 0xDBFF:
            self.pending_high_surrogate = code_unit
        elif 0xDC00 <= code_unit <= 0xDFFF:
            self.error = "invalid unicode surrogate pair"
        else:
            self.string_buffer.append(chr(code_unit))

    def _consume_string_char(self, ch: str) -> None:
        if self.unicode_escape:
            if ch.lower() in "0123456789abcdef":
                self.unicode_digits.append(ch)
                if len(self.unicode_digits) == 4:
                    self._append_unicode_code_unit(int("".join(self.unicode_digits), 16))
                    self.unicode_digits = []
                    self.unicode_escape = False
                    self.escape = False
                    self._partial_string_materialized = False
                return
            self.error = "invalid unicode escape"
            return
        if self.escape:
            escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
            if ch == "u":
                self.unicode_escape = True
                self.unicode_digits = []
                return
            if ch not in escapes:
                self.error = f"invalid escape {ch!r}"
                return
            if self.pending_high_surrogate is not None:
                self.error = "invalid unicode surrogate pair"
                return
            self.string_buffer.append(escapes[ch])
            self.escape = False
            self._partial_string_materialized = False
            return
        if ch == "\\":
            self.escape = True
            return
        if ch == '"':
            if self.pending_high_surrogate is not None:
                self.error = "invalid unicode surrogate pair"
                return
            value = "".join(self.string_buffer)
            if self.string_mode == "key":
                self.current_key = value
                self.state = "after_key"
            else:
                if self.partial_string_attached:
                    if self.stack:
                        ctx = self.stack[-1]
                        if ctx["type"] == "object":
                            if self.current_key is not None:
                                ctx["value"][self.current_key] = value
                                self.current_key = None
                        elif self.partial_string_index is not None:
                            ctx["value"][self.partial_string_index] = value
                    else:
                        self.root = value
                    self.state = "after_value"
                else:
                    self._attach_value(value)
            self.string_mode = None
            self.string_buffer = []
            self.partial_string_attached = False
            self.partial_string_index = None
            self._partial_string_materialized = False
            return
        if ord(ch) < 0x20:
            self.error = "invalid control character in string"
            return
        if self.pending_high_surrogate is not None:
            self.error = "invalid unicode surrogate pair"
            return
        self.string_buffer.append(ch)
        self._partial_string_materialized = False

    def _materialize_partial_string_value(self) -> None:
        if self._partial_string_materialized:
            return
        value = "".join(self.string_buffer)
        if self.stack:
            ctx = self.stack[-1]
            if ctx["type"] == "object":
                if self.current_key is None:
                    return
                ctx["value"][self.current_key] = value
            elif not self.partial_string_attached:
                ctx["value"].append(value)
                self.partial_string_index = len(ctx["value"]) - 1
            elif self.partial_string_index is not None:
                ctx["value"][self.partial_string_index] = value
        elif self.root is None or self.partial_string_attached:
            self.root = value
        else:
            return
        self.partial_string_attached = True
        self._partial_string_materialized = True

    def _finalize_number(self) -> None:
        token = "".join(self.number_buffer)
        self.number_buffer = []
        self.state = "after_value"
        try:
            value = json.loads(token)
        except json.JSONDecodeError:
            self.error = f"invalid number {token!r}"
            return
        self._attach_value(value)

    def _finalize_literal(self) -> None:
        token = "".join(self.literal_buffer)
        self.literal_buffer = []
        self.state = "after_value"
        mapping = {"true": True, "false": False, "null": None}
        if token not in mapping:
            self.error = f"invalid literal {token!r}"
            return
        self._attach_value(mapping[token])

    def _close_container(self, expected_type: str) -> None:
        if not self.stack:
            self.error = f"unexpected closing token for {expected_type}"
            return
        ctx = self.stack.pop()
        if ctx["type"] != expected_type:
            self.error = f"mismatched close for {expected_type}"
            return
        if not self.stack:
            self.complete = True
            self.state = "done"
        else:
            self.state = "after_value"
