# Streaming JSON Parser

High-performance JSON decoding and true incremental parsing for Python streams.
The package chooses an appropriate backend for complete documents, NDJSON, typed
decoding, selective extraction, and partial input. The strict incremental API
owns the semantics that ordinary JSON decoders do not provide.

The current release is `0.2.0` and is in beta while the public API settles.

## Install

```bash
python -m pip install streaming-json-parser
```

Optional backend groups:

```bash
python -m pip install 'streaming-json-parser[accelerated]'
python -m pip install 'streaming-json-parser[partial]'
```

The Rust extension is optional. When a compatible wheel is available, install
it separately:

```bash
python -m pip install streaming-json-parser-native
```

The Python implementation remains functional without optional dependencies.

## Choose An API

| Workload | API |
| --- | --- |
| Complete JSON document | `decode_complete_json` |
| Complete document with zero-copy view semantics | `decode_complete_json_view` |
| Newline-delimited JSON | `decode_ndjson` or `StreamingJsonParser(framing="ndjson")` |
| True incremental parsing | `StreamingJsonParser` |
| Structural partial snapshots | `decode_structural_partial_json` |
| Repeated selective extraction | `make_tuned_json_path_extractor` |

There is no universal fastest decoder for every payload. The tuned factories
calibrate compatible backends for a representative workload; the benchmark
[scorecard](docs/current-api-scorecard.md) records the current evidence.

## Complete Documents

```python
from streaming_json_parser import decode_complete_json

value = decode_complete_json(b'{"name":"example","ok":true}')
assert value == {"name": "example", "ok": True}
```

For a stable repeated workload, bind a decoder once:

```python
from streaming_json_parser import make_tuned_complete_json_decoder

decode = make_tuned_complete_json_decoder(
    sample=b'{"id":1,"name":"example"}',
    payload_size_hint=1024,
)
value = decode(b'{"id":2,"name":"another"}')
```

## Incremental Streams

`StreamingJsonParser` preserves state across chunks and reports
one of `EMPTY`, `PARTIAL`, `COMPLETE`, or `INVALID`.

```python
from streaming_json_parser import StreamingJsonParser, ParseStatus

parser = StreamingJsonParser()
result = parser.feed(b'{"message":"hel')
assert result.status is ParseStatus.PARTIAL
assert result.value == {"message": "hel"}

result = parser.feed(b'lo"}')
assert result.status is ParseStatus.COMPLETE
assert result.value == {"message": "hello"}
```

Call `finish()` when the input source ends. This is required for ambiguous root
scalars and for an NDJSON stream whose final record has no trailing newline.

```python
parser = StreamingJsonParser()
parser.consume("12")
result = parser.finish()
assert result.value == 12
```

For NDJSON, use `poll_many()` to drain complete records:

```python
parser = StreamingJsonParser(framing="ndjson")
parser.consume(b'{"id":1}\n{"id":2}\n')
assert parser.poll_many() == [{"id": 1}, {"id": 2}]
```

## Partial JSON

Structural mode is useful when an unfinished string value does not need to be
returned. It is a cumulative finisher, not a resumable strict state machine:

```python
from streaming_json_parser import decode_structural_partial_json

assert decode_structural_partial_json('{"items":[1,2') == {"items": [1, 2]}
assert decode_structural_partial_json('{"text":"hel') == {}
assert decode_structural_partial_json('{"text":"hel', trailing_strings=True) == {
    "text": "hel"
}
```

Use `StreamingJsonParser(partial_mode="structural")` when the
prefix arrives as many small chunks and a stateful parser is preferable.

## Selective Extraction

```python
from streaming_json_parser import make_tuned_json_path_extractor

extract = make_tuned_json_path_extractor(
    ("meta", "name"),
    ("meta", "count"),
    framing="single",
    sample={"meta": {"name": "example", "count": 1}},
    payload_size_hint=1024,
)
assert extract(b'{"meta":{"name":"example","count":2}}') == ("example", 2)
```

## Development

```bash
python -m pip install -e '.[test]'
pytest
```

Build and inspect release artifacts locally:

```bash
python -m build
python -m twine check dist/*
```

Benchmark artifacts are optional and can be regenerated with:

```bash
make benchmark-artifacts
make verify-benchmark-artifacts
```

The package supports Python 3.10 and later. It is distributed under the MIT
license.
