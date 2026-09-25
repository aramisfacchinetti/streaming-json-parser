# ABI3 Strict Incremental Build Investigation

Date: 2026-09-25

This is a development-only build comparison used to isolate PyO3 ABI mode on the recommended strict incremental workload. It does not replace the [published-release benchmark](incremental-benchmark.md), which measures the native 0.2.2 ABI3 wheel against the Python fallback.

## Controlled build pair

- Source revision: `6a0deeff679c89039320d4d428e9af3b257e4775` (clean working tree).
- Native Rust source fingerprint excluding the ABI feature: `151d6c24ee95e5cfeccd1f8e24f2c3fc566ecbaa86a8ea98c1c9138558533c28`.
- Core/native package versions: `0.2.2` / `0.2.2`.
- Python/platform/processor: `3.14.0` / `macOS-27.0-arm64-arm-64bit-Mach-O` / `Apple M2 Pro`.
- Toolchain: `rustc 1.96.0 (ac68faa20 2026-05-25)`, `cargo 1.96.0 (30a34c682 2026-05-25)`, `maturin 1.14.0`.
- Benchmark library versions: `ijson=3.5.1`, `jiter=0.17.0`, `json-repair=0.63.5`, `jsonriver=1.0.0`, `msgspec=0.21.1`, `orjson=3.12.0`, `partial-json-parser=0.2.1.1.post7`, `partialjson=1.2.0`, `pydantic-core=2.49.0`, `rapidjson=1.25`, `simdjson=7.0.2`, `ujson=6.0.0`, `untruncate-json=1.1.0`.
- ABI3 wheel binary: `streaming_json_parser_native.abi3.so`; SHA-256 `7eefd7c3b86fba9bb94f91c18256fb4bc42ea6df47c85442a80c6e0bc34d0e53`; PyO3 `abi3-py310` enabled.
- CPython-specific wheel binary: `streaming_json_parser_native.cpython-314-darwin.so`; SHA-256 `6a37f01965eeed35cf7daba9618205f616699e751a5f5cf287f0a2f84f9ed633`; PyO3 `abi3-py310` omitted.
- Both wheels were built locally from the same source revision, Rust files, Cargo.lock, compiler/toolchain, Python, and machine. The PyO3 abi3-py310 feature is the only source manifest difference.
- Python fallback timing control: median `13.3%`, p90 `27.1%`, max `43.8%` (limits 15% / 30% / 50%).

## ABI3 timing difference

Values show the ABI3 build's elapsed time change relative to the CPython-specific build for the same shape and chunk size. Positive percentages mean ABI3 was slower; negative percentages mean it was faster.

| Native path | Median ABI3 change | Cases ABI3 slower | Paired cases |
| --- | ---: | ---: | ---: |
| Public `StreamingJsonParser` | +2.5% | 24 | 43 |
| Direct `consume_and_poll_result` | +4.1% | 30 | 43 |

## Median ABI3 change by payload shape

Positive values mean ABI3 was slower. These are medians across the chunk sizes available for each shape.

| Shape | Public path | Direct native path | Paired chunk sizes |
| --- | ---: | ---: | ---: |
| `escape_heavy_object` | -16.9% | -4.3% | 6 |
| `flat_string_object` | +16.5% | +11.4% | 6 |
| `nested_records` | -3.1% | +4.8% | 6 |
| `number_array` | +44.5% | +31.5% | 6 |
| `root_literal` | +21.6% | +0.4% | 1 |
| `root_number` | +35.7% | +19.9% | 1 |
| `root_string` | -5.2% | -9.4% | 5 |
| `string_array` | +27.0% | +6.8% | 6 |
| `unicode_object` | -23.9% | -21.3% | 6 |

## Paired results

Times are median elapsed milliseconds per complete stream. This table is limited to the two native strict paths; complete decoding, NDJSON extraction, structural finishers, and repair libraries are not included.

| Shape | Payload bytes | Chunk bytes | Chunks | Public ABI3 ms | Public CPython ms | Change | Direct ABI3 ms | Direct CPython ms | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `escape_heavy_object` | 13,115 | 1 | 13,115 | 10.118 | 15.896 | -36.3% | 10.194 | 14.693 | -30.6% |
| `escape_heavy_object` | 13,115 | 8 | 1,640 | 1.806 | 3.554 | -49.2% | 1.841 | 3.125 | -41.1% |
| `escape_heavy_object` | 13,115 | 64 | 205 | 0.317 | 0.329 | -3.5% | 0.324 | 0.338 | -4.1% |
| `escape_heavy_object` | 13,115 | 256 | 52 | 0.137 | 0.197 | -30.2% | 0.151 | 0.158 | -4.6% |
| `escape_heavy_object` | 13,115 | 1,024 | 13 | 0.084 | 0.082 | +2.2% | 0.086 | 0.080 | +6.9% |
| `escape_heavy_object` | 13,115 | 4,096 | 4 | 0.090 | 0.069 | +30.8% | 0.118 | 0.068 | +75.0% |
| `flat_string_object` | 8,203 | 1 | 8,203 | 4.148 | 3.532 | +17.4% | 3.724 | 3.445 | +8.1% |
| `flat_string_object` | 8,203 | 8 | 1,026 | 0.525 | 0.454 | +15.6% | 0.538 | 0.469 | +14.8% |
| `flat_string_object` | 8,203 | 64 | 129 | 0.074 | 0.074 | -0.1% | 0.076 | 0.088 | -13.7% |
| `flat_string_object` | 8,203 | 256 | 33 | 0.033 | 0.035 | -5.2% | 0.032 | 0.026 | +22.3% |
| `flat_string_object` | 8,203 | 1,024 | 9 | 0.021 | 0.018 | +18.3% | 0.017 | 0.016 | +3.5% |
| `flat_string_object` | 8,203 | 4,096 | 3 | 0.027 | 0.015 | +80.3% | 0.035 | 0.016 | +116.2% |
| `nested_records` | 8,526 | 1 | 8,526 | 5.683 | 4.335 | +31.1% | 5.137 | 4.129 | +24.4% |
| `nested_records` | 8,526 | 8 | 1,066 | 1.000 | 0.924 | +8.2% | 0.940 | 0.859 | +9.3% |
| `nested_records` | 8,526 | 64 | 134 | 0.362 | 0.353 | +2.5% | 0.328 | 0.326 | +0.5% |
| `nested_records` | 8,526 | 256 | 34 | 0.251 | 0.275 | -8.8% | 0.289 | 0.289 | +0.1% |
| `nested_records` | 8,526 | 1,024 | 9 | 0.243 | 0.268 | -9.4% | 0.237 | 0.223 | +6.2% |
| `nested_records` | 8,526 | 4,096 | 3 | 0.214 | 0.262 | -18.4% | 0.266 | 0.257 | +3.4% |
| `number_array` | 12,541 | 1 | 12,541 | 7.917 | 6.156 | +28.6% | 7.553 | 5.907 | +27.9% |
| `number_array` | 12,541 | 8 | 1,568 | 1.892 | 1.250 | +51.3% | 1.570 | 1.288 | +21.9% |
| `number_array` | 12,541 | 64 | 196 | 1.379 | 0.822 | +67.8% | 1.474 | 0.539 | +173.6% |
| `number_array` | 12,541 | 256 | 49 | 0.676 | 0.491 | +37.7% | 0.840 | 0.517 | +62.5% |
| `number_array` | 12,541 | 1,024 | 13 | 0.702 | 0.378 | +85.7% | 0.457 | 0.382 | +19.6% |
| `number_array` | 12,541 | 4,096 | 4 | 0.456 | 0.390 | +17.1% | 0.509 | 0.377 | +35.2% |
| `root_literal` | 4 | 1 | 4 | 0.004 | 0.003 | +21.6% | 0.003 | 0.003 | +0.4% |
| `root_number` | 4 | 1 | 4 | 0.005 | 0.003 | +35.7% | 0.004 | 0.003 | +19.9% |
| `root_string` | 2,050 | 1 | 2,050 | 0.939 | 1.009 | -7.0% | 0.914 | 1.010 | -9.5% |
| `root_string` | 2,050 | 8 | 257 | 0.120 | 0.126 | -5.2% | 0.119 | 0.132 | -9.4% |
| `root_string` | 2,050 | 64 | 33 | 0.019 | 0.022 | -11.9% | 0.019 | 0.022 | -14.4% |
| `root_string` | 2,050 | 256 | 9 | 0.009 | 0.009 | -2.1% | 0.008 | 0.008 | +0.7% |
| `root_string` | 2,050 | 1,024 | 3 | 0.005 | 0.005 | +1.9% | 0.005 | 0.005 | +4.9% |
| `string_array` | 7,772 | 1 | 7,772 | 4.485 | 3.467 | +29.4% | 3.744 | 3.478 | +7.7% |
| `string_array` | 7,772 | 8 | 972 | 0.696 | 0.544 | +27.8% | 0.683 | 0.556 | +22.7% |
| `string_array` | 7,772 | 64 | 122 | 0.161 | 0.142 | +12.8% | 0.160 | 0.137 | +16.6% |
| `string_array` | 7,772 | 256 | 31 | 0.118 | 0.093 | +26.2% | 0.095 | 0.092 | +4.1% |
| `string_array` | 7,772 | 1,024 | 8 | 0.099 | 0.070 | +41.1% | 0.077 | 0.076 | +1.8% |
| `string_array` | 7,772 | 4,096 | 2 | 0.083 | 0.069 | +19.9% | 0.077 | 0.073 | +6.0% |
| `unicode_object` | 11,477 | 1 | 11,477 | 5.485 | 5.690 | -3.6% | 5.533 | 5.320 | +4.0% |
| `unicode_object` | 11,477 | 8 | 1,435 | 0.754 | 0.993 | -24.1% | 0.785 | 0.819 | -4.2% |
| `unicode_object` | 11,477 | 64 | 180 | 0.131 | 0.174 | -24.7% | 0.156 | 0.157 | -0.6% |
| `unicode_object` | 11,477 | 256 | 45 | 0.067 | 0.081 | -18.1% | 0.064 | 0.131 | -50.7% |
| `unicode_object` | 11,477 | 1,024 | 12 | 0.048 | 0.063 | -23.7% | 0.046 | 0.074 | -38.4% |
| `unicode_object` | 11,477 | 4,096 | 3 | 0.040 | 0.077 | -47.8% | 0.042 | 0.069 | -39.3% |

## Interpretation limits

This comparison isolates ABI mode for one Python version, platform, compiler, and workload matrix. Use the release-wheel benchmark for current user-facing performance. A material change should be investigated with profiling before changing native packaging or parser code.
