# Current API Scorecard

Date: 2026-09-25

This scorecard is the shortest honest answer to "what should I use from this repo today?"

For the current benchmark snapshot behind these recommendations, see [docs/benchmark-snapshot.md](benchmark-snapshot.md) and [docs/benchmark-snapshot.json](benchmark-snapshot.json). To regenerate all tracked artifacts from the current harness, run `make benchmark-artifacts`. To verify that those tracked generated artifacts are current without rewriting them, run `make verify-benchmark-artifacts`.
For the complete top-level export inventory and proposed 0.3 API tiers, see [docs/public-api.md](public-api.md). Primary recommendations use framing and workload semantics while leaving backend selection to the library.
Strict chunk-by-chunk performance is measured separately in [docs/incremental-benchmark.md](incremental-benchmark.md); the same-source ABI-mode investigation is in [docs/abi3-incremental-investigation.md](abi3-incremental-investigation.md).

## Recommended APIs

- Strict incremental partial streaming:
  - Use `StreamingJsonParser`
  - Best when you need real delta-chunk correctness and explicit `EMPTY` / `PARTIAL` / `COMPLETE` / `INVALID` states
  - With the optional `streaming_json_parser_native` wheel, single-document partial modes use the Rust incremental core
  - Call `finish()` when the source is exhausted, especially for root scalars or a final NDJSON line without a newline
  - Use `parser.feed(chunk)` when each chunk is consumed and polled immediately; it collapses the native boundary

- Structural partial snapshots without unfinished-string semantics:
  - Use `StreamingJsonParser(partial_mode="structural")`
  - For an already available prefix, use `decode_structural_partial_json(...)` to avoid parser-object overhead
  - For repeated prefixes with a stable input representation, use `make_tuned_structural_partial_decoder(sample=...)`
  - Prefer the parser for fine-grained delta chunks; prefer the one-shot or tuned finisher when prefixes arrive in coarse batches
  - Uses the calibrated native facade, Pydantic Core, or Jiter finisher path according to the representative workload
  - Omits unfinished strings and may complete scalar prefixes before `finish()`
  - One-shot structural finishers return `None` for syntactically valid but incomplete root scalars
  - Use `partial_mode="structural_trailing_strings"` when the trailing unfinished string must be retained

Use the structural parser when the caller needs a stateful snapshot after many small delta chunks. If the caller already has coarse prefixes, use `decode_structural_partial_json(...)` or a sample-tuned finisher instead; reparsing a coarse prefix can be cheaper than constructing and synchronizing an incremental tree. This distinction is workload-driven and is not collapsed into one universal route because the crossover varies with chunk size, document shape, and whether unfinished strings are retained.

- Complete document, detached Python objects:
  - Use `decode_complete_json(...)`
  - If you know the payload size band or have a representative sample and will reuse the decoder, prefer `make_tuned_complete_json_decoder(...)`
  - Pass both `sample=` and `payload_size_hint=` to validate and benchmark strict compatible backends once at construction for representatives at least 64 bytes; calibration uses the sample's input representation and replaces the static fallback only after a 10% measured speed margin for complete JSON or a 20% margin for NDJSON

- Advanced complete-document view path:
  - Use `decode_complete_json_view(...)` or `make_complete_json_view_decoder(...)`
  - Best when `simdjson` view/proxy semantics are acceptable

- Complete document, selective field extraction:
  - Reused extractor: `make_tuned_json_path_extractor(..., framing="single")`
  - One-shot call: `extract_complete_json_paths(...)`
  - For large documents this effectively tracks the existing `simdjson` view extractor

- NDJSON full-record decode:
  - One-shot generic decode: `decode_ndjson(...)`
  - Stable repeated workload: `make_tuned_ndjson_decoder(sample=..., payload_size_hint=...)`
  - Advanced typed options: `make_ndjson_decoder(record_type=...)` or `decode_ndjson_adaptive(...)` (the latter infers `msgspec` records when the lines are type-stable)

- NDJSON selective field extraction:
  - Reused extractor: `make_tuned_json_path_extractor(..., framing="ndjson")`
  - One-shot call: `extract_ndjson_paths(...)`
  - One-shot calls express framing directly; construct and reuse the tuned extractor for a stable workload

- Advanced complete-document and NDJSON typed path extractors are available when `msgspec` records match the workload; they are not the default selective API

## Latest Snapshot

These numbers come from the current repo benchmark slices run on 2026-09-25; they report median process CPU seconds from seven measured batches after one untimed warm-up invocation, not wall-clock latency.

- Complete 1 MB object, 20 iterations:
  - `simdjson_parse`: `0.006460s`
  - `facade_decode_complete_json`: `0.009256s`
  - `facade_reusable_complete_decoder`: `0.008288s`
  - `msgspec_decode`: `0.006848s`
  - `orjson_loads`: `0.012285s`
  - `StreamingJsonParser — single chunk`: `0.005315s`

- Complete selective extraction, 200 iterations:
  - `simdjson_proxy_manual`: `0.062394s`
  - `tuned_complete_path_extractor`: `0.076090s`
  - `tuned_json_path_extractor`: `0.074741s`
  - `repo_path_extractor`: `0.068094s`
  - `orjson_full_then_select`: `0.286038s`
  - `msgspec_full_then_select`: `0.309525s`

- NDJSON selective extraction, 25 iterations:
  - `tuned_ndjson_path_extractor`: `0.048918s`
  - `tuned_json_path_extractor`: `0.047184s`
  - `typed_ndjson_path_extractor`: `0.051809s`
  - `orjson_full_then_select`: `0.088229s`
  - `msgspec_full_then_select`: `0.084574s`
  - `generic_ndjson_path_extractor`: `0.137621s`
  - native `sonic-rs` path: `0.065560s-0.074198s`

## Non-Recommendations

- Do not compare Pydantic Core `allow_partial` as a strict partial-value peer; it is a fast structural finisher but does not preserve unfinished string values.
- Native selective NDJSON functions are experimental backend-forcing APIs for tests and benchmarks, not normal recommendations.
- Do not recommend the typed complete selective extractor as the universal complete selective path. It helps on smaller object-shaped documents, but the backend-selecting tuned factory is the practical reusable recommendation.
