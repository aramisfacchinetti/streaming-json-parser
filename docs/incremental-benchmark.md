# Strict Incremental Parser Benchmark

Date: 2026-09-25

This benchmark measures strict incremental parsing as UTF-8 bytes arrive in fixed-width chunks. Every chunk is fed and its partial status/value/error is inspected before the next chunk; the stream is finalized after the last chunk. All rows are in the same strict incremental semantic family.

## Provenance

- Core package: `0.2.2` (installed distribution; installed metadata `0.2.2`)
- Source revision: `9da80493873f07c024ce80780e42436abddc58e9`; working tree dirty: `False`
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
- Median native public speedup vs Python fallback: `12.64×` (Python elapsed time divided by native elapsed time; above 1 means native is faster).
- Cases where native public was faster: 43; not faster (slower or tied): 0.

## Numeric overflow edge case

`1e400` has valid JSON number syntax but exceeds finite Python float range. Its untimed behavior is recorded separately: `{"native_incremental_direct_result": {"error_type": "ValueError", "outcome": "rejected"}, "streaming_json_parser_native_public": {"error_type": "ValueError", "outcome": "rejected"}, "streaming_json_parser_python_fallback": {"decoded_value": "non-finite float", "outcome": "accepted"}}`. This input is not included in performance timings.

## Results

Times are median elapsed milliseconds per complete stream. `direct native` uses `IncrementalJsonParser.consume_and_poll_result` directly; it is an implementation reference, not a separate public recommendation.

| Payload shape | Payload bytes | Chunk bytes | Chunks | Public native ms | Direct native ms | Python fallback ms | Native/Python speedup |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `flat_string_object` | 8,203 | 1 | 8,203 | 5.198 | 8.987 | 254.958 | 49.05× |
| `flat_string_object` | 8,203 | 8 | 1,026 | 1.476 | 0.887 | 32.707 | 22.16× |
| `flat_string_object` | 8,203 | 64 | 129 | 0.209 | 0.161 | 4.016 | 19.17× |
| `flat_string_object` | 8,203 | 256 | 33 | 0.061 | 0.048 | 2.111 | 34.40× |
| `flat_string_object` | 8,203 | 1,024 | 9 | 0.031 | 0.033 | 1.381 | 44.46× |
| `flat_string_object` | 8,203 | 4,096 | 3 | 0.023 | 0.031 | 1.539 | 65.52× |
| `number_array` | 12,541 | 1 | 12,541 | 8.798 | 6.649 | 23.363 | 2.66× |
| `number_array` | 12,541 | 8 | 1,568 | 1.367 | 1.325 | 6.520 | 4.77× |
| `number_array` | 12,541 | 64 | 196 | 0.625 | 0.666 | 5.170 | 8.27× |
| `number_array` | 12,541 | 256 | 49 | 0.555 | 0.707 | 4.793 | 8.64× |
| `number_array` | 12,541 | 1,024 | 13 | 0.784 | 0.556 | 4.370 | 5.58× |
| `number_array` | 12,541 | 4,096 | 4 | 0.605 | 0.615 | 4.759 | 7.86× |
| `string_array` | 7,772 | 1 | 7,772 | 3.949 | 4.416 | 14.212 | 3.60× |
| `string_array` | 7,772 | 8 | 972 | 0.701 | 0.710 | 3.321 | 4.74× |
| `string_array` | 7,772 | 64 | 122 | 0.180 | 0.269 | 1.708 | 9.46× |
| `string_array` | 7,772 | 256 | 31 | 0.118 | 0.112 | 1.285 | 10.85× |
| `string_array` | 7,772 | 1,024 | 8 | 0.096 | 0.083 | 1.074 | 11.18× |
| `string_array` | 7,772 | 4,096 | 2 | 0.076 | 0.104 | 1.342 | 17.76× |
| `nested_records` | 8,526 | 1 | 8,526 | 5.702 | 5.575 | 15.763 | 2.76× |
| `nested_records` | 8,526 | 8 | 1,066 | 1.038 | 1.011 | 3.393 | 3.27× |
| `nested_records` | 8,526 | 64 | 134 | 0.368 | 0.367 | 1.860 | 5.05× |
| `nested_records` | 8,526 | 256 | 34 | 0.472 | 0.719 | 2.251 | 4.77× |
| `nested_records` | 8,526 | 1,024 | 9 | 0.515 | 0.483 | 1.782 | 3.46× |
| `nested_records` | 8,526 | 4,096 | 3 | 0.384 | 0.291 | 2.766 | 7.21× |
| `unicode_object` | 11,477 | 1 | 11,477 | 6.252 | 5.953 | 127.534 | 20.40× |
| `unicode_object` | 11,477 | 8 | 1,435 | 1.364 | 1.689 | 76.720 | 56.26× |
| `unicode_object` | 11,477 | 64 | 180 | 0.382 | 0.249 | 7.732 | 20.22× |
| `unicode_object` | 11,477 | 256 | 45 | 0.106 | 0.112 | 2.157 | 20.31× |
| `unicode_object` | 11,477 | 1,024 | 12 | 0.070 | 0.086 | 1.193 | 17.02× |
| `unicode_object` | 11,477 | 4,096 | 3 | 0.060 | 0.077 | 1.194 | 19.82× |
| `escape_heavy_object` | 13,115 | 1 | 13,115 | 10.915 | 13.618 | 116.149 | 10.64× |
| `escape_heavy_object` | 13,115 | 8 | 1,640 | 2.313 | 2.836 | 29.236 | 12.64× |
| `escape_heavy_object` | 13,115 | 64 | 205 | 0.461 | 0.346 | 6.432 | 13.95× |
| `escape_heavy_object` | 13,115 | 256 | 52 | 0.226 | 0.151 | 3.573 | 15.82× |
| `escape_heavy_object` | 13,115 | 1,024 | 13 | 0.096 | 0.136 | 3.303 | 34.29× |
| `escape_heavy_object` | 13,115 | 4,096 | 4 | 0.123 | 0.161 | 3.770 | 30.58× |
| `root_number` | 4 | 1 | 4 | 0.004 | 0.004 | 0.016 | 4.02× |
| `root_literal` | 4 | 1 | 4 | 0.007 | 0.004 | 0.019 | 2.75× |
| `root_string` | 2,050 | 1 | 2,050 | 1.239 | 1.532 | 14.919 | 12.04× |
| `root_string` | 2,050 | 8 | 257 | 0.165 | 0.143 | 2.349 | 14.21× |
| `root_string` | 2,050 | 64 | 33 | 0.028 | 0.023 | 0.524 | 18.97× |
| `root_string` | 2,050 | 256 | 9 | 0.012 | 0.013 | 0.558 | 45.61× |
| `root_string` | 2,050 | 1,024 | 3 | 0.015 | 0.016 | 0.360 | 23.23× |

## Reproduce

The release benchmark target generates this artifact alongside the core and community benchmark snapshots from a clean checkout with the installed core and native release distributions.

Command: `make benchmark-release-artifacts COMMUNITY_JSON_CORPUS_DIR=/private/tmp/tktech-json-benchmark/data`

This artifact describes the installed native build. The separate [same-source ABI comparison](abi3-incremental-investigation.md) is a local build investigation and does not replace these release-wheel measurements.
