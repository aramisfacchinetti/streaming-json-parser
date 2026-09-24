# Community JSON Benchmark Snapshot

Date: 2026-09-24

This run adapts the complete-document load workload and public data files from [TkTech/json_benchmark](https://github.com/TkTech/json_benchmark). It is a community-maintained Python parser benchmark, not a formal industry standard. The upstream project also has SAX/event streaming cases; those are omitted because they do not materialize the same result as this library.

## Provenance

- Upstream commit: `52d596b8a9bc0e00e654747298a8ec5b0d95152b`
- Upstream benchmark definition: `tests/test_json.py::test_full_document_read`
- Package: `streaming-json-parser 0.2.2` (installed distribution); source revision: `9d872f32c9189df5c98f1ca3ec447f1e33e1ebb1`
- Module `__version__`: `0.2.2`; installed distribution metadata: `0.2.2`
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
| 1 | `yyjson_loads` | 6.294 | 341.1 |
| 2 | `decode_complete_json` | 7.242 | 296.4 |
| 3 | `reusable_complete_decoder` | 7.291 | 294.4 |
| 4 | `orjson_loads` | 7.518 | 285.6 |
| 5 | `msgspec_decode` | 8.218 | 261.2 |
| 6 | `simdjson_loads` | 8.506 | 252.4 |
| 7 | `ujson_loads` | 13.536 | 158.6 |
| 8 | `rapidjson_loads` | 26.882 | 79.9 |
| 9 | `json_loads` | 29.116 | 73.7 |
| 10 | `streaming_parser_single_chunk` | 50.563 | 42.5 |

### `data/citm_catalog.json` — 1,727,204 bytes

SHA-256: `a73e7a883f6ea8de113dff59702975e60119b4b58d451d518a929f31c92e2059`. 2 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `orjson_loads` | 2.668 | 617.4 |
| 2 | `decode_complete_json` | 2.737 | 601.9 |
| 3 | `reusable_complete_decoder` | 2.823 | 583.4 |
| 4 | `msgspec_decode` | 3.062 | 538.0 |
| 5 | `ujson_loads` | 5.077 | 324.4 |
| 6 | `rapidjson_loads` | 5.675 | 290.2 |
| 7 | `json_loads` | 6.443 | 255.6 |
| 8 | `simdjson_loads` | 7.993 | 206.1 |
| 9 | `streaming_parser_single_chunk` | 13.416 | 122.8 |

### `data/twitter.json` — 631,514 bytes

SHA-256: `a08b769f32b95f426cbc3abafcec65c1a19d3eb544d4ddf320eae142c99efc5d`. 6 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `reusable_complete_decoder` | 1.001 | 601.9 |
| 2 | `orjson_loads` | 1.191 | 505.6 |
| 3 | `msgspec_decode` | 1.248 | 482.5 |
| 4 | `decode_complete_json` | 1.355 | 444.6 |
| 5 | `ujson_loads` | 1.749 | 344.3 |
| 6 | `simdjson_loads` | 1.985 | 303.3 |
| 7 | `rapidjson_loads` | 2.931 | 205.5 |
| 8 | `json_loads` | 3.152 | 191.1 |
| 9 | `streaming_parser_single_chunk` | 5.942 | 101.4 |

### `data/gsoc-2018.json` — 3,327,831 bytes

SHA-256: `72f1ef4898d88049da856c2ab8f4ec3e2c968ce209b2bbfd16cef842eb2e185f`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `msgspec_decode` | 3.753 | 845.6 |
| 2 | `decode_complete_json` | 3.959 | 801.6 |
| 3 | `reusable_complete_decoder` | 4.031 | 787.3 |
| 4 | `orjson_loads` | 4.383 | 724.1 |
| 5 | `ujson_loads` | 5.376 | 590.3 |
| 6 | `simdjson_loads` | 5.564 | 570.4 |
| 7 | `json_loads` | 8.257 | 384.4 |
| 8 | `streaming_parser_single_chunk` | 9.842 | 322.5 |
| 9 | `rapidjson_loads` | 10.389 | 305.5 |

### `data/poet.json` — 3,512,883 bytes

SHA-256: `2c2689a3b5df460f02e4dee2a36ac32cc27c43e2964fba7965eba3469bf617ec`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `orjson_loads` | 4.902 | 683.4 |
| 2 | `reusable_complete_decoder` | 5.305 | 631.5 |
| 3 | `ujson_loads` | 5.585 | 599.8 |
| 4 | `msgspec_decode` | 5.761 | 581.5 |
| 5 | `decode_complete_json` | 6.100 | 549.2 |
| 6 | `json_loads` | 6.717 | 498.8 |
| 7 | `simdjson_loads` | 7.791 | 430.0 |
| 8 | `streaming_parser_single_chunk` | 11.071 | 302.6 |
| 9 | `rapidjson_loads` | 12.662 | 264.6 |

### `data/fgo.json` — 48,765,043 bytes

SHA-256: `4d0153f122aa4f049888dce8162d38b677e0127e2be90ae3afd998813f44a738`. 1 load(s) per sample; 7 samples.

| Rank | Decoder | Median CPU ms/load | MiB/s |
| ---: | --- | ---: | ---: |
| 1 | `orjson_loads` | 208.574 | 223.0 |
| 2 | `msgspec_decode` | 210.206 | 221.2 |
| 3 | `decode_complete_json` | 211.798 | 219.6 |
| 4 | `reusable_complete_decoder` | 225.476 | 206.3 |
| 5 | `ujson_loads` | 369.207 | 126.0 |
| 6 | `simdjson_loads` | 406.332 | 114.5 |
| 7 | `rapidjson_loads` | 474.192 | 98.1 |
| 8 | `json_loads` | 551.068 | 84.4 |
| 9 | `streaming_parser_single_chunk` | 1,039.039 | 44.8 |

## Reproduce

```bash
python -m pip install 'streaming-json-parser[accelerated,benchmark]==0.2.2'
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
