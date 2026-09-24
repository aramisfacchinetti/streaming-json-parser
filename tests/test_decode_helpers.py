import importlib.util
import json
from types import SimpleNamespace

import pytest

import msgspec

import streaming_json_parser.high_performance_parser as high_performance_parser
from streaming_json_parser import (decode_complete_json, decode_ndjson,
                                   decode_ndjson_adaptive,
                                   decode_complete_json_view,
                                   HighPerformanceStreamingJsonParser,
                                   extract_complete_json_paths,
                                   extract_complete_json_typed_paths,
                                   extract_ndjson_paths,
                                   extract_tuned_json_paths,
                                   extract_tuned_complete_json_paths,
                                   extract_tuned_ndjson_paths,
                                   extract_ndjson_paths_native,
                                   extract_ndjson_typed_paths,
                                   ParseStatus,
                                   StreamingJsonParser,
                                   make_complete_json_decoder,
                                   make_complete_json_typed_path_extractor,
                                   make_ndjson_path_extractor,
                                   make_tuned_ndjson_decoder,
                                   make_tuned_json_path_extractor,
                                   make_tuned_complete_json_path_extractor,
                                   make_tuned_ndjson_path_extractor,
                                   make_tuned_complete_json_decoder,
                                   make_tuned_structural_partial_decoder,
                                   make_complete_json_view_decoder,
                                   make_json_path_extractor,
                                   make_ndjson_path_extractor_native,
                                   make_ndjson_typed_path_extractor,
                                   make_ndjson_decoder)


def test_decode_complete_json_object():
    assert decode_complete_json(b'{"a":1,"b":[1,2,3]}') == {"a": 1, "b": [1, 2, 3]}


def test_decode_ndjson_adaptive_uses_stable_schema_when_available():
    payload = b'{"a":1,"b":"x"}\n{"a":2,"b":"y"}\n'

    result = decode_ndjson_adaptive(payload)

    assert [item.a for item in result] == [1, 2]
    assert [item.b for item in result] == ["x", "y"]


def test_decode_ndjson_adaptive_discards_stale_schema_on_shape_change():
    decode_ndjson_adaptive(b'{"a":1,"b":"x"}\n')

    result = decode_ndjson_adaptive(b'{"a":2,"c":"y"}\n')

    assert result[0].a == 2
    assert result[0].c == "y"


def test_decode_complete_json_tiny_payload_uses_orjson_fallback_fast_path(monkeypatch):
    calls = []

    def fake_orjson_loads(payload):
        calls.append(payload)
        return {"fast": True}

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=fake_orjson_loads),
    )
    monkeypatch.setattr(high_performance_parser, "_GLOBAL_MSGSPEC_DECODER", None)
    assert decode_complete_json(b'{"a":1}') == {"fast": True}
    assert calls == [b'{"a":1}']


def test_decode_complete_json_tiny_payload_prefers_msgspec(monkeypatch):
    calls = []

    def fake_msgspec_decode(payload):
        calls.append(payload)
        return {"msgspec": True}

    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=fake_msgspec_decode),
    )
    assert decode_complete_json(b'{"a":1}') == {"msgspec": True}
    assert calls == [b'{"a":1}']


def test_decode_complete_json_tiny_numeric_array_prefers_orjson(monkeypatch):
    calls = []

    def fake_orjson_loads(payload):
        calls.append(payload)
        return [1, 2, 3]

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=fake_orjson_loads),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=lambda _payload: ["wrong backend"]),
    )
    assert decode_complete_json(b"[1,2,3]") == [1, 2, 3]
    assert calls == [b"[1,2,3]"]


def test_decode_complete_json_subnative_scalar_skips_shape_dispatch(monkeypatch):
    calls = []

    def fake_msgspec_decode(payload):
        calls.append(payload)
        return "scalar-fast-path"

    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=fake_msgspec_decode),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_select_complete_decoder",
        lambda *_args, **_kwargs: pytest.fail("shape dispatch should be skipped"),
    )

    assert decode_complete_json(" " + ("1" * 300)) == "scalar-fast-path"
    assert calls == [" " + ("1" * 300)]


def test_decode_complete_json_escape_heavy_payload_prefers_orjson(monkeypatch):
    calls = []

    def fake_orjson_loads(payload):
        calls.append(payload)
        return {"fast": True}

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=fake_orjson_loads),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=lambda _payload: {"wrong": True}),
    )
    payload = json.dumps({"data": "\\n\\t\\\"\\\\" * 8}, separators=(",", ":"))

    assert decode_complete_json(payload) == {"fast": True}
    assert calls == [payload]


def test_decode_complete_json_compact_nested_array_prefers_orjson(monkeypatch):
    calls = []

    def fake_orjson_loads(payload):
        calls.append(payload)
        return ["orjson"]

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=fake_orjson_loads),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=lambda _payload: ["wrong backend"]),
    )
    payload = json.dumps(
        [list(range(20)), list(range(20))],
        separators=(",", ":"),
    )

    assert decode_complete_json(payload) == ["orjson"]
    assert calls == [payload]


def test_tuned_complete_decoder_wide_object_prefers_orjson(monkeypatch):
    orjson_decoder = SimpleNamespace(loads=lambda payload: json.loads(payload))
    msgspec_decoder = SimpleNamespace(decode=lambda _payload: {"wrong": True})
    monkeypatch.setattr(high_performance_parser, "_backend_orjson", orjson_decoder)
    monkeypatch.setattr(high_performance_parser, "_GLOBAL_MSGSPEC_DECODER", msgspec_decoder)
    payload = json.dumps(
        {f"key_{index}": index for index in range(16)},
        separators=(",", ":"),
    ).encode()

    decoder = make_tuned_complete_json_decoder(sample=payload)
    assert decoder(payload) == json.loads(payload)


def test_tuned_complete_decoder_nested_array_prefers_orjson(monkeypatch):
    calls = []

    def fake_orjson_loads(payload):
        calls.append(payload)
        return ["orjson"]

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=fake_orjson_loads),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=lambda _payload: ["wrong backend"]),
    )
    payload = b"[[" + b",".join(str(index).encode() for index in range(12000)) + b"]]"

    decoder = make_tuned_complete_json_decoder(sample=payload)
    assert decoder(payload) == ["orjson"]
    assert calls == [payload]


def test_tuned_complete_decoder_calibrates_compact_nested_array(monkeypatch):
    calls = []

    def fake_orjson_loads(payload):
        calls.append(payload)
        return json.loads(payload)

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=fake_orjson_loads),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=lambda _payload: ["wrong backend"]),
    )
    payload = json.dumps(
        [list(range(20)), list(range(20))],
        separators=(",", ":"),
    ).encode()

    decoder = make_tuned_complete_json_decoder(
        sample=payload,
        payload_size_hint=len(payload),
    )

    assert decoder(payload) == json.loads(payload)
    assert calls


def test_tuned_complete_decoder_large_string_array_prefers_msgspec(monkeypatch):
    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=lambda _payload: ["wrong backend"]),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=lambda _payload: ["msgspec"]),
    )
    payload = b"[" + b",".join(b'"x"' for _ in range(20000)) + b"]"

    decoder = make_tuned_complete_json_decoder(sample=payload)
    assert decoder(payload) == ["msgspec"]


def test_tuned_complete_decoder_very_wide_object_prefers_orjson(monkeypatch):
    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=lambda _payload: ["wrong backend"]),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=lambda _payload: ["msgspec"]),
    )
    payload = b"{" + b",".join(
        b'"key_' + str(index).encode() + b'":' + str(index).encode()
        for index in range(30000)
    ) + b"}"

    decoder = make_tuned_complete_json_decoder(sample=payload)
    assert decoder(payload) == ["wrong backend"]


def test_decode_complete_json_array():
    assert decode_complete_json("[1,2,3]") == [1, 2, 3]


def test_decode_complete_json_handles_escaped_object_keys():
    assert decode_complete_json(b'{"a\\\"b":{"x":1}}') == {"a\"b": {"x": 1}}


def test_decode_complete_json_preserves_large_utf8_strings():
    value = {"text": "hé🙂" * 300}
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    assert decode_complete_json(payload) == value
    assert decode_complete_json(payload.decode("utf-8")) == value


def test_decode_complete_json_preserves_large_bytearray_input(monkeypatch):
    calls = []

    def decoder(payload):
        calls.append(type(payload))
        return json.loads(payload)

    monkeypatch.setattr(
        high_performance_parser,
        "_select_complete_decoder",
        lambda _payload, value_type=None: decoder,
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_coerce_bytes",
        lambda _payload: pytest.fail("bytearray dispatch copied before backend invocation"),
    )
    payload = bytearray(
        json.dumps({"data": "x" * 20_000}, separators=(",", ":")).encode()
    )

    assert decode_complete_json(payload) == json.loads(payload)
    assert calls == [bytearray]


def test_make_complete_json_decoder_preserves_large_utf8_strings():
    value = {"text": "hé🙂" * 300}
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    decoder = make_complete_json_decoder()

    assert decoder(payload) == value


def test_make_complete_json_decoder_preserves_bytearray_input(monkeypatch):
    calls = []

    def decoder(payload):
        calls.append(type(payload))
        return json.loads(payload)

    monkeypatch.setattr(
        high_performance_parser,
        "_select_complete_decoder",
        lambda payload, value_type=None: decoder,
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_coerce_bytes",
        lambda _payload: pytest.fail("reusable bytearray decoder copied input"),
    )
    payload = bytearray(
        json.dumps({"data": "x" * 20_000}, separators=(",", ":")).encode()
    )

    reusable = make_complete_json_decoder()
    assert reusable(payload) == json.loads(payload)
    payload[:] = b"[1,2,3]"
    assert reusable(payload) == [1, 2, 3]
    assert calls == [bytearray, bytearray]


def test_decode_complete_json_does_not_route_utf8_bytes_to_yyjson(monkeypatch):
    calls = []

    def wrong_yyjson_decoder(payload):
        calls.append(payload)
        return {"wrong": True}

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_yyjson",
        SimpleNamespace(loads=wrong_yyjson_decoder),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=lambda payload: json.loads(payload)),
    )
    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(high_performance_parser, "_backend_native", None)
    monkeypatch.setattr(high_performance_parser, "_GLOBAL_SIMD_PARSER", None)
    payload = json.dumps(
        {"text": "hé🙂" * 300}, ensure_ascii=False, separators=(",", ":")
    ).encode()

    assert decode_complete_json(payload) == json.loads(payload)
    assert calls == []


def test_decode_complete_ascii_escape_payload_uses_yyjson_for_immutable_input(monkeypatch):
    yyjson_decoder = lambda payload: ("yyjson", payload)
    orjson_decoder = lambda payload: ("orjson", payload)
    monkeypatch.setattr(
        high_performance_parser,
        "_backend_yyjson",
        SimpleNamespace(loads=yyjson_decoder),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=orjson_decoder),
    )
    payload = b'{"data":"' + (b"\\n\\t\\\"\\\\" * 1_000) + b'"}'

    assert high_performance_parser._select_complete_decoder(payload) is yyjson_decoder
    assert (
        high_performance_parser._select_complete_decoder(bytearray(payload))
        is orjson_decoder
    )
    assert high_performance_parser._select_complete_decoder_text(
        payload.decode()
    ) is yyjson_decoder


@pytest.mark.parametrize("dense_escapes", [False, True])
def test_complete_decoders_avoid_yyjson_for_non_ascii_unicode_escapes(
    monkeypatch, dense_escapes
):
    yyjson_calls = []

    def wrong_yyjson_decoder(payload):
        yyjson_calls.append(payload)
        return {"wrong": True}

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_yyjson",
        SimpleNamespace(loads=wrong_yyjson_decoder),
    )
    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(high_performance_parser, "_GLOBAL_MSGSPEC_DECODER", None)
    monkeypatch.setattr(high_performance_parser, "_GLOBAL_SIMD_PARSER", None)
    monkeypatch.setattr(high_performance_parser, "_backend_native", None)

    escape_prefix = r"\n" * 24 if dense_escapes else "x" * 100
    payload = '{"text":"' + escape_prefix + r"\u2019" + '"}'
    expected = json.loads(payload)

    assert high_performance_parser._has_non_ascii_unicode_escape(payload)
    assert high_performance_parser._has_non_ascii_unicode_escape(payload.encode())
    assert high_performance_parser._has_non_ascii_unicode_escape(bytearray(payload.encode()))
    assert not high_performance_parser._has_non_ascii_unicode_escape(r'{"text":"\\u2019"}')
    assert not high_performance_parser._has_non_ascii_unicode_escape(r'{"text":"\u007f"}')
    assert high_performance_parser._select_complete_decoder_text(payload) is json.loads
    assert high_performance_parser._select_complete_decoder(payload.encode()) is json.loads
    assert decode_complete_json(payload) == expected
    assert decode_complete_json(payload.encode()) == expected
    assert decode_complete_json(bytearray(payload.encode())) == expected
    reusable = make_complete_json_decoder()
    assert reusable(payload) == expected
    assert reusable(payload.encode()) == expected
    assert reusable(bytearray(payload.encode())) == expected
    assert yyjson_calls == []


def test_bytearray_calibration_does_not_wrap_yyjson(monkeypatch):
    yyjson_decoder = lambda payload: payload
    monkeypatch.setattr(
        high_performance_parser,
        "_backend_yyjson",
        SimpleNamespace(loads=yyjson_decoder),
    )

    variants = high_performance_parser._candidate_variants(
        yyjson_decoder,
        bytearray(b"{}"),
    )

    assert variants == (yyjson_decoder,)


def test_decode_complete_json_preserves_large_string_input_representation(monkeypatch):
    calls = []

    def decoder(payload):
        calls.append(type(payload))
        return json.loads(payload)

    monkeypatch.setattr(
        high_performance_parser,
        "_select_complete_decoder_text",
        lambda _payload, value_type=None: decoder,
    )
    monkeypatch.setattr(high_performance_parser, "_backend_native", None)
    payload = json.dumps({"data": "x" * 20_000}, separators=(",", ":"))

    assert decode_complete_json(payload) == json.loads(payload)
    assert calls == [str]


def test_decode_complete_json_text_dispatch_does_not_encode_before_selection(monkeypatch):
    calls = []

    def decoder(payload):
        calls.append(type(payload))
        return json.loads(payload)

    monkeypatch.setattr(
        high_performance_parser,
        "_select_complete_decoder_text",
        lambda _payload, value_type=None: decoder,
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_coerce_bytes",
        lambda _payload: pytest.fail("text dispatch encoded before backend invocation"),
    )
    payload = json.dumps(
        {"rows": [{"id": index, "value": "x"} for index in range(500)]},
        separators=(",", ":"),
    )

    assert decode_complete_json(payload) == json.loads(payload)
    assert calls == [str]


def test_decode_complete_json_uses_native_text_fast_path(monkeypatch):
    calls = []

    def native_decoder(payload):
        calls.append(type(payload))
        return json.loads(payload)

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_native",
        SimpleNamespace(decode_complete=native_decoder),
    )
    payload = json.dumps({"data": "x" * 20_000}, separators=(",", ":"))

    assert decode_complete_json(payload) == json.loads(payload)
    assert calls == [str]


def test_decode_complete_json_keeps_large_ascii_root_string_native(monkeypatch):
    calls = []

    def native_decoder(payload):
        calls.append(type(payload))
        return json.loads(payload)

    monkeypatch.setattr(
        high_performance_parser,
        "_backend_native",
        SimpleNamespace(decode_complete=native_decoder),
    )
    payload = '"' + ("x" * 20_000) + '"'

    assert decode_complete_json(payload) == "x" * 20_000
    assert calls == [str]


def test_decode_complete_json_rejects_nonstandard_large_utf8_number():
    payload = json.dumps(
        {"text": "hé🙂" * 300}, ensure_ascii=False, separators=(",", ":")
    ).encode()[:-1] + b',"bad":NaN}'
    with pytest.raises(Exception):
        decode_complete_json(payload)


def test_decode_complete_json_with_value_type():
    record_type = msgspec.defstruct("TypedCompleteRecordTest", [("a", int), ("b", str)])
    result = decode_complete_json(b'{"a":1,"b":"x"}', value_type=record_type)
    assert result.a == 1
    assert result.b == "x"


def test_decode_complete_json_large_root_array():
    payload = "[" + ",".join('{"a":1,"b":"xyz"}' for _ in range(256)) + "]"
    result = decode_complete_json(payload)
    assert len(result) == 256
    assert result[0] == {"a": 1, "b": "xyz"}


def test_decode_ndjson():
    payload = b'{"a":1}\n{"b":2}\n'
    assert decode_ndjson(payload) == [{"a": 1}, {"b": 2}]


def test_decode_ndjson_ignores_blank_lines():
    payload = b'{"a":1}\n\n{"b":2}\n'
    assert decode_ndjson(payload) == [{"a": 1}, {"b": 2}]


def test_decode_ndjson_preserves_escape_heavy_records():
    value = {"text": '\n\t"' * 2_000}
    payload = (json.dumps(value, separators=(",", ":")) + "\n").encode()
    assert decode_ndjson(payload) == [value]


def test_decode_ndjson_preserves_raw_utf8_string_input():
    value = [{"text": "hé🙂"}, {"text": "café"}]
    payload = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in value)

    assert decode_ndjson(payload) == value
    assert decode_ndjson(payload.encode("utf-8")) == value


def test_decode_ndjson_string_dispatch_keeps_msgspec_on_text(monkeypatch):
    seen_types = []

    def decode_lines(payload):
        seen_types.append(type(payload))
        return [json.loads(line) for line in payload.split("\n") if line]

    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode_lines=decode_lines),
    )
    payload = '{"text":"hé🙂"}\n'

    assert decode_ndjson(payload) == [{"text": "hé🙂"}]
    assert seen_types == [str]


def test_decode_ndjson_bytearray_dispatch_keeps_original_buffer(monkeypatch):
    seen_types = []

    def decode_lines(payload):
        seen_types.append(type(payload))
        return [json.loads(line) for line in payload.split(b"\n") if line]

    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode_lines=decode_lines),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_coerce_bytes",
        lambda _payload: pytest.fail("bytearray NDJSON dispatch copied before decoding"),
    )
    payload = bytearray(b'{"text":"x"}\n')

    assert decode_ndjson(payload) == [{"text": "x"}]
    assert seen_types == [bytearray]


def test_decode_ndjson_with_record_type():
    record_type = msgspec.defstruct("TypedRecordTest", [("a", int), ("b", str)])
    payload = b'{"a":1,"b":"x"}\n{"a":2,"b":"y"}\n'
    result = decode_ndjson(payload, record_type=record_type)
    assert [record.a for record in result] == [1, 2]
    assert [record.b for record in result] == ["x", "y"]
    string_result = decode_ndjson(payload.decode(), record_type=record_type)
    assert [record.a for record in string_result] == [1, 2]
    assert [record.b for record in string_result] == ["x", "y"]


def test_make_complete_json_decoder_with_value_type():
    record_type = msgspec.defstruct("TypedFactoryRecordTest", [("a", int), ("b", str)])
    decoder = make_complete_json_decoder(value_type=record_type)
    result = decoder(b'{"a":1,"b":"x"}')
    assert result.a == 1
    assert result.b == "x"


def test_make_complete_json_decoder_reselects_mixed_workloads():
    decoder = make_complete_json_decoder()
    assert decoder(b'{"a":1}') == {"a": 1}
    assert decoder(b'[1,2,3]') == [1, 2, 3]
    assert decoder(b'{"rows":[{"a":1}]}') == {"rows": [{"a": 1}]}


def test_make_complete_json_decoder_selects_text_without_encoding(monkeypatch):
    calls = []

    def decoder(payload):
        calls.append(type(payload))
        return json.loads(payload)

    monkeypatch.setattr(
        high_performance_parser,
        "_select_complete_decoder_text",
        lambda _payload, value_type=None: decoder,
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_coerce_bytes",
        lambda _payload: pytest.fail("reusable text decoder encoded before dispatch"),
    )
    reusable = make_complete_json_decoder()
    payload = json.dumps({"rows": [{"id": index} for index in range(500)]})

    assert reusable(payload) == json.loads(payload)
    assert calls == [str]


def test_make_complete_json_decoder_caches_same_immutable_input(monkeypatch):
    calls = 0
    original = high_performance_parser._is_numeric_array_data

    def counting_probe(data):
        nonlocal calls
        calls += 1
        return original(data)

    monkeypatch.setattr(high_performance_parser, "_is_numeric_array_data", counting_probe)
    monkeypatch.setattr(high_performance_parser, "_GLOBAL_MSGSPEC_DECODER", None)
    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=json.loads),
    )
    decoder = make_complete_json_decoder()
    payload = b"[1,2,3]"

    assert decoder(payload) == [1, 2, 3]
    assert decoder(payload) == [1, 2, 3]
    assert calls == 1


def test_decode_complete_json_view():
    result = decode_complete_json_view(b'{"a":1,"b":"x"}')
    assert result["a"] == 1
    assert result["b"] == "x"


def test_make_complete_json_view_decoder():
    decoder = make_complete_json_view_decoder()
    result = decoder(b'{"a":1,"b":"x"}')
    assert result["a"] == 1
    assert result["b"] == "x"


def test_make_tuned_complete_json_decoder_tiny_hint():
    decoder = make_tuned_complete_json_decoder(payload_size_hint=64)
    assert decoder(b'{"a":1,"b":"x"}') == {"a": 1, "b": "x"}


def test_make_tuned_complete_json_decoder_size_only_keeps_scalar_dispatch(monkeypatch):
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode=lambda _payload: "msgspec"),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_backend_orjson",
        SimpleNamespace(loads=lambda _payload: "orjson"),
    )

    decoder = make_tuned_complete_json_decoder(payload_size_hint=64)

    assert decoder(b"64") == "msgspec"


def test_make_tuned_complete_json_decoder_reuses_adaptive_shape_selection():
    decoder = make_tuned_complete_json_decoder(payload_size_hint=4096)
    assert decoder(b'[1,2,3]') == [1, 2, 3]
    assert decoder(b'{"rows":[{"a":1}]}') == {"rows": [{"a": 1}]}


def test_make_tuned_complete_json_decoder_uses_sample_strategy():
    decoder = make_tuned_complete_json_decoder(
        payload_size_hint=4096,
        sample=b'{"rows":[{"a":1}]}',
    )
    assert decoder(b'{"rows":[{"a":2}]}') == {"rows": [{"a": 2}]}


def test_make_tuned_complete_json_decoder_calibrates_sample_with_size_hint(monkeypatch):
    chosen = lambda _payload: {"calibrated": True}
    calls = []

    def calibrate(payload, fallback):
        calls.append((payload, fallback))
        return chosen

    monkeypatch.setattr(
        high_performance_parser,
        "_calibrate_complete_decoder",
        calibrate,
    )
    decoder = make_tuned_complete_json_decoder(
        payload_size_hint=64,
        sample=b'{"a":1}',
    )

    assert decoder is chosen
    assert calls and calls[0][0] == b'{"a":1}'


def test_complete_calibration_rejects_permissive_candidate(monkeypatch):
    payload = b'{"data":"' + b"x" * 20_000 + b'"}'
    fallback = lambda _payload: {"fallback": True}

    def permissive(candidate_payload):
        if candidate_payload == b'{"value":NaN}':
            return {"value": float("nan")}
        return json.loads(candidate_payload)

    monkeypatch.setattr(
        high_performance_parser,
        "_complete_decoder_candidates",
        lambda _payload: (permissive,),
    )

    assert high_performance_parser._calibrate_complete_decoder(payload, fallback) is fallback


def test_tuned_complete_calibration_uses_sample_input_representation(monkeypatch):
    seen_types = []

    def strict_string_decoder(value):
        seen_types.append(type(value))
        if not isinstance(value, str) or any(
            token in value for token in ("NaN", "01", "1e400", "trailing")
        ):
            raise ValueError("invalid JSON")
        return json.loads(value)

    monkeypatch.setattr(
        high_performance_parser,
        "_complete_decoder_candidates",
        lambda _payload: (strict_string_decoder,),
    )
    monkeypatch.setattr(high_performance_parser, "_TUNED_CALIBRATION_THRESHOLD", 0)
    sample = '{"a":1}'

    decoder = make_tuned_complete_json_decoder(
        sample=sample,
        payload_size_hint=len(sample),
    )

    assert decoder('{"a":2}') == {"a": 2}
    assert seen_types and set(seen_types) == {str}


def test_make_tuned_complete_json_decoder_value_type():
    record_type = msgspec.defstruct("TypedTunedFactoryRecordTest", [("a", int), ("b", str)])
    decoder = make_tuned_complete_json_decoder(value_type=record_type, payload_size_hint=64)
    result = decoder(b'{"a":1,"b":"x"}')
    assert result.a == 1
    assert result.b == "x"


def test_make_tuned_complete_json_decoder_view_mode():
    decoder = make_tuned_complete_json_decoder(mode="view")
    result = decoder(b'{"a":1,"b":"x"}')
    assert result["a"] == 1
    assert result["b"] == "x"

def test_make_tuned_complete_json_decoder_rejects_bad_mode():
    try:
        make_tuned_complete_json_decoder(mode="unknown")
    except ValueError as exc:
        assert "mode" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("expected ValueError")


def test_make_tuned_structural_partial_decoder_binds_input_type():
    string_decoder = make_tuned_structural_partial_decoder(sample='{"a":1')
    bytes_decoder = make_tuned_structural_partial_decoder(sample=b'{"a":1')
    trailing_decoder = make_tuned_structural_partial_decoder(
        sample=b'{"text":"hel',
        trailing_strings=True,
    )

    assert string_decoder('{"a":1') == {"a": 1}
    assert bytes_decoder(b'{"a":1') == {"a": 1}
    assert trailing_decoder(b'{"text":"hel') == {"text": "hel"}


def test_make_tuned_structural_partial_decoder_rejects_bad_trailing_strings_flag():
    with pytest.raises(TypeError, match="trailing_strings"):
        make_tuned_structural_partial_decoder(trailing_strings=1)


def test_extract_complete_json_paths():
    payload = b'{"meta":{"name":"dataset"},"rows":[{"a":1}],"tail":{"count":2}}'
    result = extract_complete_json_paths(
        payload,
        ("meta", "name"),
        ("tail", "count"),
        ("rows", 0, "a"),
    )
    assert result == ("dataset", 2, 1)


def test_make_json_path_extractor_single_path():
    extractor = make_json_path_extractor(("meta", "name"))
    result = extractor(b'{"meta":{"name":"dataset"},"rows":[{"a":1}]}')
    assert result == "dataset"


def test_make_complete_json_typed_path_extractor():
    sample = {"meta": {"name": "dataset", "owner": "x"}, "tail": {"count": 2, "done": True}}
    extractor = make_complete_json_typed_path_extractor(
        ("meta", "name"),
        ("tail", "count"),
        sample=sample,
    )
    payload = b'{"meta":{"name":"dataset","owner":"x"},"tail":{"count":2,"done":true},"padding":"x"}'
    assert extractor(payload) == ("dataset", 2)
    assert extractor(payload.decode()) == ("dataset", 2)


def test_extract_complete_json_typed_paths_with_sample():
    sample = {"meta": {"name": "dataset"}, "tail": {"count": 2, "done": True}}
    payload = b'{"meta":{"name":"dataset"},"tail":{"count":2,"done":true},"padding":"x"}'
    assert extract_complete_json_typed_paths(payload, ("meta", "name"), ("tail", "done"), sample=sample) == (
        "dataset",
        True,
    )


def test_extract_complete_json_typed_paths_infers_sample():
    payload = b'{"meta":{"name":"dataset"},"tail":{"count":2,"done":true},"padding":"x"}'
    assert extract_complete_json_typed_paths(payload, ("meta", "name"), ("tail", "count")) == ("dataset", 2)


def test_make_complete_json_typed_path_extractor_rejects_non_string_paths():
    sample = {"rows": [{"a": 1}]}
    try:
        make_complete_json_typed_path_extractor(("rows", 0, "a"), sample=sample)
    except ValueError as exc:
        assert "string paths" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("expected ValueError")


def test_make_tuned_complete_json_path_extractor_small_hint():
    sample = {"meta": {"name": "dataset"}, "tail": {"count": 2, "done": True}}
    extractor = make_tuned_complete_json_path_extractor(
        ("meta", "name"),
        ("tail", "count"),
        sample=sample,
        payload_size_hint=1024,
    )
    payload = b'{"meta":{"name":"dataset"},"tail":{"count":2,"done":true},"padding":"x"}'
    assert extractor(payload) == ("dataset", 2)


def test_make_tuned_complete_json_path_extractor_large_hint():
    sample = {"meta": {"name": "dataset"}, "tail": {"count": 2, "done": True}}
    extractor = make_tuned_complete_json_path_extractor(
        ("meta", "name"),
        ("tail", "count"),
        sample=sample,
        payload_size_hint=100000,
    )
    payload = b'{"meta":{"name":"dataset"},"tail":{"count":2,"done":true},"padding":"x"}'
    assert extractor(payload) == ("dataset", 2)


def test_extract_tuned_complete_json_paths():
    sample = {"meta": {"name": "dataset"}, "tail": {"count": 2, "done": True}}
    payload = b'{"meta":{"name":"dataset"},"tail":{"count":2,"done":true},"padding":"x"}'
    assert extract_tuned_complete_json_paths(payload, ("meta", "name"), ("tail", "count"), sample=sample) == (
        "dataset",
        2,
    )


def test_make_tuned_json_path_extractor_single():
    sample = {"meta": {"name": "dataset"}, "tail": {"count": 2, "done": True}}
    extractor = make_tuned_json_path_extractor(
        ("meta", "name"),
        ("tail", "count"),
        framing="single",
        sample=sample,
        payload_size_hint=1024,
    )
    payload = b'{"meta":{"name":"dataset"},"tail":{"count":2,"done":true},"padding":"x"}'
    assert extractor(payload) == ("dataset", 2)


def test_extract_tuned_json_paths_single():
    sample = {"meta": {"name": "dataset"}, "tail": {"count": 2, "done": True}}
    payload = b'{"meta":{"name":"dataset"},"tail":{"count":2,"done":true},"padding":"x"}'
    assert extract_tuned_json_paths(payload, ("meta", "name"), ("tail", "count"), framing="single", sample=sample) == (
        "dataset",
        2,
    )


def test_extract_ndjson_paths_native():
    if importlib.util.find_spec("streaming_json_parser_native") is None:
        return
    payload = b'{"row":{"id":1,"value":"x"}}\n{"row":{"id":2,"value":"y"}}\n'
    result = extract_ndjson_paths_native(payload, ("row", "id"), ("row", "value"))
    assert result == [(1, "x"), (2, "y")]


def test_make_ndjson_path_extractor_native():
    if importlib.util.find_spec("streaming_json_parser_native") is None:
        return
    extractor = make_ndjson_path_extractor_native(("row", "id"))
    payload = b'{"row":{"id":1,"value":"x"}}\n{"row":{"id":2,"value":"y"}}\n'
    assert extractor(payload) == [1, 2]


def test_extract_ndjson_paths_native_scalar_types():
    if importlib.util.find_spec("streaming_json_parser_native") is None:
        return
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true,"note":null}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false,"note":null}}\n'
    )
    result = extract_ndjson_paths_native(
        payload,
        ("row", "id"),
        ("meta", "ok"),
        ("meta", "note"),
    )
    assert result == [(1, True, None), (2, False, None)]


def test_extract_ndjson_paths_native_accepts_bytearray():
    if importlib.util.find_spec("streaming_json_parser_native") is None:
        return
    payload = bytearray(b'{"row":{"id":1}}\n')
    assert extract_ndjson_paths_native(payload, ("row", "id")) == [1]


def test_make_ndjson_path_extractor_generic():
    extractor = make_ndjson_path_extractor(("row", "id"), ("meta", "ok"))
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    assert extractor(payload) == [(1, True), (2, False)]


def test_extract_ndjson_paths_generic():
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    assert extract_ndjson_paths(payload, ("row", "id"), ("meta", "ok")) == [(1, True), (2, False)]


def test_make_ndjson_decoder_with_record_type():
    record_type = msgspec.defstruct("TypedFactoryNdjsonRecordTest", [("a", int), ("b", str)])
    decoder = make_ndjson_decoder(record_type=record_type)
    result = decoder(b'{"a":1,"b":"x"}\n{"a":2,"b":"y"}\n')
    assert [record.a for record in result] == [1, 2]
    assert [record.b for record in result] == ["x", "y"]


def test_make_ndjson_decoder_handles_mixed_record_workloads():
    decoder = make_ndjson_decoder()
    ordinary = b'{"a":1}\n{"a":2}\n'
    escaped_value = {"text": '\n\t"' * 2_000}
    escaped = (json.dumps(escaped_value, separators=(",", ":")) + "\n").encode()
    assert decoder(ordinary) == [{"a": 1}, {"a": 2}]
    assert decoder(ordinary.decode()) == [{"a": 1}, {"a": 2}]
    assert decoder(escaped) == [escaped_value]


def test_make_ndjson_decoder_preserves_bytearray_input(monkeypatch):
    seen_types = []

    def decode_lines(payload):
        seen_types.append(type(payload))
        return [json.loads(line) for line in payload.split(b"\n") if line]

    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode_lines=decode_lines),
    )
    monkeypatch.setattr(
        high_performance_parser,
        "_coerce_bytes",
        lambda _payload: pytest.fail("reusable NDJSON decoder copied bytearray input"),
    )
    decoder = make_ndjson_decoder()

    assert decoder(bytearray(b'{"a":1}\n')) == [{"a": 1}]
    assert seen_types == [bytearray]


def test_make_tuned_ndjson_decoder_binds_direct_line_decoder(monkeypatch):
    calls = []

    def fake_decode_lines(payload):
        calls.append(payload)
        return [{"tuned": True}]

    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode_lines=fake_decode_lines),
    )
    decoder = make_tuned_ndjson_decoder(sample=b'{"a":1}\n')

    assert decoder(b'{"a":2}\n') == [{"tuned": True}]
    assert calls == [b'{"a":2}\n']


def test_make_tuned_ndjson_decoder_preserves_text_input(monkeypatch):
    seen_types = []

    def fake_decode_lines(payload):
        seen_types.append(type(payload))
        return [json.loads(line) for line in payload.split("\n") if line]

    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode_lines=fake_decode_lines),
    )
    decoder = make_tuned_ndjson_decoder(sample='{"a":1}\n')

    assert decoder('{"a":2}\n') == [{"a": 2}]
    assert seen_types == [str]


def test_make_tuned_ndjson_decoder_preserves_bytearray_input(monkeypatch):
    seen_types = []

    def fake_decode_lines(payload):
        seen_types.append(type(payload))
        return [json.loads(line) for line in payload.split(b"\n") if line]

    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode_lines=fake_decode_lines),
    )
    decoder = make_tuned_ndjson_decoder(sample=bytearray(b'{"a":1}\n'))

    assert decoder(bytearray(b'{"a":2}\n')) == [{"a": 2}]
    assert seen_types == [bytearray]


def test_make_tuned_ndjson_decoder_calibrates_sample_with_size_hint(monkeypatch):
    chosen = lambda _payload: [{"calibrated": True}]
    calls = []

    def calibrate(payload, fallback):
        calls.append((payload, fallback))
        return chosen

    monkeypatch.setattr(
        high_performance_parser,
        "_calibrate_ndjson_decoder",
        calibrate,
    )
    decoder = make_tuned_ndjson_decoder(
        sample=b'{"a":1}\n',
        payload_size_hint=64,
    )

    assert decoder is chosen
    assert calls and calls[0][0] == b'{"a":1}\n'


def test_ndjson_calibration_rejects_permissive_candidate(monkeypatch):
    payload = b'{"data":"' + b"x" * 20_000 + b'"}\n'
    fallback = lambda _payload: [{"fallback": True}]

    def permissive(candidate_payload):
        if b"NaN" in candidate_payload:
            return [{"value": float("nan")}]
        return [json.loads(line) for line in candidate_payload.split(b"\n") if line]

    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode_lines=permissive),
    )
    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(high_performance_parser, "_backend_yyjson", None)

    assert high_performance_parser._calibrate_ndjson_decoder(payload, fallback) is fallback


def test_tuned_ndjson_calibration_uses_sample_input_representation(monkeypatch):
    seen_types = []

    def reject_constant(_value):
        raise ValueError("invalid JSON constant")

    def strict_string_decoder(value):
        seen_types.append(type(value))
        if not isinstance(value, str):
            raise TypeError("expected str")
        return [
            json.loads(line, parse_constant=reject_constant)
            for line in value.split("\n")
            if line
        ]

    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(high_performance_parser, "_backend_yyjson", None)
    monkeypatch.setattr(
        high_performance_parser,
        "_GLOBAL_MSGSPEC_DECODER",
        SimpleNamespace(decode_lines=strict_string_decoder),
    )
    monkeypatch.setattr(high_performance_parser, "_TUNED_CALIBRATION_THRESHOLD", 0)
    sample = '{"a":1}\n'

    decoder = make_tuned_ndjson_decoder(
        sample=sample,
        payload_size_hint=len(sample),
    )

    assert decoder('{"a":2}\n') == [{"a": 2}]
    assert seen_types and set(seen_types) == {str}


def test_make_ndjson_typed_path_extractor():
    sample = {"meta": {"src": "x"}, "row": {"id": 1, "value": "xyz", "ok": True}}
    extractor = make_ndjson_typed_path_extractor(("row", "id"), ("row", "value"), sample=sample)
    payload = (
        b'{"meta":{"src":"x"},"row":{"id":1,"value":"x","ok":true}}\n'
        b'{"meta":{"src":"y"},"row":{"id":2,"value":"y","ok":false}}\n'
    )
    assert extractor(payload) == [(1, "x"), (2, "y")]
    assert extractor(payload.decode()) == [(1, "x"), (2, "y")]


def test_extract_ndjson_typed_paths_with_sample():
    sample = {"row": {"id": 1, "value": "x"}, "meta": {"ok": True}}
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    result = extract_ndjson_typed_paths(payload, ("row", "id"), ("meta", "ok"), sample=sample)
    assert result == [(1, True), (2, False)]


def test_extract_ndjson_typed_paths_infers_sample():
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    result = extract_ndjson_typed_paths(payload, ("row", "id"), ("meta", "ok"))
    assert result == [(1, True), (2, False)]


def test_make_ndjson_typed_path_extractor_rejects_non_string_paths():
    sample = {"row": {"id": 1, "items": ["x"]}}
    try:
        make_ndjson_typed_path_extractor(("row", "items", 0), sample=sample)
    except ValueError as exc:
        assert "string paths" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("expected ValueError")


def test_make_tuned_ndjson_path_extractor_small_hint_uses_typed_shape():
    sample = {"row": {"id": 1, "value": "x"}, "meta": {"ok": True}}
    extractor = make_tuned_ndjson_path_extractor(
        ("row", "id"),
        ("meta", "ok"),
        sample=sample,
        payload_size_hint=1024,
    )
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    assert extractor(payload) == [(1, True), (2, False)]


def test_make_tuned_ndjson_path_extractor_large_hint_falls_back_generic():
    sample = {"row": {"id": 1, "value": "x"}, "meta": {"ok": True}}
    extractor = make_tuned_ndjson_path_extractor(
        ("row", "id"),
        ("meta", "ok"),
        sample=sample,
        payload_size_hint=1000000,
    )
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    assert extractor(payload) == [(1, True), (2, False)]


def test_extract_tuned_ndjson_paths():
    sample = {"row": {"id": 1, "value": "x"}, "meta": {"ok": True}}
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    assert extract_tuned_ndjson_paths(payload, ("row", "id"), ("meta", "ok"), sample=sample) == [
        (1, True),
        (2, False),
    ]


def test_extract_tuned_ndjson_paths_infers_sample():
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    assert extract_tuned_ndjson_paths(payload, ("row", "id"), ("meta", "ok")) == [
        (1, True),
        (2, False),
    ]


def test_make_tuned_json_path_extractor_ndjson():
    sample = {"row": {"id": 1, "value": "x"}, "meta": {"ok": True}}
    extractor = make_tuned_json_path_extractor(
        ("row", "id"),
        ("meta", "ok"),
        framing="ndjson",
        sample=sample,
        payload_size_hint=1024,
    )
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    assert extractor(payload) == [(1, True), (2, False)]


def test_extract_tuned_json_paths_ndjson():
    sample = {"row": {"id": 1, "value": "x"}, "meta": {"ok": True}}
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    assert extract_tuned_json_paths(payload, ("row", "id"), ("meta", "ok"), framing="ndjson", sample=sample) == [
        (1, True),
        (2, False),
    ]


def test_extract_tuned_json_paths_ndjson_infers_sample():
    payload = (
        b'{"row":{"id":1,"value":"x"},"meta":{"ok":true}}\n'
        b'{"row":{"id":2,"value":"y"},"meta":{"ok":false}}\n'
    )
    assert extract_tuned_json_paths(payload, ("row", "id"), ("meta", "ok"), framing="ndjson") == [
        (1, True),
        (2, False),
    ]


def test_make_tuned_json_path_extractor_rejects_bad_framing():
    try:
        make_tuned_json_path_extractor(("a",), framing="bad")
    except ValueError as exc:
        assert "framing" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("expected ValueError")


def test_streaming_parser_exported_as_strict_parser():
    assert StreamingJsonParser is HighPerformanceStreamingJsonParser
    parser = StreamingJsonParser()
    result = parser.feed('{"a":')
    assert result.status is ParseStatus.PARTIAL
    assert result.value == {}
    result = parser.feed("1}")
    assert result.status is ParseStatus.COMPLETE
    assert result.value == {"a": 1}
