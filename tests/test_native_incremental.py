import json

import pytest

native = pytest.importorskip("streaming_json_parser_native")

from streaming_json_parser import (
    HighPerformanceStreamingJsonParser,
    ParseResult,
    ParseStatus,
    decode_ndjson,
)
import streaming_json_parser.high_performance_parser as high_performance_parser


def _is_native_public_parser(parser):
    return isinstance(
        parser,
        (native.IncrementalJsonParser, native.FacadeIncrementalJsonParser),
    )


def test_native_incremental_preserves_partial_nested_values():
    parser = native.IncrementalJsonParser()
    parser.consume('{"a":{"b":"hel')
    status, value, error = parser.poll()
    assert (status, value, error) == ("partial", {"a": {"b": "hel"}}, None)

    parser.consume('lo","c":1}}')
    status, value, error = parser.poll()
    assert (status, value, error) == ("complete", {"a": {"b": "hello", "c": 1}}, None)


def test_native_complete_materializer_is_strict_and_unicode_safe():
    assert native.decode_complete(b'{"text":"caf\xc3\xa9"}') == {"text": "café"}
    assert native.decode_complete(bytearray(b'{"value":1}')) == {"value": 1}
    with pytest.raises(ValueError):
        native.decode_complete(b'{"value":NaN}')
    for number in ("1e400", "-1e400"):
        with pytest.raises(ValueError, match="non-finite"):
            native.decode_complete(f'{{"value":{number}}}'.encode())


@pytest.mark.parametrize("number", ["1e400", "-1e400"])
def test_native_strict_incremental_parser_rejects_float_overflow(number):
    parser = HighPerformanceStreamingJsonParser()
    result = parser.feed(f'{{"value":{number}}}')
    assert result.status is ParseStatus.INVALID


def test_native_ndjson_materializer_is_strict_and_unicode_safe():
    payload = b'{"text":"caf\xc3\xa9"}\n[1,2,3]\n'

    assert native.decode_ndjson(payload) == [{"text": "café"}, [1, 2, 3]]
    assert native.decode_ndjson(payload.decode()) == [{"text": "café"}, [1, 2, 3]]
    with pytest.raises(ValueError):
        native.decode_ndjson(b'{"value":NaN}\n')


def test_python_facade_uses_native_ndjson_fallback_without_python_backends(monkeypatch):
    monkeypatch.setattr(high_performance_parser, "_GLOBAL_MSGSPEC_DECODER", None)
    monkeypatch.setattr(high_performance_parser, "_backend_orjson", None)
    monkeypatch.setattr(
        high_performance_parser,
        "_NATIVE_NDJSON_DECODER",
        native.decode_ndjson,
    )

    assert decode_ndjson(b'{"a":1}\n{"a":2}\n') == [{"a": 1}, {"a": 2}]


def test_native_structural_finisher_preserves_nested_scalars():
    decoder = high_performance_parser._make_native_structural_partial_decoder(True)
    if decoder is None:
        pytest.skip("native facade backend is unavailable")

    assert decoder('{"items":[1') == {"items": [1]}
    assert decoder("1e") is None
    with pytest.raises(ValueError):
        decoder('{"items":[1}')


@pytest.mark.parametrize(
    "payload",
    [
        b"-239.26214438207614",
        b"-0.0",
        b"18446744073709551616",
        b"999999999999999999999999999999999999999999999999999999999999999999",
        b"[1, -239.26214438207614, 18446744073709551616, 1e-324]",
    ],
)
def test_native_numbers_match_python_json_semantics(payload):
    expected = json.loads(payload)

    assert native.decode_complete(payload) == expected

    parser = HighPerformanceStreamingJsonParser()
    text = payload.decode()
    for index in range(0, len(text), 2):
        parser.feed(text[index : index + 2])
    assert parser.finish().value == expected


def test_native_root_boundary_probe_handles_nesting_strings_and_trailing_data():
    assert native.is_complete_document(b'{"nested":{"ok":true}}')
    assert native.is_complete_document(b'{"text":"}]\\\""}')
    assert not native.is_complete_document(b'{"nested":{"ok":true}')
    assert not native.is_complete_document(b'{"ok":true} trailing')


def test_native_incremental_handles_split_utf8_and_bytearray():
    parser = native.IncrementalJsonParser()
    parser.consume(bytearray(b'{"text":"caf\xc3'))
    assert parser.poll()[1] == {"text": "caf"}

    parser.consume(bytearray(b'\xa9"}'))
    status, value, error = parser.poll()
    assert (status, value, error) == ("complete", {"text": "caf\u00e9"}, None)


def test_native_incremental_decodes_split_surrogate_pair():
    parser = native.IncrementalJsonParser()
    parser.consume('{"text":"\\uD83')
    assert parser.poll()[1] == {"text": ""}

    parser.consume('D\\uDE00"}')
    status, value, error = parser.poll()
    assert (status, value, error) == ("complete", {"text": "😀"}, None)


def test_native_incremental_materializes_partial_array_string():
    parser = native.IncrementalJsonParser()
    parser.consume('["hel')
    assert parser.poll()[1] == ["hel"]

    parser.consume('lo"]')
    parser.finish()
    assert parser.poll()[1] == ["hello"]


def test_native_incremental_handles_large_ascii_string_chunks():
    parser = native.IncrementalJsonParser()
    parser.configure_statuses(
        ParseStatus.EMPTY,
        ParseStatus.PARTIAL,
        ParseStatus.COMPLETE,
        ParseStatus.INVALID,
    )
    parser.configure_public_api(False, True)
    payload = '{"data":"' + ("x" * 8_192) + '"}'

    for index in range(0, len(payload), 64):
        parser.feed(payload[index : index + 64])

    result = parser.finish()
    assert result.status is ParseStatus.COMPLETE
    assert result.value == {"data": "x" * 8_192}


def test_native_incremental_structural_poll_keeps_partial_scalars():
    parser = native.IncrementalJsonParser()
    parser.consume('{"a":[1')
    status, value, error = parser.poll_structural()
    assert (status, value, error) == ("partial", {"a": [1]}, None)

    trailing = native.IncrementalJsonParser()
    trailing.consume('{"text":"hel')
    status, value, error = trailing.poll_partial()
    assert (status, value, error) == ("partial", {"text": "hel"}, None)


def test_native_incremental_materializes_partial_root_string():
    parser = native.IncrementalJsonParser()
    parser.consume('"hel')
    assert parser.poll()[1] == "hel"

    parser.consume('lo"')
    status, value, error = parser.finish()
    assert (status, value, error) == ("complete", "hello", None)


def test_native_incremental_refreshes_cached_array_growth():
    parser = native.IncrementalJsonParser()
    parser.consume('{"items":[1,')
    status, value, error = parser.poll()
    assert (status, value, error) == ("partial", {"items": [1]}, None)

    parser.consume('2,3]}')
    status, value, error = parser.poll()
    assert (status, value, error) == ("complete", {"items": [1, 2, 3]}, None)


def test_native_incremental_keeps_last_duplicate_object_key():
    parser = native.IncrementalJsonParser()
    parser.consume('{"value":1,"value":')
    assert parser.poll()[1] == {"value": 1}

    parser.consume('2}')
    status, value, error = parser.poll()
    assert (status, value, error) == ("complete", {"value": 2}, None)


def test_native_incremental_finish_finalizes_split_scalar():
    parser = native.IncrementalJsonParser()
    parser.consume("1")
    assert parser.poll()[0] == "partial"
    parser.consume("2")
    status, value, error = parser.finish()
    assert (status, value, error) == ("complete", 12, None)


def test_native_incremental_rejects_invalid_input():
    parser = native.IncrementalJsonParser()
    parser.consume('{"a":01}')
    status, value, error = parser.poll()
    assert status == "invalid"
    assert value == {}
    assert "invalid number" in error


def test_native_incremental_rejects_trailing_chunk_after_completion():
    parser = native.IncrementalJsonParser()
    parser.consume('{"a":1}')
    assert parser.poll()[0] == "complete"

    parser.consume(" trailing")
    status, value, error = parser.poll()
    assert status == "invalid"
    assert value == {"a": 1}
    assert error == "extra trailing data after complete document"


def test_native_incremental_public_result_uses_complete_chunk_fast_path():
    parser = native.IncrementalJsonParser()
    parser.configure_statuses(
        ParseStatus.EMPTY,
        ParseStatus.PARTIAL,
        ParseStatus.COMPLETE,
        ParseStatus.INVALID,
    )

    result = parser.consume_and_poll_result('{"a":1}')

    assert result.status is ParseStatus.COMPLETE
    assert result.value == {"a": 1}

    parser.consume(" trailing")
    result = parser.poll_result_value()
    assert result.status is ParseStatus.INVALID
    assert result.value == {"a": 1}
    assert result.error == "extra trailing data after complete document"


def test_native_incremental_public_result_accepts_bytearray_fast_path():
    parser = native.IncrementalJsonParser()
    parser.configure_statuses(
        ParseStatus.EMPTY,
        ParseStatus.PARTIAL,
        ParseStatus.COMPLETE,
        ParseStatus.INVALID,
    )
    parser.configure_public_api()

    result = parser.feed(bytearray(b'{"value":1}'))

    assert result.status is ParseStatus.COMPLETE
    assert result.value == {"value": 1}

    trailing = parser.feed(bytearray(b" trailing"))

    assert trailing.status is ParseStatus.INVALID
    assert trailing.value == {"value": 1}
    assert trailing.error == "extra trailing data after complete document"


def test_native_incremental_public_mode_exposes_facade_result_api():
    if not hasattr(native.IncrementalJsonParser, "configure_public_api"):
        pytest.skip("native public API mode is unavailable")

    parser = native.IncrementalJsonParser()
    parser.configure_statuses(
        ParseStatus.EMPTY,
        ParseStatus.PARTIAL,
        ParseStatus.COMPLETE,
        ParseStatus.INVALID,
    )
    parser.configure_public_api()

    partial = parser.feed('{"a":')
    assert isinstance(partial, ParseResult)
    assert partial.status is ParseStatus.PARTIAL
    assert parser.poll().status is ParseStatus.PARTIAL

    complete = parser.feed("1}")
    assert complete.status is ParseStatus.COMPLETE
    assert complete.value == {"a": 1}
    assert parser.poll_many() == [{"a": 1}]


def test_native_incremental_rejects_unpaired_surrogate():
    parser = native.IncrementalJsonParser()
    parser.consume('{"text":"\\uD800"}')
    status, value, error = parser.poll()
    assert status == "invalid"
    assert "surrogate" in error


def test_native_incremental_rejects_non_json_whitespace():
    parser = native.IncrementalJsonParser()
    parser.consume('{"a":1\u00a0}')
    status, value, error = parser.poll()
    assert status == "invalid"
    assert "trailing" in error or "expected" in error


def test_facade_selects_native_core_for_incomplete_generic_documents():
    parser = HighPerformanceStreamingJsonParser()
    parser.consume('{"key":"partial')
    if hasattr(native, "FacadeIncrementalJsonParser"):
        assert _is_native_public_parser(parser)
    result = parser.poll()
    assert result.status == ParseStatus.PARTIAL
    assert result.value == {"key": "partial"}
    assert isinstance(parser, HighPerformanceStreamingJsonParser)


def test_facade_eagerly_binds_only_compatible_strict_configuration():
    strict = HighPerformanceStreamingJsonParser()
    structural = HighPerformanceStreamingJsonParser(partial_mode="structural")

    if hasattr(native, "FacadeIncrementalJsonParser"):
        assert _is_native_public_parser(strict)
        assert _is_native_public_parser(structural)
    else:
        assert structural._native_incremental is None
    assert strict.feed('{"a":1}').value == {"a": 1}


def test_facade_feed_uses_simple_string_fast_path_without_native_backend(monkeypatch):
    import streaming_json_parser.high_performance_parser as high_performance_parser

    monkeypatch.setattr(high_performance_parser, "_backend_native", None)
    parser = HighPerformanceStreamingJsonParser()
    result = parser.feed('{"key":"partial')
    assert result.status == ParseStatus.PARTIAL
    assert result.value == {"key": "partial"}
    assert parser._pending_bytes is None
    assert not parser._pending
    assert parser._native_incremental is None
    assert parser._simple_string_state is not None


def test_facade_feed_prefers_native_core_when_available():
    parser = HighPerformanceStreamingJsonParser()
    result = parser.feed('{"key":"partial')

    assert isinstance(result, ParseResult)
    assert result.status is ParseStatus.PARTIAL
    assert result.status == ParseStatus.PARTIAL
    assert result.value == {"key": "partial"}
    if hasattr(native, "FacadeIncrementalJsonParser"):
        assert _is_native_public_parser(parser)
    assert parser._simple_string_state is None


def test_facade_feed_uses_native_core_for_medium_unicode_chunks():
    parser = HighPerformanceStreamingJsonParser()
    first = parser.feed('{"data":"' + ("hé🙂" * 10))

    assert first.status == ParseStatus.PARTIAL
    assert first.value == {"data": "hé🙂" * 10}
    if hasattr(native, "FacadeIncrementalJsonParser"):
        assert _is_native_public_parser(parser)

    result = parser.feed('"}')
    assert result.status == ParseStatus.COMPLETE
    assert result.value == {"data": "hé🙂" * 10}


def test_native_feed_result_honors_copy_value():
    parser = HighPerformanceStreamingJsonParser()
    parser.feed('{"a":{"b":')
    result = parser.feed('1}', copy_value=True)

    result.value["a"]["b"] = 2
    assert parser.poll().value == {"a": {"b": 1}}


def test_native_facade_reset_preserves_public_behavior():
    parser = HighPerformanceStreamingJsonParser()
    parser.reset()
    assert parser.poll().status == ParseStatus.EMPTY
    assert parser.feed('{"b":2}').value == {"b": 2}


def test_native_facade_complete_chunk_fast_path_preserves_state_and_trailing_data():
    parser = HighPerformanceStreamingJsonParser()
    result = parser.feed('{"nested":{"value":1}}')

    assert result.status is ParseStatus.COMPLETE
    assert parser.poll().value == {"nested": {"value": 1}}
    assert parser.finish().status is ParseStatus.COMPLETE

    trailing_parser = HighPerformanceStreamingJsonParser()
    assert trailing_parser.feed('{"nested":{"value":1}}').status is ParseStatus.COMPLETE
    trailing = trailing_parser.feed(" trailing")
    assert trailing.status is ParseStatus.INVALID
    assert trailing.error == "extra trailing data after complete document"


def test_native_facade_consume_poll_uses_complete_chunk_fast_path():
    parser = HighPerformanceStreamingJsonParser()
    parser.consume(' \n{"nested":{"value":1}}\t')

    result = parser.poll()

    assert result.status is ParseStatus.COMPLETE
    assert result.value == {"nested": {"value": 1}}

    trailing_parser = HighPerformanceStreamingJsonParser()
    trailing_parser.consume('{"nested":{"value":1}}')
    trailing_parser.consume(" trailing")
    trailing = trailing_parser.poll()
    assert trailing.status is ParseStatus.INVALID
    assert trailing.error == "extra trailing data after complete document"

    scalar_parser = HighPerformanceStreamingJsonParser()
    scalar_parser.consume("1")
    assert scalar_parser.poll().status is ParseStatus.PARTIAL


def test_native_facade_complete_root_string_fast_path_is_complete():
    parser = HighPerformanceStreamingJsonParser()

    result = parser.feed('"complete"')

    assert result.status is ParseStatus.COMPLETE
    assert result.value == "complete"


def test_native_facade_complete_hint_still_rejects_malformed_documents():
    malformed = HighPerformanceStreamingJsonParser().feed('{"a":[}')
    assert malformed.status is ParseStatus.INVALID

    trailing = HighPerformanceStreamingJsonParser().feed('{} {}')
    assert trailing.status is ParseStatus.INVALID

    overflow = HighPerformanceStreamingJsonParser().feed('{"value":1e400}')
    assert overflow.status is ParseStatus.INVALID


def test_native_facade_single_document_poll_many_matches_python_facade():
    parser = HighPerformanceStreamingJsonParser()
    parser.feed('{"b":2}')

    assert parser.poll_many() == [{"b": 2}]
    assert parser.poll_many(max_items=1) == [{"b": 2}]


def test_native_bound_finish_preserves_scalar_and_copy_semantics():
    parser = HighPerformanceStreamingJsonParser()
    assert parser.feed("1").status == ParseStatus.PARTIAL
    result = parser.finish(copy_value=True)
    assert result.status == ParseStatus.COMPLETE
    assert result.value == 1
    assert parser.poll().status == ParseStatus.COMPLETE

    copied = HighPerformanceStreamingJsonParser()
    copied.feed('{"nested":{"value":1}}')
    result = copied.finish(copy_value=True)
    result.value["nested"]["value"] = 2
    assert copied.poll().value == {"nested": {"value": 1}}


def test_facade_simple_string_fast_path_is_bounded():
    parser = HighPerformanceStreamingJsonParser()
    result = None
    for chunk in '{"key":"' + ('x' * 8_000) + '"}':
        result = parser.feed(chunk)

    assert result is not None
    assert result.status == ParseStatus.COMPLETE
    assert result.value == {"key": "x" * 8_000}


def test_facade_simple_string_fast_path_falls_back_for_escaped_values():
    parser = HighPerformanceStreamingJsonParser()
    assert parser.feed('{"key":"partial').value == {"key": "partial"}
    result = parser.feed('\\n"}')
    assert result.status == ParseStatus.COMPLETE
    assert result.value == {"key": "partial\n"}


def test_facade_structural_modes_use_native_partial_snapshots():
    parser = HighPerformanceStreamingJsonParser(partial_mode="structural")
    result = parser.feed('{"a":[1')
    assert result.status == ParseStatus.PARTIAL
    assert result.value == {"a": [1]}

    trailing = HighPerformanceStreamingJsonParser(
        partial_mode="structural_trailing_strings"
    )
    result = trailing.feed('{"text":"hel')
    assert result.status == ParseStatus.PARTIAL
    assert result.value == {"text": "hel"}
