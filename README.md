# Streaming JSON Parser

**Decode complete JSON documents or parse JSON as chunks arrive.** `streaming-json-parser` provides a strict incremental parser with partial values and explicit parse states, alongside complete-document decoding, NDJSON, and selective extraction for Python.

[![CI](https://github.com/aramisfacchinetti/streaming-json-parser/actions/workflows/test.yml/badge.svg)](https://github.com/aramisfacchinetti/streaming-json-parser/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/streaming-json-parser)](https://pypi.org/project/streaming-json-parser/)
[![Python versions](https://img.shields.io/pypi/pyversions/streaming-json-parser)](https://pypi.org/project/streaming-json-parser/)
[![License: MIT](https://img.shields.io/github/license/aramisfacchinetti/streaming-json-parser)](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/LICENSE)

```bash
python -m pip install streaming-json-parser
```

## Quickstart: parse while the stream is still arriving

```python
from streaming_json_parser import ParseStatus, StreamingJsonParser

parser = StreamingJsonParser()

partial = parser.feed(b'{"message":"hel')
assert partial.status is ParseStatus.PARTIAL
assert partial.value == {"message": "hel"}

complete = parser.feed(b'lo"}')
assert complete.status is ParseStatus.COMPLETE
assert complete.value == {"message": "hello"}
```

The parser resumes from its previous state on each chunk. It distinguishes `EMPTY`, `PARTIAL`, `COMPLETE`, and `INVALID` results; partial strings are available before the closing quote arrives. By default, `.value` refers to parser-owned state and may change after later chunks; pass `copy_value=True` to `feed()` when you need a retained snapshot.

![Diagram showing a JSON string split across two chunks: the first produces a PARTIAL value and the second completes it](https://raw.githubusercontent.com/aramisfacchinetti/streaming-json-parser/main/docs/assets/streaming-flow.svg)

## What it supports

- Strict incremental parsing across arbitrary input chunks, with partial values and explicit statuses.
- Complete JSON decoding, including reusable and workload-tuned decoders.
- NDJSON decoding and streaming records.
- Selective path extraction from complete JSON documents and NDJSON without always building every Python object.
- Structural partial snapshots for callers that do not need unfinished string values. This is a separate finishing mode, not the strict incremental state machine.
- Optional Rust acceleration through `streaming-json-parser-native`.

The Python implementation works without optional packages. The project is currently in beta while its public API settles.

## Performance

These charts show three separate workloads from the checked-in benchmark snapshot. Bars report total process CPU time for each repeated batch; **lower is better**. Every measured result is shown. Values are generated from [`docs/benchmark-snapshot.json`](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/benchmark-snapshot.json), and the environment, versions, workload sizes, and timing method are recorded in the [benchmark report](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/benchmark-snapshot.md).

### Complete JSON decoding

Decodes the same roughly 1 MB JSON object into a complete value. The `StreamingJsonParser — single chunk` row feeds the entire payload in one call and is included as a complete-input reference. This chart does not measure incremental parsing across arriving chunks.

![Horizontal chart of complete JSON decoding times for streaming-json-parser APIs and alternative decoders; total CPU time for 20 iterations, lower is better](https://raw.githubusercontent.com/aramisfacchinetti/streaming-json-parser/main/docs/assets/benchmarks/complete-decoding.svg)

### Complete-document selective extraction

Reads the same two object paths (`meta.name` and `tail.count`) from a 5,000-row JSON document. The full-decode baselines decode the document before accessing those paths.

![Horizontal chart of complete-document selective extraction times for streaming-json-parser APIs and alternative approaches; total CPU time for 200 iterations, lower is better](https://raw.githubusercontent.com/aramisfacchinetti/streaming-json-parser/main/docs/assets/benchmarks/selective-extraction.svg)

### NDJSON selective extraction

Reads `row.id` and `row.value` from each of 5,000 newline-delimited records. Full-decode baselines materialize each record before selecting its fields.

![Horizontal chart of NDJSON selective extraction times for streaming-json-parser APIs and alternative approaches; total CPU time for 25 iterations, lower is better](https://raw.githubusercontent.com/aramisfacchinetti/streaming-json-parser/main/docs/assets/benchmarks/ndjson-selective-extraction.svg)

### Strict incremental parsing

This separate chart measures elapsed time for complete streams delivered in exact-width UTF-8 byte chunks. It compares the public parser with the native ABI3 backend, its direct native result path, and the Python fallback; each result is inspected as chunks arrive. Its wall-clock metric is separate from the process CPU time above. See the [full results and provenance](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/incremental-benchmark.md), [JSON data](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/incremental-benchmark.json), and the [same-source PyO3 ABI comparison](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/abi3-incremental-investigation.md).

![Strict incremental parser elapsed milliseconds by byte chunk size for public native, direct native, and Python fallback paths](https://raw.githubusercontent.com/aramisfacchinetti/streaming-json-parser/main/docs/assets/benchmarks/incremental-chunk-size.svg)

These charts compare operations with the same output paths within each workload. Strict incremental parsers, structural partial finishers, and permissive JSON-repair tools have different semantics, so they are measured separately in the [API scorecard](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/current-api-scorecard.md) and [partial-strategy benchmark harness](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/scripts/benchmark_partial_strategy_matrix.py).

### Real-world Python JSON benchmark corpus

This additional chart adapts the complete-document load workload and public datasets from the community-maintained [TkTech JSON benchmark](https://github.com/TkTech/json_benchmark). It decodes six whole documents into ordinary Python values and checks every included decoder against `json.loads` before timing. Each panel has its own scale and reports input throughput; **higher is better**. This is a Python community benchmark, not a formal industry standard. The suite's SAX/event streaming cases are omitted because they do not produce the same output as this parser.

![Grouped horizontal bars compare complete-load throughput on six public JSON corpus files across streaming-json-parser APIs and common Python decoder libraries](https://raw.githubusercontent.com/aramisfacchinetti/streaming-json-parser/main/docs/assets/benchmarks/community-json-corpus-throughput.svg)

Results vary by dataset and decoder; compare the per-file values, dataset hashes, package versions, methodology, and upstream revision in the [community corpus report](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/community-json-benchmark.md) and [JSON snapshot](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/community-json-benchmark.json). For an already-complete document, use a complete-document API. Sending it through `StreamingJsonParser.feed()` also performs incremental state handling, so it is not a substitute for `decode_complete_json()`. These corpus timings are separate from the generated synthetic workloads above.

## Choose an API

This table covers the normal workflows. The [public API inventory and proposed
0.3 tiers](docs/public-api.md) classify every top-level export, including
advanced, experimental, and compatibility names.

| Workload | API | Notes |
| --- | --- | --- |
| One complete JSON document | `decode_complete_json(data)` | Returns a regular Python value. |
| Repeated complete-document decoding | `make_tuned_complete_json_decoder(...)` | Calibrates against a representative sample and payload size. |
| JSON arriving in chunks | `StreamingJsonParser` | Strict resumable parser; inspect `ParseResult.status` and `.value` after each `feed()`. |
| Newline-delimited records | `decode_ndjson(data)` or `StreamingJsonParser(framing="ndjson")` | Call `finish()` to consume a final record without a newline. |
| Incomplete prefix; unfinished strings can be omitted | `decode_structural_partial_json(prefix)` | Structural finisher; not equivalent to strict incremental parsing. |
| A few fields from JSON or NDJSON | `make_tuned_json_path_extractor(..., framing="single" or "ndjson")` | One-shot calls use `extract_complete_json_paths(...)` or `extract_ndjson_paths(...)`; reuse the factory for stable workloads. |
| Advanced typed records | `make_ndjson_decoder(record_type=...)` | Optional typed decoding through `msgspec`. |

There is no single best backend for every input. The tuned factories can benchmark compatible backends once during setup when given a representative `sample` and `payload_size_hint`.

## Common operations

### Decode a complete document

```python
from streaming_json_parser import decode_complete_json

value = decode_complete_json(b'{"name":"example","ok":true}')
```

For large read-only payloads, the advanced `decode_complete_json_view()` API can return a view backed by `simdjson`; use it only when proxy/view semantics are suitable for your application.

### Read NDJSON records

```python
from streaming_json_parser import decode_ndjson

records = decode_ndjson(b'{"id":1}\n{"id":2}\n')
```

The stateful parser also supports `framing="ndjson"` and `poll_many()` to drain complete records as they become available.

### Finish a structural partial value

Structural partial mode is useful when a caller has an incomplete prefix and needs completed objects or arrays from it. By default, it omits an unfinished trailing string; use `trailing_strings=True` or `partial_mode="structural_trailing_strings"` when that text must be retained. It may complete scalar prefixes differently from the strict parser.

```python
from streaming_json_parser import decode_structural_partial_json

value = decode_structural_partial_json('{"items":[1,2')
assert value == {"items": [1, 2]}
```

## Optional acceleration

Install the Rust extension separately when a compatible wheel is available:

```bash
python -m pip install streaming-json-parser-native
```

The native package is optional. Backend-specific packages such as `msgspec`, `orjson`, and `simdjson` are also optional; APIs fall back to the Python implementation where applicable.

The package ships PEP 561 type information for Pyright, IDEs, and other static type checkers.

## Reproduce the benchmarks

The benchmark snapshot includes the date, source revision and dirty-state flag, Python and platform details, processor and architecture, installed benchmark-package versions, native-extension availability, payload sizes, record counts, and selected paths. The methodology records its clock, warm-up, sample count, and repetitions.

To reproduce the published benchmark artifacts, install core 0.2.3 and native 0.2.2, clone the pinned community corpus, and run the guarded release target from a clean Git checkout:

```bash
python -m pip install 'streaming-json-parser[benchmark,accelerated]==0.2.3'
python -m pip install 'streaming-json-parser-native==0.2.2'
git clone https://github.com/TkTech/json_benchmark.git /tmp/tktech-json-benchmark
git -C /tmp/tktech-json-benchmark checkout 52d596b8a9bc0e00e654747298a8ec5b0d95152b
make benchmark-release-artifacts COMMUNITY_JSON_CORPUS_DIR=/tmp/tktech-json-benchmark/data
```

The release target refuses to run if the repository has tracked or untracked changes. It measures the installed core and native distributions, checks that their versions match the repository release metadata, collects the core, community, and strict incremental snapshots before writing any artifacts, and records the source commit as clean. The reports retain the module `__version__` separately from installed distribution metadata.

For local iteration, you can still regenerate only the synthetic or community snapshot without the release clean-tree guard:

```bash
make benchmark-artifacts
make benchmark-community-corpus COMMUNITY_JSON_CORPUS_DIR=/tmp/tktech-json-benchmark/data
make verify-community-benchmark-artifacts
```

To verify generated Markdown, scorecard, charts, and the current benchmark results against the committed snapshot:

```bash
make verify-release-benchmark-artifacts COMMUNITY_JSON_CORPUS_DIR=/tmp/tktech-json-benchmark/data
```

Verification checks generated files against the authoritative JSON snapshot and reruns the same benchmark slices. Timing checks allow shared machine slowdowns, but detect large per-implementation regressions. For meaningful comparisons, use the same dependency versions and a similar machine; compare the provenance fields in the snapshot.

## Development

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

See [contributing guidance](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/CONTRIBUTING.md), the [changelog](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/CHANGELOG.md), the [current API scorecard](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/current-api-scorecard.md), [open issues](https://github.com/aramisfacchinetti/streaming-json-parser/issues), and [manual GitHub settings follow-up](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/docs/github-settings-follow-up.md).

## License

MIT. See [LICENSE](https://github.com/aramisfacchinetti/streaming-json-parser/blob/main/LICENSE).
