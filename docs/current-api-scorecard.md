# Current API Scorecard

Date: 2026-09-24

This scorecard is the shortest honest answer to "what should I use from this repo today?"

For the current benchmark snapshot behind these recommendations, see [docs/benchmark-snapshot.md](docs/benchmark-snapshot.md) and [docs/benchmark-snapshot.json](docs/benchmark-snapshot.json). To regenerate all tracked artifacts from the current harness, run `make benchmark-artifacts`. To verify that those tracked generated artifacts are current without rewriting them, run `make verify-benchmark-artifacts`.

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

- Complete document, fastest in-repo large-payload path:
  - Use `decode_complete_json_view(...)` or `make_complete_json_view_decoder(...)`
  - Best when `simdjson` view/proxy semantics are acceptable

- Complete document, selective field extraction:
  - Reused extractor: `make_tuned_json_path_extractor(..., framing="single")`
  - One-shot call: `extract_tuned_json_paths(..., framing="single")`
  - For large documents this effectively tracks the existing `simdjson` view extractor

- NDJSON full-record decode:
  - Generic: `decode_ndjson(...)`
  - Schema-adaptive typed option: `decode_ndjson_adaptive(...)` (returns inferred msgspec records when the lines are type-stable)
  - Typed: `make_ndjson_decoder(record_type=...)`
  - Stable repeated workload: `make_tuned_ndjson_decoder(sample=..., payload_size_hint=...)`

- NDJSON selective field extraction:
  - Reused extractor: `make_tuned_json_path_extractor(..., framing="ndjson")`
  - One-shot call: `extract_tuned_json_paths(..., framing="ndjson")`
  - This is the clearest top-level selective API in the repo right now

## Latest Snapshot

These numbers come from the current repo benchmark slices run on 2026-09-24; they report median process CPU seconds from seven measured batches after one untimed warm-up invocation, not wall-clock latency.

- Complete 1 MB object, 20 iterations:
  - `simdjson_parse`: `0.006358s`
  - `facade_decode_complete_json`: `0.007608s`
  - `facade_reusable_complete_decoder`: `0.005388s`
  - `msgspec_decode`: `0.006181s`
  - `orjson_loads`: `0.008953s`
  - `StreamingJsonParser — single chunk`: `0.005216s`

- Complete selective extraction, 200 iterations:
  - `simdjson_proxy_manual`: `0.077316s`
  - `tuned_complete_path_extractor`: `0.064587s`
  - `tuned_json_path_extractor`: `0.062883s`
  - `repo_path_extractor`: `0.062755s`
  - `orjson_full_then_select`: `0.305603s`
  - `msgspec_full_then_select`: `0.314272s`

- NDJSON selective extraction, 25 iterations:
  - `tuned_ndjson_path_extractor`: `0.058508s`
  - `tuned_json_path_extractor`: `0.051251s`
  - `typed_ndjson_path_extractor`: `0.048078s`
  - `orjson_full_then_select`: `0.065337s`
  - `msgspec_full_then_select`: `0.066425s`
  - `generic_ndjson_path_extractor`: `0.099446s`
  - native `sonic-rs` path: `0.053115s-0.056378s`

## Non-Recommendations

- Do not compare Pydantic Core `allow_partial` as a strict partial-value peer; it is a fast structural finisher but does not preserve unfinished string values.
- Do not recommend the native selective NDJSON path as the default. Current evidence still does not justify it.
- Do not recommend the typed complete selective extractor as the universal complete selective path. It helps on smaller object-shaped documents, but the tuned selector is the practical recommendation.
