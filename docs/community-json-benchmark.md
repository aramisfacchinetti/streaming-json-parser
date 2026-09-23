# Community JSON Benchmark Snapshot

Date: 2026-09-23

This run adapts the complete-document load workload and public data files from [TkTech/json_benchmark](https://github.com/TkTech/json_benchmark). It is a community-maintained Python parser benchmark, not a formal industry standard. The upstream project also has SAX/event streaming cases; those are omitted because they do not materialize the same result as this library.

## Provenance

- Upstream commit: `52d596b8a9bc0e00e654747298a8ec5b0d95152b`
- Upstream benchmark definition: `tests/test_json.py::test_full_document_read`
- Package version and source revision: `0.2.0` / `6b11966cc4f10c07ed2ac555da7b298aba2d3151`
- Working tree dirty: `True`
- Python and platform: `3.14.0` / `macOS-27.0-arm64-arm-64bit-Mach-O`
- Processor: `Apple M2 Pro` (arm64)
- Native extension: `0.1.0`
- Benchmark library versions: `json (stdlib)=3.14.0`, `msgspec=0.21.1`, `orjson=3.12.0`, `rapidjson=1.23`, `simdjson=7.0.2`, `ujson=5.12.1`, `yyjson=4.0.6`

## Methodology

- Operation: decode the complete document into an ordinary Python JSON value.
- Input: UTF-8 data file decoded to Python str before timing; file I/O and UTF-8 decoding are outside timing.
- Timing: `time.process_time`; median per-operation process CPU time across 7 measured batches; 1 warm-up batch(s).
- Repetitions: max(1, floor(4 MiB / UTF-8 file byte length)), capped at 50; same count for every compatible decoder on a file.
- Fairness check: each candidate output was compared recursively with Python json.loads; booleans, integers, and floats must retain their exact Python value types, and incompatible candidates are excluded for that file.
- Rate: UTF-8 file bytes divided by median per-operation CPU time; chart uses MiB/s, higher is better.
- Scope: This adapts only the upstream complete-load workload. Its SAX/event streaming cases are not comparable because this library materializes Python values.

The chart uses one scale per corpus file. Use the number labels and the exact values below for cross-file comparisons.

## Results

### `data/canada.json` — 2,251,051 bytes

SHA-256: `f83b3b354030d5dd58740c68ac4fecef64cb730a0d12a90362a7f23077f50d78`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `yyjson_loads` | 6.011 | 357.1 |
| 2 | `reusable_complete_decoder` | 6.316 | 339.9 |
| 3 | `orjson_loads` | 6.519 | 329.3 |
| 4 | `decode_complete_json` | 6.949 | 308.9 |
| 5 | `msgspec_decode` | 7.386 | 290.7 |
| 6 | `simdjson_loads` | 7.628 | 281.4 |
| 7 | `ujson_loads` | 11.172 | 192.2 |
| 8 | `rapidjson_loads` | 24.014 | 89.4 |
| 9 | `json_loads` | 26.489 | 81.0 |
| 10 | `streaming_parser_one_buffer` | 47.605 | 45.1 |

### `data/citm_catalog.json` — 1,727,204 bytes

SHA-256: `a73e7a883f6ea8de113dff59702975e60119b4b58d451d518a929f31c92e2059`. 2 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `reusable_complete_decoder` | 2.444 | 673.8 |
| 2 | `decode_complete_json` | 2.450 | 672.3 |
| 3 | `orjson_loads` | 2.524 | 652.6 |
| 4 | `msgspec_decode` | 2.857 | 576.5 |
| 5 | `ujson_loads` | 3.706 | 444.5 |
| 6 | `simdjson_loads` | 3.836 | 429.3 |
| 7 | `rapidjson_loads` | 4.956 | 332.4 |
| 8 | `json_loads` | 6.044 | 272.6 |
| 9 | `streaming_parser_one_buffer` | 11.403 | 144.4 |

### `data/twitter.json` — 631,514 bytes

SHA-256: `a08b769f32b95f426cbc3abafcec65c1a19d3eb544d4ddf320eae142c99efc5d`. 6 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `decode_complete_json` | 0.907 | 664.0 |
| 2 | `reusable_complete_decoder` | 0.927 | 649.5 |
| 3 | `msgspec_decode` | 1.173 | 513.6 |
| 4 | `orjson_loads` | 1.325 | 454.7 |
| 5 | `ujson_loads` | 1.592 | 378.3 |
| 6 | `simdjson_loads` | 1.848 | 325.8 |
| 7 | `json_loads` | 2.452 | 245.6 |
| 8 | `rapidjson_loads` | 2.594 | 232.2 |
| 9 | `streaming_parser_one_buffer` | 4.607 | 130.7 |

### `data/gsoc-2018.json` — 3,327,831 bytes

SHA-256: `72f1ef4898d88049da856c2ab8f4ec3e2c968ce209b2bbfd16cef842eb2e185f`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `reusable_complete_decoder` | 3.397 | 934.3 |
| 2 | `decode_complete_json` | 4.192 | 757.1 |
| 3 | `msgspec_decode` | 4.223 | 751.5 |
| 4 | `orjson_loads` | 4.285 | 740.6 |
| 5 | `simdjson_loads` | 5.139 | 617.6 |
| 6 | `ujson_loads` | 5.352 | 593.0 |
| 7 | `json_loads` | 7.132 | 445.0 |
| 8 | `streaming_parser_one_buffer` | 9.068 | 350.0 |
| 9 | `rapidjson_loads` | 9.220 | 344.2 |

### `data/poet.json` — 3,512,883 bytes

SHA-256: `2c2689a3b5df460f02e4dee2a36ac32cc27c43e2964fba7965eba3469bf617ec`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `orjson_loads` | 4.434 | 755.6 |
| 2 | `ujson_loads` | 4.777 | 701.3 |
| 3 | `reusable_complete_decoder` | 5.549 | 603.7 |
| 4 | `msgspec_decode` | 5.910 | 566.9 |
| 5 | `decode_complete_json` | 6.542 | 512.1 |
| 6 | `json_loads` | 6.970 | 480.7 |
| 7 | `simdjson_loads` | 7.238 | 462.9 |
| 8 | `streaming_parser_one_buffer` | 11.043 | 303.4 |
| 9 | `rapidjson_loads` | 11.506 | 291.2 |

### `data/fgo.json` — 48,765,043 bytes

SHA-256: `4d0153f122aa4f049888dce8162d38b677e0127e2be90ae3afd998813f44a738`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `decode_complete_json` | 204.467 | 227.4 |
| 2 | `reusable_complete_decoder` | 213.978 | 217.3 |
| 3 | `orjson_loads` | 238.129 | 195.3 |
| 4 | `msgspec_decode` | 248.464 | 187.2 |
| 5 | `ujson_loads` | 337.858 | 137.6 |
| 6 | `simdjson_loads` | 424.672 | 109.5 |
| 7 | `rapidjson_loads` | 437.798 | 106.2 |
| 8 | `json_loads` | 519.402 | 89.5 |
| 9 | `streaming_parser_one_buffer` | 873.624 | 53.2 |

## Reproduce

```bash
python -m pip install -e '.[accelerated]'
python -m pip install 'streaming-json-parser-native==0.2.0'
git clone --depth 1 https://github.com/TkTech/json_benchmark.git /tmp/json_benchmark
make benchmark-community-corpus COMMUNITY_JSON_CORPUS_DIR=/tmp/json_benchmark/data
```

The input files are not copied into this repository. The JSON snapshot records the upstream revision, file hashes, and exact tool versions for this run.

## Excluded incompatible results

- `citm_catalog.json` / `yyjson_loads`: decoded value differs from Python json.loads
- `fgo.json` / `yyjson_loads`: decoded value differs from Python json.loads
- `gsoc-2018.json` / `yyjson_loads`: decoded value differs from Python json.loads
- `poet.json` / `yyjson_loads`: decoded value differs from Python json.loads
- `twitter.json` / `yyjson_loads`: decoded value differs from Python json.loads
