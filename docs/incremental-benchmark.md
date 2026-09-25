# Strict Incremental Parser Benchmark

Date: 2026-09-25

This benchmark measures strict incremental parsing as UTF-8 bytes arrive in fixed-width chunks. Every chunk is fed and its partial status/value/error is inspected before the next chunk; the stream is finalized after the last chunk. All rows are in the same strict incremental semantic family.

## Provenance

- Core package: `0.2.3` (installed distribution; installed metadata `0.2.3`)
- Source revision: `55f38cd26ab10d73c015381980be60dcc7ae1f66`; working tree dirty: `False`
- Native package: `0.2.2`; build variant: `abi3`; ABI3 binary: `True`
- Native module file: `streaming_json_parser_native.abi3.so`; SHA-256: `ae4a201a96c9bb5adb4f156471abae7cd5397ff796be1958864ef607401c357d`
- Python/platform: `3.14.0` / `macOS-27.0-arm64-arm-64bit-Mach-O`; processor: `Apple M2 Pro`
- Rust compiler: `rustc 1.96.0 (ac68faa20 2026-05-25)`
- Benchmark toolchain libraries: `ijson=3.5.1`, `jiter=0.17.0`, `json-repair=0.63.5`, `jsonriver=1.0.0`, `msgspec=0.21.1`, `orjson=3.12.0`, `partial-json-parser=0.2.1.1.post7`, `partialjson=1.2.0`, `pydantic-core=2.49.0`, `rapidjson=1.25`, `simdjson=7.0.2`, `ujson=6.0.0`, `untruncate-json=1.1.0`
- Native source fingerprint (excluding only the PyO3 ABI feature): `151d6c24ee95e5cfeccd1f8e24f2c3fc566ecbaa86a8ea98c1c9138558533c28`

## Methodology

- Clock: `time.perf_counter`; median per-stream elapsed time across 7 measured batches.
- Timed lifecycle: parser construction, every delta-chunk feed/consume-and-poll call, inspection of each partial status/value/error, and finalization; payload construction and reference JSON decoding are outside timing.
- Chunking: UTF-8 serialized payloads are sliced as bytes at exact requested byte widths; cases with fewer than two chunks are omitted.
- Correctness: all three adapters must produce the same complete Python value and reject NaN, leading-zero numbers, trailing commas, and trailing data.
- Scope: strict incremental only; complete decoding, cumulative-prefix reparsing, structural finishers, and permissive repair libraries are excluded.
- Each timing is per complete stream, including parser construction and finalization; lower is better.

## Summary

- Paired shape/chunk cases: 43.
- Median native public speedup vs Python fallback: `12.03×` (Python elapsed time divided by native elapsed time; above 1 means native is faster).
- Cases where native public was faster: 43; not faster (slower or tied): 0.

## Numeric overflow edge case

`1e400` has valid JSON number syntax but exceeds finite Python float range. Its untimed behavior is recorded separately: `{"native_incremental_direct_result": {"error_type": "ValueError", "outcome": "rejected"}, "streaming_json_parser_native_public": {"error_type": "ValueError", "outcome": "rejected"}, "streaming_json_parser_python_fallback": {"error_type": "ValueError", "outcome": "rejected"}}`. This input is not included in performance timings.

## Results

Times are median elapsed milliseconds per complete stream. `direct native` uses `IncrementalJsonParser.consume_and_poll_result` directly; it is an implementation reference, not a separate public recommendation.

| Payload shape | Payload bytes | Chunk bytes | Chunks | Public native ms | Direct native ms | Python fallback ms | Native/Python speedup |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `flat_string_object` | 8,203 | 1 | 8,203 | 4.176 | 4.449 | 169.024 | 40.48× |
| `flat_string_object` | 8,203 | 8 | 1,026 | 0.610 | 0.611 | 27.448 | 45.01× |
| `flat_string_object` | 8,203 | 64 | 129 | 0.138 | 0.143 | 4.020 | 29.10× |
| `flat_string_object` | 8,203 | 256 | 33 | 0.042 | 0.038 | 1.840 | 43.52× |
| `flat_string_object` | 8,203 | 1,024 | 9 | 0.026 | 0.023 | 1.440 | 56.39× |
| `flat_string_object` | 8,203 | 4,096 | 3 | 0.071 | 0.075 | 1.760 | 24.69× |
| `number_array` | 12,541 | 1 | 12,541 | 8.455 | 7.475 | 27.790 | 3.29× |
| `number_array` | 12,541 | 8 | 1,568 | 1.923 | 2.010 | 11.743 | 6.11× |
| `number_array` | 12,541 | 64 | 196 | 1.126 | 1.038 | 9.236 | 8.20× |
| `number_array` | 12,541 | 256 | 49 | 0.854 | 1.264 | 7.708 | 9.02× |
| `number_array` | 12,541 | 1,024 | 13 | 0.570 | 0.550 | 5.161 | 9.05× |
| `number_array` | 12,541 | 4,096 | 4 | 1.326 | 1.444 | 5.252 | 3.96× |
| `string_array` | 7,772 | 1 | 7,772 | 5.466 | 5.995 | 19.430 | 3.55× |
| `string_array` | 7,772 | 8 | 972 | 0.865 | 0.938 | 5.061 | 5.85× |
| `string_array` | 7,772 | 64 | 122 | 0.695 | 0.299 | 1.280 | 1.84× |
| `string_array` | 7,772 | 256 | 31 | 0.095 | 0.149 | 1.445 | 15.13× |
| `string_array` | 7,772 | 1,024 | 8 | 0.075 | 0.099 | 1.671 | 22.34× |
| `string_array` | 7,772 | 4,096 | 2 | 0.167 | 0.194 | 2.049 | 12.30× |
| `nested_records` | 8,526 | 1 | 8,526 | 6.299 | 6.709 | 20.338 | 3.23× |
| `nested_records` | 8,526 | 8 | 1,066 | 1.654 | 1.491 | 5.553 | 3.36× |
| `nested_records` | 8,526 | 64 | 134 | 0.701 | 0.443 | 2.304 | 3.29× |
| `nested_records` | 8,526 | 256 | 34 | 0.688 | 0.443 | 3.482 | 5.06× |
| `nested_records` | 8,526 | 1,024 | 9 | 0.453 | 0.549 | 2.814 | 6.21× |
| `nested_records` | 8,526 | 4,096 | 3 | 0.573 | 0.534 | 5.057 | 8.82× |
| `unicode_object` | 11,477 | 1 | 11,477 | 6.988 | 8.552 | 163.052 | 23.33× |
| `unicode_object` | 11,477 | 8 | 1,435 | 1.277 | 1.132 | 45.462 | 35.59× |
| `unicode_object` | 11,477 | 64 | 180 | 0.215 | 0.208 | 8.788 | 40.79× |
| `unicode_object` | 11,477 | 256 | 45 | 0.115 | 0.140 | 2.442 | 21.15× |
| `unicode_object` | 11,477 | 1,024 | 12 | 0.079 | 0.103 | 1.975 | 24.96× |
| `unicode_object` | 11,477 | 4,096 | 3 | 0.098 | 0.102 | 0.795 | 8.10× |
| `escape_heavy_object` | 13,115 | 1 | 13,115 | 21.472 | 23.933 | 258.332 | 12.03× |
| `escape_heavy_object` | 13,115 | 8 | 1,640 | 4.605 | 5.110 | 63.637 | 13.82× |
| `escape_heavy_object` | 13,115 | 64 | 205 | 2.730 | 1.685 | 25.840 | 9.47× |
| `escape_heavy_object` | 13,115 | 256 | 52 | 0.422 | 0.718 | 12.874 | 30.51× |
| `escape_heavy_object` | 13,115 | 1,024 | 13 | 0.233 | 0.168 | 6.795 | 29.20× |
| `escape_heavy_object` | 13,115 | 4,096 | 4 | 0.186 | 0.190 | 7.737 | 41.64× |
| `root_number` | 4 | 1 | 4 | 0.009 | 0.006 | 0.024 | 2.67× |
| `root_literal` | 4 | 1 | 4 | 0.007 | 0.007 | 0.034 | 4.72× |
| `root_string` | 2,050 | 1 | 2,050 | 2.400 | 2.450 | 24.295 | 10.12× |
| `root_string` | 2,050 | 8 | 257 | 0.549 | 0.515 | 4.550 | 8.29× |
| `root_string` | 2,050 | 64 | 33 | 0.073 | 0.060 | 1.437 | 19.64× |
| `root_string` | 2,050 | 256 | 9 | 0.031 | 0.024 | 1.557 | 50.29× |
| `root_string` | 2,050 | 1,024 | 3 | 0.016 | 0.013 | 0.648 | 39.43× |

## Reproduce

The release benchmark target generates this artifact alongside the core and community benchmark snapshots from a clean checkout with the installed core and native release distributions.

Command: `make benchmark-release-artifacts COMMUNITY_JSON_CORPUS_DIR=/private/tmp/tktech-json-benchmark/data`

This artifact describes the installed native build. The separate [same-source ABI comparison](abi3-incremental-investigation.md) is a local build investigation and does not replace these release-wheel measurements.
