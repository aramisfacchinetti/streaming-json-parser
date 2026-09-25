# Community JSON Benchmark Snapshot

Date: 2026-09-25

This run adapts the complete-document load workload and public data files from [TkTech/json_benchmark](https://github.com/TkTech/json_benchmark). It is a community-maintained Python parser benchmark, not a formal industry standard. The upstream project also has SAX/event streaming cases; those are omitted because they do not materialize the same result as this library.

## Provenance

- Upstream commit: `52d596b8a9bc0e00e654747298a8ec5b0d95152b`
- Upstream benchmark definition: `tests/test_json.py::test_full_document_read`
- Package: `streaming-json-parser 0.2.3` (installed distribution); source revision: `55f38cd26ab10d73c015381980be60dcc7ae1f66`
- Module `__version__`: `0.2.3`; installed distribution metadata: `0.2.3`
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
| 1 | `simdjson_loads` | 11.406 | 188.2 |
| 2 | `msgspec_decode` | 11.453 | 187.4 |
| 3 | `orjson_loads` | 13.578 | 158.1 |
| 4 | `yyjson_loads` | 14.534 | 147.7 |
| 5 | `decode_complete_json` | 15.007 | 143.0 |
| 6 | `ujson_loads` | 19.213 | 111.7 |
| 7 | `reusable_complete_decoder` | 19.798 | 108.4 |
| 8 | `json_loads` | 37.529 | 57.2 |
| 9 | `rapidjson_loads` | 41.684 | 51.5 |
| 10 | `streaming_parser_single_chunk` | 65.776 | 32.6 |

### `data/citm_catalog.json` — 1,727,204 bytes

SHA-256: `a73e7a883f6ea8de113dff59702975e60119b4b58d451d518a929f31c92e2059`. 2 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `reusable_complete_decoder` | 4.926 | 334.4 |
| 2 | `orjson_loads` | 5.229 | 315.0 |
| 3 | `decode_complete_json` | 5.603 | 294.0 |
| 4 | `msgspec_decode` | 5.781 | 284.9 |
| 5 | `ujson_loads` | 7.775 | 211.9 |
| 6 | `rapidjson_loads` | 8.638 | 190.7 |
| 7 | `simdjson_loads` | 10.155 | 162.2 |
| 8 | `json_loads` | 13.403 | 122.9 |
| 9 | `streaming_parser_single_chunk` | 23.375 | 70.5 |

### `data/twitter.json` — 631,514 bytes

SHA-256: `a08b769f32b95f426cbc3abafcec65c1a19d3eb544d4ddf320eae142c99efc5d`. 6 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `orjson_loads` | 1.846 | 326.3 |
| 2 | `decode_complete_json` | 2.553 | 235.9 |
| 3 | `reusable_complete_decoder` | 3.043 | 197.9 |
| 4 | `msgspec_decode` | 3.372 | 178.6 |
| 5 | `rapidjson_loads` | 3.381 | 178.1 |
| 6 | `json_loads` | 4.809 | 125.2 |
| 7 | `simdjson_loads` | 6.109 | 98.6 |
| 8 | `ujson_loads` | 6.465 | 93.2 |
| 9 | `streaming_parser_single_chunk` | 22.774 | 26.4 |

### `data/gsoc-2018.json` — 3,327,831 bytes

SHA-256: `72f1ef4898d88049da856c2ab8f4ec3e2c968ce209b2bbfd16cef842eb2e185f`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `msgspec_decode` | 4.484 | 707.8 |
| 2 | `orjson_loads` | 6.459 | 491.4 |
| 3 | `json_loads` | 10.893 | 291.4 |
| 4 | `streaming_parser_single_chunk` | 11.505 | 275.8 |
| 5 | `simdjson_loads` | 12.941 | 245.2 |
| 6 | `rapidjson_loads` | 15.826 | 200.5 |
| 7 | `decode_complete_json` | 27.946 | 113.6 |
| 8 | `reusable_complete_decoder` | 27.955 | 113.5 |
| 9 | `ujson_loads` | 31.124 | 102.0 |

### `data/poet.json` — 3,512,883 bytes

SHA-256: `2c2689a3b5df460f02e4dee2a36ac32cc27c43e2964fba7965eba3469bf617ec`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `reusable_complete_decoder` | 9.774 | 342.8 |
| 2 | `decode_complete_json` | 11.340 | 295.4 |
| 3 | `msgspec_decode` | 12.058 | 277.8 |
| 4 | `orjson_loads` | 12.988 | 257.9 |
| 5 | `simdjson_loads` | 15.825 | 211.7 |
| 6 | `json_loads` | 16.852 | 198.8 |
| 7 | `streaming_parser_single_chunk` | 19.516 | 171.7 |
| 8 | `ujson_loads` | 28.433 | 117.8 |
| 9 | `rapidjson_loads` | 38.783 | 86.4 |

### `data/fgo.json` — 48,765,043 bytes

SHA-256: `4d0153f122aa4f049888dce8162d38b677e0127e2be90ae3afd998813f44a738`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median elapsed ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `msgspec_decode` | 247.386 | 188.0 |
| 2 | `reusable_complete_decoder` | 280.008 | 166.1 |
| 3 | `ujson_loads` | 330.462 | 140.7 |
| 4 | `orjson_loads` | 440.863 | 105.5 |
| 5 | `decode_complete_json` | 445.310 | 104.4 |
| 6 | `simdjson_loads` | 498.339 | 93.3 |
| 7 | `rapidjson_loads` | 561.689 | 82.8 |
| 8 | `json_loads` | 942.517 | 49.3 |
| 9 | `streaming_parser_single_chunk` | 984.484 | 47.2 |

## Reproduce

```bash
python -m pip install 'streaming-json-parser[accelerated,benchmark]==0.2.3'
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
