# Community JSON Benchmark Snapshot

Date: 2026-09-25

This run adapts the complete-document load workload and public data files from [TkTech/json_benchmark](https://github.com/TkTech/json_benchmark). It is a community-maintained Python parser benchmark, not a formal industry standard. The upstream project also has SAX/event streaming cases; those are omitted because they do not materialize the same result as this library.

## Provenance

- Upstream commit: `52d596b8a9bc0e00e654747298a8ec5b0d95152b`
- Upstream benchmark definition: `tests/test_json.py::test_full_document_read`
- Package: `streaming-json-parser 0.2.2` (installed distribution); source revision: `9da80493873f07c024ce80780e42436abddc58e9`
- Module `__version__`: `0.2.2`; installed distribution metadata: `0.2.2`
- Working tree dirty: `False`
- Python and platform: `3.14.0` / `macOS-27.0-arm64-arm-64bit-Mach-O`
- Processor: `Apple M2 Pro` (arm64)
- Native extension: `0.2.2`
- Benchmark library versions: `json (stdlib)=3.14.0`, `msgspec=0.21.1`, `orjson=3.12.0`, `rapidjson=1.25`, `simdjson=7.0.2`, `ujson=6.0.0`, `yyjson=4.0.6`

## Methodology

- Operation: decode the complete document into an ordinary Python JSON value.
- Input: UTF-8 data file decoded to Python str before timing; file I/O and UTF-8 decoding are outside timing.
- Timing: `time.perf_counter`; median per-operation elapsed time across 7 measured batches; 1 warm-up batch(s).
- Repetitions: max(1, floor(4 MiB / UTF-8 file byte length)), capped at 50; same count for every compatible decoder on a file.
- Fairness check: each candidate output was compared recursively with Python json.loads; booleans, integers, and floats must retain their exact Python value types, and incompatible candidates are excluded for that file.
- Rate: UTF-8 file bytes divided by median per-operation elapsed time; chart uses MiB/s, higher is better.
- Scope: This adapts only the upstream complete-load workload. Its SAX/event streaming cases are not comparable because this library materializes Python values.

The chart uses one scale per corpus file. Use the number labels and the exact values below for cross-file comparisons.

## Results

### `data/canada.json` — 2,251,051 bytes

SHA-256: `f83b3b354030d5dd58740c68ac4fecef64cb730a0d12a90362a7f23077f50d78`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `yyjson_loads` | 8.483 | 253.1 |
| 2 | `decode_complete_json` | 9.137 | 235.0 |
| 3 | `orjson_loads` | 9.380 | 228.9 |
| 4 | `simdjson_loads` | 9.691 | 221.5 |
| 5 | `reusable_complete_decoder` | 12.279 | 174.8 |
| 6 | `msgspec_decode` | 16.800 | 127.8 |
| 7 | `ujson_loads` | 18.308 | 117.3 |
| 8 | `rapidjson_loads` | 36.044 | 59.6 |
| 9 | `json_loads` | 37.912 | 56.6 |
| 10 | `streaming_parser_single_chunk` | 62.891 | 34.1 |

### `data/citm_catalog.json` — 1,727,204 bytes

SHA-256: `a73e7a883f6ea8de113dff59702975e60119b4b58d451d518a929f31c92e2059`. 2 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `reusable_complete_decoder` | 3.397 | 484.8 |
| 2 | `decode_complete_json` | 4.162 | 395.8 |
| 3 | `msgspec_decode` | 4.218 | 390.6 |
| 4 | `orjson_loads` | 4.928 | 334.3 |
| 5 | `simdjson_loads` | 6.060 | 271.8 |
| 6 | `json_loads` | 8.225 | 200.3 |
| 7 | `ujson_loads` | 9.798 | 168.1 |
| 8 | `rapidjson_loads` | 11.870 | 138.8 |
| 9 | `streaming_parser_single_chunk` | 22.340 | 73.7 |

### `data/twitter.json` — 631,514 bytes

SHA-256: `a08b769f32b95f426cbc3abafcec65c1a19d3eb544d4ddf320eae142c99efc5d`. 6 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `decode_complete_json` | 1.327 | 454.0 |
| 2 | `orjson_loads` | 1.852 | 325.3 |
| 3 | `reusable_complete_decoder` | 2.012 | 299.4 |
| 4 | `msgspec_decode` | 2.217 | 271.7 |
| 5 | `ujson_loads` | 2.429 | 248.0 |
| 6 | `simdjson_loads` | 3.005 | 200.4 |
| 7 | `json_loads` | 4.723 | 127.5 |
| 8 | `rapidjson_loads` | 4.797 | 125.5 |
| 9 | `streaming_parser_single_chunk` | 8.391 | 71.8 |

### `data/gsoc-2018.json` — 3,327,831 bytes

SHA-256: `72f1ef4898d88049da856c2ab8f4ec3e2c968ce209b2bbfd16cef842eb2e185f`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `ujson_loads` | 7.609 | 417.1 |
| 2 | `simdjson_loads` | 7.768 | 408.5 |
| 3 | `json_loads` | 8.724 | 363.8 |
| 4 | `reusable_complete_decoder` | 9.628 | 329.6 |
| 5 | `msgspec_decode` | 9.800 | 323.9 |
| 6 | `decode_complete_json` | 10.015 | 316.9 |
| 7 | `rapidjson_loads` | 15.032 | 211.1 |
| 8 | `orjson_loads` | 17.262 | 183.9 |
| 9 | `streaming_parser_single_chunk` | 17.399 | 182.4 |

### `data/poet.json` — 3,512,883 bytes

SHA-256: `2c2689a3b5df460f02e4dee2a36ac32cc27c43e2964fba7965eba3469bf617ec`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `msgspec_decode` | 7.047 | 475.4 |
| 2 | `orjson_loads` | 7.604 | 440.6 |
| 3 | `ujson_loads` | 8.915 | 375.8 |
| 4 | `reusable_complete_decoder` | 8.961 | 373.9 |
| 5 | `simdjson_loads` | 9.672 | 346.4 |
| 6 | `decode_complete_json` | 9.802 | 341.8 |
| 7 | `json_loads` | 11.650 | 287.6 |
| 8 | `streaming_parser_single_chunk` | 23.426 | 143.0 |
| 9 | `rapidjson_loads` | 23.606 | 141.9 |

### `data/fgo.json` — 48,765,043 bytes

SHA-256: `4d0153f122aa4f049888dce8162d38b677e0127e2be90ae3afd998813f44a738`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `reusable_complete_decoder` | 226.872 | 205.0 |
| 2 | `decode_complete_json` | 232.820 | 199.8 |
| 3 | `orjson_loads` | 234.288 | 198.5 |
| 4 | `msgspec_decode` | 235.342 | 197.6 |
| 5 | `ujson_loads` | 459.444 | 101.2 |
| 6 | `simdjson_loads` | 475.557 | 97.8 |
| 7 | `json_loads` | 571.463 | 81.4 |
| 8 | `rapidjson_loads` | 1,124.805 | 41.3 |
| 9 | `streaming_parser_single_chunk` | 1,260.165 | 36.9 |

## Reproduce

```bash
python -m pip install 'streaming-json-parser[accelerated,benchmark]==0.2.2'
python -m pip install 'streaming-json-parser-native==0.2.2'
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
