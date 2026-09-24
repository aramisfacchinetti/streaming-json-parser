# Community JSON Benchmark Snapshot

Date: 2026-09-24

This run adapts the complete-document load workload and public data files from [TkTech/json_benchmark](https://github.com/TkTech/json_benchmark). It is a community-maintained Python parser benchmark, not a formal industry standard. The upstream project also has SAX/event streaming cases; those are omitted because they do not materialize the same result as this library.

## Provenance

- Upstream commit: `52d596b8a9bc0e00e654747298a8ec5b0d95152b`
- Upstream benchmark definition: `tests/test_json.py::test_full_document_read`
- Package: `streaming-json-parser 0.2.1` (installed distribution); source revision: `80f3576cc3c6e899c26bff70ca7a2324d4496e08`
- Module `__version__`: `0.2.0`; installed distribution metadata: `0.2.1`
- Working tree dirty: `False`
- Python and platform: `3.14.0` / `macOS-27.0-arm64-arm-64bit-Mach-O`
- Processor: `Apple M2 Pro` (arm64)
- Native extension: `0.2.1`
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
| 1 | `orjson_loads` | 7.089 | 302.8 |
| 2 | `yyjson_loads` | 7.126 | 301.3 |
| 3 | `reusable_complete_decoder` | 7.344 | 292.3 |
| 4 | `decode_complete_json` | 7.900 | 271.7 |
| 5 | `msgspec_decode` | 8.005 | 268.2 |
| 6 | `simdjson_loads` | 8.742 | 245.6 |
| 7 | `ujson_loads` | 13.191 | 162.7 |
| 8 | `rapidjson_loads` | 26.570 | 80.8 |
| 9 | `json_loads` | 28.780 | 74.6 |
| 10 | `streaming_parser_single_chunk` | 54.667 | 39.3 |

### `data/citm_catalog.json` — 1,727,204 bytes

SHA-256: `a73e7a883f6ea8de113dff59702975e60119b4b58d451d518a929f31c92e2059`. 2 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `decode_complete_json` | 2.897 | 568.6 |
| 2 | `orjson_loads` | 2.957 | 557.0 |
| 3 | `reusable_complete_decoder` | 3.046 | 540.8 |
| 4 | `msgspec_decode` | 3.457 | 476.5 |
| 5 | `simdjson_loads` | 4.976 | 331.0 |
| 6 | `ujson_loads` | 5.752 | 286.4 |
| 7 | `rapidjson_loads` | 5.909 | 278.7 |
| 8 | `json_loads` | 7.057 | 233.4 |
| 9 | `streaming_parser_single_chunk` | 15.164 | 108.6 |

### `data/twitter.json` — 631,514 bytes

SHA-256: `a08b769f32b95f426cbc3abafcec65c1a19d3eb544d4ddf320eae142c99efc5d`. 6 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `decode_complete_json` | 1.099 | 548.2 |
| 2 | `orjson_loads` | 1.304 | 462.0 |
| 3 | `msgspec_decode` | 1.374 | 438.4 |
| 4 | `reusable_complete_decoder` | 1.561 | 385.7 |
| 5 | `simdjson_loads` | 2.429 | 248.0 |
| 6 | `ujson_loads` | 2.573 | 234.1 |
| 7 | `rapidjson_loads` | 3.028 | 198.9 |
| 8 | `json_loads` | 3.056 | 197.0 |
| 9 | `streaming_parser_single_chunk` | 6.377 | 94.4 |

### `data/gsoc-2018.json` — 3,327,831 bytes

SHA-256: `72f1ef4898d88049da856c2ab8f4ec3e2c968ce209b2bbfd16cef842eb2e185f`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `orjson_loads` | 4.564 | 695.4 |
| 2 | `msgspec_decode` | 4.632 | 685.2 |
| 3 | `decode_complete_json` | 4.753 | 667.7 |
| 4 | `reusable_complete_decoder` | 4.824 | 657.9 |
| 5 | `simdjson_loads` | 5.340 | 594.3 |
| 6 | `ujson_loads` | 6.273 | 505.9 |
| 7 | `json_loads` | 9.033 | 351.3 |
| 8 | `streaming_parser_single_chunk` | 11.446 | 277.3 |
| 9 | `rapidjson_loads` | 12.460 | 254.7 |

### `data/poet.json` — 3,512,883 bytes

SHA-256: `2c2689a3b5df460f02e4dee2a36ac32cc27c43e2964fba7965eba3469bf617ec`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `ujson_loads` | 5.995 | 558.8 |
| 2 | `reusable_complete_decoder` | 6.222 | 538.4 |
| 3 | `json_loads` | 6.952 | 481.9 |
| 4 | `decode_complete_json` | 7.053 | 475.0 |
| 5 | `msgspec_decode` | 7.548 | 443.8 |
| 6 | `orjson_loads` | 8.978 | 373.2 |
| 7 | `simdjson_loads` | 10.972 | 305.3 |
| 8 | `streaming_parser_single_chunk` | 13.031 | 257.1 |
| 9 | `rapidjson_loads` | 13.295 | 252.0 |

### `data/fgo.json` — 48,765,043 bytes

SHA-256: `4d0153f122aa4f049888dce8162d38b677e0127e2be90ae3afd998813f44a738`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `decode_complete_json` | 219.986 | 211.4 |
| 2 | `reusable_complete_decoder` | 231.460 | 200.9 |
| 3 | `orjson_loads` | 241.810 | 192.3 |
| 4 | `msgspec_decode` | 256.221 | 181.5 |
| 5 | `ujson_loads` | 364.015 | 127.8 |
| 6 | `simdjson_loads` | 418.151 | 111.2 |
| 7 | `rapidjson_loads` | 477.537 | 97.4 |
| 8 | `json_loads` | 621.981 | 74.8 |
| 9 | `streaming_parser_single_chunk` | 1,025.040 | 45.4 |

## Reproduce

```bash
python -m pip install 'streaming-json-parser[accelerated,benchmark]==0.2.1'
python -m pip install 'streaming-json-parser-native==0.2.1'
git clone https://github.com/TkTech/json_benchmark.git /tmp/tktech-json-benchmark
git -C /tmp/tktech-json-benchmark checkout 52d596b8a9bc0e00e654747298a8ec5b0d95152b
make benchmark-release-artifacts COMMUNITY_JSON_CORPUS_DIR=/private/tmp/tktech-json-benchmark/data
```

The input files are not copied into this repository. The JSON snapshot records the upstream revision, file hashes, and exact tool versions for this run.

## Excluded incompatible results

- `citm_catalog.json` / `yyjson_loads`: decoded value differs from Python json.loads
- `fgo.json` / `yyjson_loads`: decoded value differs from Python json.loads
- `gsoc-2018.json` / `yyjson_loads`: decoded value differs from Python json.loads
- `poet.json` / `yyjson_loads`: decoded value differs from Python json.loads
- `twitter.json` / `yyjson_loads`: decoded value differs from Python json.loads
