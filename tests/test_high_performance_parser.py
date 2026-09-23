import json
from types import SimpleNamespace

import msgspec
import pytest

from streaming_json_parser import (HighPerformanceStreamingJsonParser,
                                   ParseStatus, decode_structural_partial_json)
from streaming_json_parser.high_performance_parser import (
    _IncrementalStrictCore,
    _has_many_object_fields,
    _has_numeric_array_record,
    _may_be_complete,
    _select_complete_decoder,
    _select_complete_decoder_text,
)
import streaming_json_parser.high_performance_parser as high_performance_parser


class TestHighPerformanceStreamingJsonParser:
    def test_invalid_framing_is_rejected(self):
        try:
            HighPerformanceStreamingJsonParser(framing="unknown")
        except ValueError as exc:
            assert str(exc) == "framing must be 'single' or 'ndjson'"
        else:
            raise AssertionError("invalid framing should raise ValueError")

    def test_invalid_schema_mode_is_rejected(self):
        try:
            HighPerformanceStreamingJsonParser(schema_mode="unknown")
        except ValueError as exc:
            assert str(exc) == "schema_mode must be 'generic' or 'adaptive'"
        else:
            raise AssertionError("invalid schema_mode should raise ValueError")

    def test_invalid_partial_mode_is_rejected(self):
        try:
            HighPerformanceStreamingJsonParser(partial_mode="unknown")
        except ValueError as exc:
            assert str(exc) == (
                "partial_mode must be 'strict', 'structural', or "
                "'structural_trailing_strings'"
            )
        else:
            raise AssertionError("invalid partial mode should raise ValueError")

    def test_native_capability_probe_requires_status_configuration(self, monkeypatch):
        class IncompleteNativeParser:
            consume = object()
            consume_and_poll_result = object()
            poll_result_value = object()
            finish_result = object()
            reset = object()

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_native",
            SimpleNamespace(
                ParseResult=object,
                IncrementalJsonParser=IncompleteNativeParser,
            ),
        )
        monkeypatch.setattr(high_performance_parser, "_NATIVE_RESULT_TYPE", object)

        assert not high_performance_parser._native_strict_result_available()

    def test_structural_partial_mode_requires_single_generic_documents(self):
        try:
            HighPerformanceStreamingJsonParser(framing="ndjson", partial_mode="structural")
        except ValueError as exc:
            assert "framing='single'" in str(exc)
        else:
            raise AssertionError("structural partial mode should require single framing")

        try:
            HighPerformanceStreamingJsonParser(partial_mode="structural", value_type=dict)
        except ValueError as exc:
            assert "value_type" in str(exc)
        else:
            raise AssertionError("structural partial mode should reject typed values")

    def test_structural_partial_mode_uses_native_finisher_semantics(self):
        parser = HighPerformanceStreamingJsonParser(partial_mode="structural")
        parser.consume('{"text":"hel')
        partial = parser.poll()
        assert partial.status == ParseStatus.PARTIAL
        assert partial.value == {}

        parser.consume('lo"}')
        complete = parser.poll()
        assert complete.status == ParseStatus.COMPLETE
        assert complete.value == {"text": "hello"}

    def test_structural_trailing_strings_preserves_unfinished_string_values(self):
        parser = HighPerformanceStreamingJsonParser(
            partial_mode="structural_trailing_strings"
        )
        parser.consume('{"text":"hel')
        partial = parser.poll()
        assert partial.status == ParseStatus.PARTIAL
        assert partial.value == {"text": "hel"}

        parser.consume('lo"}')
        complete = parser.poll()
        assert complete.status == ParseStatus.COMPLETE
        assert complete.value == {"text": "hello"}

    def test_feed_supports_structural_partial_modes(self):
        parser = HighPerformanceStreamingJsonParser(partial_mode="structural")
        assert parser.feed('{"text":"hel').value == {}
        result = parser.feed('lo"}')
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"text": "hello"}

    def test_structural_modes_fall_back_without_native(self, monkeypatch):
        import streaming_json_parser.high_performance_parser as high_performance_parser

        monkeypatch.setattr(high_performance_parser, "_backend_native", None)
        parser = HighPerformanceStreamingJsonParser(partial_mode="structural")
        assert parser.feed('{"a":[1').value == {"a": [1]}
        assert parser.feed(']}').status == ParseStatus.COMPLETE

    def test_structural_partial_decoder_exposes_one_shot_native_finisher(self):
        assert decode_structural_partial_json('{"text":"hel') == {}
        assert decode_structural_partial_json('[1,2') == [1, 2]

    def test_structural_partial_decoder_omits_unfinished_root_strings(self):
        assert decode_structural_partial_json('"hel') is None
        assert decode_structural_partial_json(bytearray(b'"hel')) is None
        decoder = high_performance_parser.make_tuned_structural_partial_decoder(
            sample='"hel'
        )
        trailing_decoder = high_performance_parser.make_tuned_structural_partial_decoder(
            sample='"hel', trailing_strings=True
        )
        assert decoder('"hello') is None
        assert trailing_decoder('"hello') == 'hello'

    @pytest.mark.parametrize("payload", ["", b"", bytearray()])
    def test_structural_partial_decoder_accepts_empty_prefix(self, payload):
        assert decode_structural_partial_json(payload) is None

    @pytest.mark.parametrize(
        "payload",
        ["t", "tr", "f", "fal", "n", "nu", "-", "1e", "1."],
    )
    def test_structural_partial_decoder_omits_incomplete_root_scalars(self, payload):
        assert decode_structural_partial_json(payload) is None
        assert decode_structural_partial_json(payload.encode()) is None
        assert decode_structural_partial_json(bytearray(payload.encode())) is None

    def test_structural_partial_decoder_keeps_complete_scalars_and_rejects_bad_ones(self):
        assert decode_structural_partial_json("true") is True
        with pytest.raises(ValueError):
            decode_structural_partial_json("truX")

    @pytest.mark.parametrize(
        "payload",
        [
            "true false",
            "1 2",
            '"value" trailing',
            "{} trailing",
            "{} {}",
            "[1] trailing",
            "[1] [2]",
        ],
    )
    @pytest.mark.parametrize("representation", [str, bytes, bytearray])
    def test_structural_partial_decoder_rejects_trailing_json(
        self, payload, representation
    ):
        value = payload if representation is str else representation(payload.encode())
        with pytest.raises(ValueError, match="trailing"):
            decode_structural_partial_json(value)

    def test_tuned_structural_partial_decoder_rejects_trailing_json(self):
        decoder = high_performance_parser.make_tuned_structural_partial_decoder(
            sample=b"{}",
        )
        with pytest.raises(ValueError, match="trailing"):
            decoder(b"{} trailing")

    def test_structural_partial_decoder_skips_root_string_scan_for_containers(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            high_performance_parser,
            "_is_incomplete_root_string",
            lambda _data: pytest.fail("container prefix should not scan as root string"),
        )
        assert decode_structural_partial_json(b'{"items":[1') == {"items": [1]}

    def test_structural_partial_decoder_can_retain_trailing_root_strings(self):
        for payload in ('"hel', b'"hel', bytearray(b'"hel')):
            assert decode_structural_partial_json(
                payload,
                trailing_strings=True,
            ) == "hel"

    def test_structural_partial_decoder_rejects_unavailable_trailing_support(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            high_performance_parser,
            "_PYDANTIC_TRAILING_STRINGS",
            False,
        )
        with pytest.raises(RuntimeError, match="trailing string support"):
            decode_structural_partial_json('"hel', trailing_strings=True)

    def test_structural_text_dispatch_uses_jiter_for_large_complex_prefix(self, monkeypatch):
        calls = []

        def fake_jiter_from_json(payload, *, partial_mode):
            calls.append((payload, partial_mode))
            return {"from": "jiter"}

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_jiter",
            SimpleNamespace(from_json=fake_jiter_from_json),
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_pydantic_from_json",
            lambda *_args, **_kwargs: {"from": "pydantic"},
        )
        prefix = "[" + ",".join(str(index) for index in range(64))

        assert decode_structural_partial_json(prefix) == {"from": "jiter"}
        assert calls == [(prefix.encode("utf-8"), True)]

    def test_structural_text_dispatches_short_simple_object_to_pydantic(
        self, monkeypatch
    ):
        calls = []

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_jiter",
            SimpleNamespace(
                from_json=lambda *_args, **_kwargs: calls.append("jiter")
            ),
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_pydantic_from_json",
            lambda payload, *, allow_partial: calls.append((payload, allow_partial))
            or {"from": "pydantic"},
        )

        assert decode_structural_partial_json('{"text":"hel') == {
            "from": "pydantic"
        }
        assert calls == [('{"text":"hel', True)]

    def test_structural_text_dispatches_small_numeric_scalar_to_jiter(self, monkeypatch):
        calls = []

        def fake_jiter_from_json(payload, *, partial_mode):
            calls.append((payload, partial_mode))
            return 2

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_jiter",
            SimpleNamespace(from_json=fake_jiter_from_json),
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_pydantic_from_json",
            lambda *_args, **_kwargs: -1,
        )

        decoder = high_performance_parser.make_tuned_structural_partial_decoder(
            sample="2"
        )
        assert decoder("2") == 2
        assert calls == [(b"2", False)]

    def test_trailing_string_dispatches_root_scalar_to_pydantic(self, monkeypatch):
        calls = []

        def fake_jiter_from_json(payload, *, partial_mode):
            calls.append(("jiter", payload, partial_mode))
            return "wrong backend"

        def fake_pydantic_from_json(payload, *, allow_partial):
            calls.append(("pydantic", payload, allow_partial))
            return 2

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_jiter",
            SimpleNamespace(from_json=fake_jiter_from_json),
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_pydantic_from_json",
            fake_pydantic_from_json,
        )

        for sample in ("2", b"2", bytearray(b"2")):
            decoder = high_performance_parser.make_tuned_structural_partial_decoder(
                sample=sample,
                trailing_strings=True,
            )
            assert decoder(sample) == 2

        assert all(call[0] == "pydantic" for call in calls)
        assert not any(call[0] == "jiter" for call in calls)

    def test_structural_text_dispatches_short_numeric_array_to_jiter(self, monkeypatch):
        calls = []

        def fake_jiter_from_json(payload, *, partial_mode):
            calls.append((payload, partial_mode))
            return [1]

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_jiter",
            SimpleNamespace(from_json=fake_jiter_from_json),
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_pydantic_from_json",
            lambda *_args, **_kwargs: ["wrong backend"],
        )

        decoder = high_performance_parser.make_tuned_structural_partial_decoder(
            sample="[1,2"
        )
        assert decoder("[1,2") == [1]
        assert calls == [(b"[1,2", True)]

    def test_structural_one_shot_dispatches_short_numeric_array_to_jiter(
        self, monkeypatch
    ):
        calls = []

        def fake_jiter_from_json(payload, *, partial_mode):
            calls.append((payload, partial_mode))
            return [1]

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_jiter",
            SimpleNamespace(from_json=fake_jiter_from_json),
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_pydantic_from_json",
            lambda *_args, **_kwargs: ["wrong backend"],
        )

        assert decode_structural_partial_json("[1,2") == [1]
        assert calls == [(b"[1,2", True)]

    def test_structural_bytes_dispatches_short_simple_object_to_pydantic(
        self, monkeypatch
    ):
        calls = []

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_jiter",
            SimpleNamespace(
                from_json=lambda *_args, **_kwargs: calls.append("jiter")
            ),
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_pydantic_from_json",
            lambda payload, *, allow_partial: calls.append((payload, allow_partial))
            or {"from": "pydantic"},
        )

        assert decode_structural_partial_json(b'{"text":"hel') == {
            "from": "pydantic"
        }
        assert calls == [(b'{"text":"hel', True)]

    def test_structural_bytes_dispatches_large_plain_object_to_jiter(
        self, monkeypatch
    ):
        calls = []

        def fake_jiter_from_json(payload, *, partial_mode):
            calls.append((payload, partial_mode))
            return {"from": "jiter"}

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_jiter",
            SimpleNamespace(from_json=fake_jiter_from_json),
        )
        payload = b'{"data":"' + (b"x" * 8_192)

        assert decode_structural_partial_json(payload) == {"from": "jiter"}
        assert calls == [(payload, True)]

    def test_tuned_structural_text_decoder_binds_backend_from_sample(self, monkeypatch):
        calls = []

        def fake_jiter_from_json(payload, *, partial_mode):
            calls.append(("jiter", payload, partial_mode))
            return {"from": "jiter"}

        def fake_pydantic_from_json(payload, *, allow_partial):
            calls.append(("pydantic", payload, allow_partial))
            return {"from": "pydantic"}

        monkeypatch.setattr(
            high_performance_parser,
            "_backend_jiter",
            SimpleNamespace(from_json=fake_jiter_from_json),
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_pydantic_from_json",
            fake_pydantic_from_json,
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_STRUCTURAL_TUNED_CALIBRATION_THRESHOLD",
            4096,
        )
        sample = "[" + ",".join(str(index) for index in range(64))
        decoder = high_performance_parser.make_tuned_structural_partial_decoder(
            sample=sample
        )

        assert decoder(sample) == {"from": "jiter"}
        assert decoder(sample) == {"from": "jiter"}
        assert [call[0] for call in calls] == ["jiter", "jiter"]

    def test_tuned_structural_text_decoder_calibrates_large_sample(
        self, monkeypatch
    ):
        calibrations = []

        def fake_calibrate(sample, *, allow_partial):
            calibrations.append((sample, allow_partial))
            if len(sample) < 16:
                return None
            return lambda data: {"from": "calibrated", "data": data}

        monkeypatch.setattr(
            high_performance_parser,
            "_calibrate_structural_partial_decoder",
            fake_calibrate,
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_pydantic_from_json",
            lambda *_args, **_kwargs: {"from": "pydantic"},
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_STRUCTURAL_TUNED_CALIBRATION_THRESHOLD",
            16,
        )
        sample = "x" * 16
        decoder = high_performance_parser.make_tuned_structural_partial_decoder(
            sample=sample
        )

        assert calibrations == [(sample, True)]
        assert decoder(sample) == {"from": "calibrated", "data": sample}

    def test_structural_calibration_uses_partial_invalid_corpus(self, monkeypatch):
        if high_performance_parser._backend_jiter is None:
            pytest.skip("jiter is required for structural calibration")
        captured = {}

        def fake_select(payload, candidates, reference, invalid_inputs, fallback, **kwargs):
            del payload, reference, kwargs
            captured["invalid_inputs"] = invalid_inputs
            captured["jiter_result"] = candidates[1](sample)
            return fallback

        monkeypatch.setattr(
            high_performance_parser,
            "_select_calibrated_candidate",
            fake_select,
        )
        sample = "[" + ",".join(str(index) for index in range(2048))
        high_performance_parser.make_tuned_structural_partial_decoder(sample=sample)

        assert captured["invalid_inputs"] == (
            b'{"value":@}',
            b'{"value":{]}',
        )
        assert captured["jiter_result"][-1] == 2047

    def test_calibration_preserves_adapted_fallback_identity(self, monkeypatch):
        def strict_load(payload):
            raw = payload if isinstance(payload, bytes) else payload.encode()
            if any(token in raw for token in (b"NaN", b"01", b"trailing")):
                raise ValueError("invalid JSON")
            return json.loads(raw)

        def bytes_only_fallback(payload):
            if not isinstance(payload, bytes):
                raise TypeError("bytes required")
            return strict_load(payload)

        def alternate(payload):
            return strict_load(payload)

        clock = iter((0.0, 10.0, 10.0, 19.8))
        monkeypatch.setattr(
            high_performance_parser.time,
            "process_time",
            lambda: next(clock),
        )
        monkeypatch.setattr(high_performance_parser, "_TUNED_PROBE_SAMPLES", 1)
        monkeypatch.setattr(high_performance_parser, "_TUNED_PROBE_MAX_REPETITIONS", 1)

        decoder = high_performance_parser._select_calibrated_candidate(
            b'{"value":1}',
            (bytes_only_fallback, alternate),
            {"value": 1},
            (b'{"value":NaN}',),
            bytes_only_fallback,
            probe_payload='{"value":1}',
            min_speedup_ratio=0.95,
        )

        assert decoder('{"value":2}') == {"value": 2}
        assert decoder is not alternate

    def test_calibration_matches_bound_method_fallback_identity(self, monkeypatch):
        class Backend:
            def decode(self, payload):
                return json.loads(payload)

        backend = Backend()
        fallback = backend.decode
        alternate = lambda payload: json.loads(payload)
        clock = iter((0.0, 10.0, 10.0, 19.8))
        monkeypatch.setattr(
            high_performance_parser.time,
            "process_time",
            lambda: next(clock),
        )
        monkeypatch.setattr(high_performance_parser, "_TUNED_PROBE_SAMPLES", 1)
        monkeypatch.setattr(high_performance_parser, "_TUNED_PROBE_MAX_REPETITIONS", 1)

        decoder = high_performance_parser._select_calibrated_candidate(
            b'{"value":1}',
            (backend.decode, alternate),
            {"value": 1},
            (b'{"value":NaN}',),
            fallback,
        )

        assert decoder.__self__ is backend

    def test_structural_partial_decoder_accepts_bytes_prefixes(self):
        assert decode_structural_partial_json(b'{"text":"hel') == {}
        assert decode_structural_partial_json(bytearray(b'{"items":[1')) == {
            "items": [1]
        }
        parser = HighPerformanceStreamingJsonParser(
            partial_mode="structural_trailing_strings"
        )
        parser.consume(b'{"text":"hel')
        assert parser.poll().value == {"text": "hel"}

    def test_tuned_structural_bytearray_dispatches_by_shape(self):
        if high_performance_parser._backend_jiter is None:
            pytest.skip("jiter is required for bytearray dispatch")

        array_decoder = high_performance_parser.make_tuned_structural_partial_decoder(
            sample=bytearray(b"[1,2")
        )
        object_decoder = high_performance_parser.make_tuned_structural_partial_decoder(
            sample=bytearray(b'{"data":"' + b"x" * 128)
        )

        assert array_decoder(bytearray(b"[1,2")) == [1, 2]
        assert object_decoder(bytearray(b'{"data":"x')) == {}

    def test_structural_partial_mode_finishes_incomplete_documents_as_invalid(self):
        parser = HighPerformanceStreamingJsonParser(partial_mode="structural")
        parser.consume('{"a":1')
        result = parser.finish()
        assert result.status == ParseStatus.INVALID
        assert result.value == {"a": 1}
        assert result.error == "incomplete json document"

    def test_record_type_requires_ndjson_framing(self):
        try:
            HighPerformanceStreamingJsonParser(record_type=dict)
        except ValueError as exc:
            assert "record_type" in str(exc)
        else:
            raise AssertionError("record_type should require NDJSON framing")

    def test_value_type_requires_single_framing(self):
        try:
            HighPerformanceStreamingJsonParser(framing="ndjson", value_type=dict)
        except ValueError as exc:
            assert "value_type" in str(exc)
        else:
            raise AssertionError("value_type should require single framing")

    def test_complete_object(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume('{"a":1,"b":[1,2,3],"ok":true}')
        result = parser.poll()
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"a": 1, "b": [1, 2, 3], "ok": True}

    def test_native_complete_selector_rejects_mixed_string_documents(self, monkeypatch):
        native_decoder = lambda payload: payload
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_native",
            SimpleNamespace(decode_complete=native_decoder),
        )
        flat = b'{"data":"' + b"x" * 20_000 + b'"}'
        small_flat = b'{"data":"' + b"x" * 2_000 + b'"}'
        medium_flat = b'{"data":"' + b"x" * 3_000 + b'"}'
        mixed = b'{"data":"' + b"x" * 20_000 + b'","nested":{"ok":true}}'

        assert _select_complete_decoder(flat) is native_decoder
        assert _select_complete_decoder(small_flat) is not native_decoder
        assert _select_complete_decoder(medium_flat) is not native_decoder
        assert _select_complete_decoder(mixed) is not native_decoder

    def test_native_complete_selector_uses_ascii_root_strings_but_not_unicode(self, monkeypatch):
        native_decoder = lambda payload: payload
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_native",
            SimpleNamespace(decode_complete=native_decoder),
        )
        ascii_payload = b'"' + b"x" * 16_400 + b'"'
        unicode_payload = ('"' + ("hé🙂" * 1_400) + '"').encode()

        assert _select_complete_decoder(ascii_payload) is native_decoder
        assert _select_complete_decoder(unicode_payload) is not native_decoder

    def test_native_complete_selector_rejects_unicode_flat_string_objects(self, monkeypatch):
        native_decoder = lambda payload: payload
        orjson_decoder = lambda payload: payload
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_native",
            SimpleNamespace(decode_complete=native_decoder),
        )
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_orjson",
            SimpleNamespace(loads=orjson_decoder),
        )
        text = '{"data":"' + ("hé🙂" * 5_000) + '"}'

        assert _select_complete_decoder(text.encode()) is not native_decoder
        assert _select_complete_decoder_text(text) is not native_decoder
        assert _select_complete_decoder(text.encode()) is orjson_decoder
        assert _select_complete_decoder_text(text) is orjson_decoder

    def test_unicode_flat_probe_does_not_duplicate_small_payload(self, monkeypatch):
        orjson_decoder = lambda payload: payload
        monkeypatch.setattr(
            high_performance_parser,
            "_backend_orjson",
            SimpleNamespace(loads=orjson_decoder),
        )
        payload = ('{"data":"' + ("hé🙂" * 100) + '"}').encode()

        assert _select_complete_decoder(payload) is orjson_decoder

    def test_wide_object_probe_is_bounded(self):
        flat = b'{"data":"' + b"x" * 100_000 + b'"}'
        wide = b"{" + b",".join(
            b'"key_' + str(index).encode() + b'":' + str(index).encode()
            for index in range(8)
        ) + b"}"

        assert not _has_many_object_fields(flat)
        assert _has_many_object_fields(wide)

    def test_ndjson_numeric_array_probe_only_inspects_first_line(self):
        payload = b'{"id":1,"values":[1,2,3]}\n' + b'{"id":2}\n' * 10_000
        assert _has_numeric_array_record(payload)
        assert not _has_numeric_array_record(b'{"id":1,"values":["x"]}\n' + payload)

    def test_complete_probe_skips_boundary_scan_when_suffix_cannot_close_root(self, monkeypatch):
        calls = []

        def unexpected_scan(_payload):
            calls.append(True)
            return True

        monkeypatch.setattr(
            high_performance_parser,
            "_has_complete_root_boundary",
            unexpected_scan,
        )
        assert not _may_be_complete(b'{"data":"partial')
        assert calls == []

    def test_complete_object_with_value_type(self):
        record_type = msgspec.defstruct("TypedParserRecordTest", [("a", int), ("b", str)])
        parser = HighPerformanceStreamingJsonParser(value_type=record_type)
        parser.consume('{"a":1,"b":"x"}')
        result = parser.poll()
        assert result.status == ParseStatus.COMPLETE
        assert result.value.a == 1
        assert result.value.b == "x"

    def test_chunked_value_type_is_preserved_at_completion(self):
        record_type = msgspec.defstruct("ChunkedTypedParserRecordTest", [("a", int)])
        parser = HighPerformanceStreamingJsonParser(value_type=record_type)
        parser.consume('{"a":')
        assert parser.poll().status == ParseStatus.PARTIAL
        parser.consume("1}")
        result = parser.poll()
        assert result.status == ParseStatus.COMPLETE
        assert result.value.a == 1

    def test_value_type_mismatch_is_invalid(self):
        record_type = msgspec.defstruct("MismatchedTypedParserRecordTest", [("a", int)])
        parser = HighPerformanceStreamingJsonParser(value_type=record_type)
        parser.consume('{"a":"wrong"}')
        result = parser.poll()
        assert result.status == ParseStatus.INVALID
        assert result.error == "value does not match value_type"

    def test_chunked_value_type_mismatch_is_invalid(self):
        record_type = msgspec.defstruct("ChunkedMismatchedTypedParserRecordTest", [("a", int)])
        parser = HighPerformanceStreamingJsonParser(value_type=record_type)
        parser.consume('{"a":')
        assert parser.poll().status == ParseStatus.PARTIAL
        parser.consume('"wrong"}')
        result = parser.poll()
        assert result.status == ParseStatus.INVALID
        assert result.error == "value does not match value_type"

    def test_partial_string_delta_stream(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume('{"key":"hel')
        first = parser.poll()
        assert first.status == ParseStatus.PARTIAL
        assert first.value == {"key": "hel"}

        parser.consume('lo"}')
        second = parser.poll()
        assert second.status == ParseStatus.COMPLETE
        assert second.value == {"key": "hello"}

    def test_unicode_single_string_feed_uses_native_core(self):
        parser = HighPerformanceStreamingJsonParser()
        result = None
        for chunk in '{"data":"hé🙂"}':
            result = parser.feed(chunk)

        assert result is not None
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"data": "hé🙂"}

    def test_fast_path_does_not_decode_a_partial_key_chunk_as_root_string(self):
        parser = HighPerformanceStreamingJsonParser()
        results = [
            parser.feed(chunk)
            for chunk in ('{', '"data"', ':"YrHs', '"}')
        ]

        assert results[-1].status == ParseStatus.COMPLETE
        assert results[-1].value == {"data": "YrHs"}

    def test_feed_consumes_and_polls_one_chunk(self):
        parser = HighPerformanceStreamingJsonParser()
        first = parser.feed('{"key":"hel')
        assert first.status == ParseStatus.PARTIAL
        assert first.value == {"key": "hel"}

        second = parser.feed('lo"}')
        assert second.status == ParseStatus.COMPLETE
        assert second.value == {"key": "hello"}

    def test_split_unicode_escape_across_chunks(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume('{"text":"\\u00')
        assert parser.poll().status == ParseStatus.PARTIAL
        parser.consume('e9"}')
        result = parser.poll()
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"text": "\u00e9"}

    def test_python_strict_core_decodes_split_surrogate_pair(self):
        core = _IncrementalStrictCore()
        core.consume('{"text":"\\uD83')
        core.prepare_for_poll()
        assert core.root == {"text": ""}

        core.consume('D\\uDE00"}')
        core.finish()
        assert core.error is None
        assert core.root == {"text": "😀"}

    def test_python_strict_core_materializes_partial_root_and_array_strings(self):
        root = _IncrementalStrictCore()
        root.consume('"hel')
        root.prepare_for_poll()
        assert root.root == "hel"
        root.consume('lo"')
        root.finish()
        assert root.error is None
        assert root.root == "hello"

        array = _IncrementalStrictCore()
        array.consume('["hel')
        array.prepare_for_poll()
        assert array.root == ["hel"]
        array.consume('lo"]')
        array.finish()
        assert array.error is None
        assert array.root == ["hello"]

    def test_nested_partial_delta_stream(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume('{"a":{"b":"hel')
        first = parser.poll()
        assert first.status == ParseStatus.PARTIAL
        assert first.value == {"a": {"b": "hel"}}

        parser.consume('lo","c":1}}')
        second = parser.poll()
        assert second.status == ParseStatus.COMPLETE
        assert second.value == {"a": {"b": "hello", "c": 1}}

    @pytest.mark.parametrize(
        "payload",
        (
            '{"items":[1,{"text":"hé🙂","escaped":"quote\\\"slash\\\\"}],"ok":true}',
            '[null,false,3.14,{"nested":["a","b"]}]',
            '{"empty":{},"array":[],"number":-12.5e2}',
        ),
    )
    def test_chunked_valid_documents_match_standard_json(self, payload):
        expected = json.loads(payload)
        for input_value in (payload, payload.encode("utf-8")):
            for width in (1, 2, 5):
                parser = HighPerformanceStreamingJsonParser()
                for offset in range(0, len(input_value), width):
                    parser.feed(input_value[offset : offset + width])
                result = parser.finish()
                assert result.status == ParseStatus.COMPLETE
                assert result.value == expected

    def test_root_array_supported(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume("[1,2,3]")
        result = parser.poll()
        assert result.status == ParseStatus.COMPLETE
        assert result.value == [1, 2, 3]

    def test_large_root_array_supported_on_fast_path(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume("[" + ",".join('{"a":1,"b":"xyz"}' for _ in range(256)) + "]")
        result = parser.poll()
        assert result.status == ParseStatus.COMPLETE
        assert len(result.value) == 256
        assert result.value[0] == {"a": 1, "b": "xyz"}

    def test_invalid_number_rejected(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume('{"a":01}')
        result = parser.poll()
        assert result.status == ParseStatus.INVALID
        assert "invalid number" in (result.error or "")

    def test_invalid_prefix_rejected(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume("noise")
        result = parser.poll()
        assert result.status == ParseStatus.INVALID
        assert result.error is not None

    def test_non_json_whitespace_rejected(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume('{"a":1\u00a0}')
        result = parser.poll()
        assert result.status == ParseStatus.INVALID

    def test_bytes_input(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume(b'{"a":1}')
        result = parser.poll()
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"a": 1}

    def test_feed_uses_native_path_for_closed_one_chunk_document(self):
        parser = HighPerformanceStreamingJsonParser()
        result = parser.feed(b'{"a":1}')
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"a": 1}

    def test_feed_does_not_complete_on_nested_closing_delimiter(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.feed('{"a":1,"nested":{"ok":true}')
        result = parser.feed(',"tail":2}')
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"a": 1, "nested": {"ok": True}, "tail": 2}

    def test_python_fallback_does_not_complete_on_nested_closing_delimiter(self, monkeypatch):
        import streaming_json_parser.high_performance_parser as high_performance_parser

        monkeypatch.setattr(high_performance_parser, "_backend_native", None)
        parser = HighPerformanceStreamingJsonParser()
        assert parser.feed('{"a":1,"nested":{"ok":true}').status == ParseStatus.PARTIAL
        result = parser.feed(',"tail":2}')
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"a": 1, "nested": {"ok": True}, "tail": 2}

    def test_feed_large_nested_prefix_uses_root_boundary_not_last_delimiter(self):
        parser = HighPerformanceStreamingJsonParser()
        prefix = '{"head":"' + ("x" * 9000) + '","nested":{"ok":true}'
        assert parser.feed(prefix).status == ParseStatus.PARTIAL
        result = parser.feed(',"tail":2}')
        assert result.status == ParseStatus.COMPLETE
        assert result.value["nested"] == {"ok": True}
        assert result.value["tail"] == 2

    def test_single_document_rejects_trailing_chunks_after_completion(self):
        parser = HighPerformanceStreamingJsonParser()
        assert parser.feed('{"a":1}').status == ParseStatus.COMPLETE
        assert parser.feed(" \n\t").status == ParseStatus.COMPLETE
        result = parser.feed(" trailing")
        assert result.status == ParseStatus.INVALID
        assert result.error == "extra trailing data after complete document"

    def test_python_incremental_fallback_rejects_trailing_chunks_after_completion(self, monkeypatch):
        import streaming_json_parser.high_performance_parser as high_performance_parser

        monkeypatch.setattr(high_performance_parser, "_backend_native", None)
        parser = HighPerformanceStreamingJsonParser()
        parser.feed('{"a":')
        assert parser.feed("1}").status == ParseStatus.COMPLETE

        result = parser.feed(" trailing")
        assert result.status == ParseStatus.INVALID
        assert result.error == "extra trailing data after complete document"

    def test_json_whitespace_around_complete_document(self):
        for partial_mode in (
            "strict",
            "structural",
            "structural_trailing_strings",
        ):
            parser = HighPerformanceStreamingJsonParser(partial_mode=partial_mode)
            parser.consume(" \n{\"a\":1}\t ")
            result = parser.poll()
            assert result.status == ParseStatus.COMPLETE
            assert result.value == {"a": 1}

    def test_finish_completes_split_root_number(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume("1")
        assert parser.poll().status == ParseStatus.PARTIAL
        parser.consume("2")
        assert parser.poll().status == ParseStatus.PARTIAL
        result = parser.finish()
        assert result.status == ParseStatus.COMPLETE
        assert result.value == 12

    def test_finish_completes_split_root_literal(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume("tr")
        assert parser.poll().status == ParseStatus.PARTIAL
        parser.consume("ue")
        assert parser.poll().status == ParseStatus.PARTIAL
        result = parser.finish()
        assert result.status == ParseStatus.COMPLETE
        assert result.value is True

    def test_finish_completes_root_null_in_python_fallback(self, monkeypatch):
        import streaming_json_parser.high_performance_parser as high_performance_parser

        monkeypatch.setattr(high_performance_parser, "_backend_native", None)
        parser = HighPerformanceStreamingJsonParser()
        parser.consume("nu")
        assert parser.poll().status == ParseStatus.PARTIAL
        parser.consume("ll")
        assert parser.poll().status == ParseStatus.PARTIAL
        result = parser.finish()
        assert result.status == ParseStatus.COMPLETE
        assert result.value is None

    def test_finish_rejects_unterminated_document(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume('{"a":1')
        result = parser.finish()
        assert result.status == ParseStatus.INVALID
        assert result.error == "incomplete json document"

    def test_consume_after_finish_requires_reset(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume("1")
        assert parser.finish().status == ParseStatus.COMPLETE
        try:
            parser.consume("2")
        except RuntimeError as exc:
            assert "finished" in str(exc)
        else:
            raise AssertionError("consume after finish should raise RuntimeError")

    def test_split_utf8_byte_sequence_across_chunks(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume(b'{"text":"caf\xc3')
        first = parser.poll()
        assert first.status == ParseStatus.PARTIAL
        assert first.value == {"text": "caf"}

        parser.consume(b'\xa9"}')
        second = parser.poll()
        assert second.status == ParseStatus.COMPLETE
        assert second.value == {"text": "caf\u00e9"}

    def test_invalid_utf8_byte_is_rejected(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume(b'{"text":"bad\xff"}')
        result = parser.poll()
        assert result.status == ParseStatus.INVALID
        assert "invalid utf-8" in (result.error or "")

    def test_unescaped_control_character_in_partial_string_is_rejected(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume('{"text":"bad\n')
        result = parser.poll()
        assert result.status == ParseStatus.INVALID
        assert "control character" in (result.error or "")

    def test_copy_value(self):
        parser = HighPerformanceStreamingJsonParser()
        parser.consume('{"a":{"b":1}}')
        result = parser.poll(copy_value=True)
        assert result.status == ParseStatus.COMPLETE
        result.value["a"]["b"] = 2
        live = parser.poll()
        assert live.value == {"a": {"b": 1}}

    def test_ndjson_mode(self):
        parser = HighPerformanceStreamingJsonParser(framing="ndjson")
        parser.consume('{"a":1}\n{"b":2}\n')
        first = parser.poll()
        second = parser.poll()
        third = parser.poll()
        assert first.status == ParseStatus.COMPLETE
        assert first.value == {"a": 1}
        assert second.status == ParseStatus.COMPLETE
        assert second.value == {"b": 2}
        assert third.status == ParseStatus.EMPTY

    def test_ndjson_partial_line(self):
        parser = HighPerformanceStreamingJsonParser(framing="ndjson")
        parser.consume('{"a":1')
        first = parser.poll()
        assert first.status == ParseStatus.PARTIAL
        parser.consume('}\n')
        second = parser.poll()
        assert second.status == ParseStatus.COMPLETE
        assert second.value == {"a": 1}

    def test_ndjson_finish_accepts_final_line_without_newline(self):
        parser = HighPerformanceStreamingJsonParser(framing="ndjson")
        parser.consume('{"a":1}')
        assert parser.poll().status == ParseStatus.PARTIAL
        result = parser.finish()
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"a": 1}

    def test_typed_ndjson_finish_accepts_final_line_without_newline(self):
        record_type = msgspec.defstruct("TypedFinalNdjsonRecordTest", [("a", int)])
        parser = HighPerformanceStreamingJsonParser(framing="ndjson", record_type=record_type)
        parser.consume('{"a":1}')
        result = parser.finish()
        assert result.status == ParseStatus.COMPLETE
        assert result.value.a == 1

    def test_ndjson_record_type(self):
        record_type = msgspec.defstruct("TypedStreamRecordTest", [("a", int), ("b", str)])
        parser = HighPerformanceStreamingJsonParser(framing="ndjson", record_type=record_type)
        parser.consume('{"a":1,"b":"x"}\n{"a":2,"b":"y"}\n')
        first = parser.poll()
        second = parser.poll()
        assert first.status == ParseStatus.COMPLETE
        assert first.value.a == 1
        assert second.status == ParseStatus.COMPLETE
        assert second.value.b == "y"

    def test_ndjson_poll_many(self):
        parser = HighPerformanceStreamingJsonParser(framing="ndjson")
        parser.consume('{"a":1}\n{"a":2}\n')
        result = parser.poll_many()
        assert result == [{"a": 1}, {"a": 2}]
        assert parser.poll().status == ParseStatus.EMPTY

    def test_ndjson_generic_parser_handles_adaptive_escape_heavy_prefixes(self):
        parser = HighPerformanceStreamingJsonParser(framing="ndjson")
        value = {"text": "\n\t\"" * 400}
        payload = (json.dumps(value, separators=(",", ":")) + "\n").encode()
        parser.consume(payload)
        assert parser.poll_many() == [value]

    def test_ndjson_bytes_batch_and_mixed_chunks(self):
        parser = HighPerformanceStreamingJsonParser(framing="ndjson")
        parser.consume(b'{"a":1}\n{"a":2')
        assert parser.poll_many() == [{"a": 1}]
        parser.consume('}\n')
        assert parser.poll_many() == [{"a": 2}]

        parser.consume(b'{"a":3}')
        result = parser.finish()
        assert result.status == ParseStatus.COMPLETE
        assert result.value == {"a": 3}

    def test_ndjson_poll_many_typed(self):
        record_type = msgspec.defstruct("TypedStreamBatchRecordTest", [("a", int), ("b", str)])
        parser = HighPerformanceStreamingJsonParser(framing="ndjson", record_type=record_type)
        parser.consume('{"a":1,"b":"x"}\n{"a":2,"b":"y"}\n')
        result = parser.poll_many()
        assert [item.a for item in result] == [1, 2]
        assert [item.b for item in result] == ["x", "y"]

    def test_ndjson_poll_many_max_items(self):
        parser = HighPerformanceStreamingJsonParser(framing="ndjson")
        parser.consume('{"a":1}\n{"a":2}\n{"a":3}\n')
        first = parser.poll_many(max_items=2)
        second = parser.poll_many()
        assert first == [{"a": 1}, {"a": 2}]
        assert second == [{"a": 3}]
