# Public API design for 0.3

This document records the current top-level exports and proposes the tiers for
the 0.3 API stabilization work. It describes current behavior separately from
the proposal: no exports, parser behavior, or package versions are changed by
this document.

The package is still beta. The 0.2.0 changelog introduced the complete-document,
NDJSON, structural-partial, typed, and selective-extraction families, and
replaced the earlier `StreamingJsonParser` with strict incremental parsing.
That history supports a deliberate 0.3 contract and migration period; it does
not justify removing exported names under 0.2.x.

## Proposed tiers

The current `__all__` contains **32 names**. The proposed 0.3 classification
assigns each name one tier:

| Tier | Count | Meaning |
| --- | ---: | --- |
| Primary | 12 | Small, semantic, backend-selecting entry points intended for ordinary use and eventual 1.0 stability. |
| Advanced | 15 | Reusable lower-level, typed, view, or specialized alternatives with a useful but narrower contract. |
| Experimental | 2 | APIs that explicitly force the optional native backend. |
| Compatibility | 2 | The historical parser name and package version metadata. |
| Internal candidate | 1 | An exported wrapper with no distinct semantics that should be reviewed for deprecation. |

Primary APIs follow the rule **users choose semantics and workload; the library
chooses the backend**. “Advanced” does not mean unsupported: these names remain
available and tested. The tier is a recommendation about the stable design,
not a removal decision. The Advanced APIs remain supported, with no deprecation
or removal planned. Experimental APIs are retained as callable benchmark and
diagnostic hooks, but they carry no forward-compatibility promise.

## Complete export inventory

`README` and `Scorecard` indicate exact-name mentions in `README.md` and
`docs/current-api-scorecard.md`. “Package use” means the implementation module
references the symbol by name; tests and benchmark scripts also exercise the
exported surface. Backend coupling describes the public operation or exposed
result, not the implementation backends that the library may select
internally.

| Export (kind) | Purpose, overlap, and semantic distinction | README / scorecard | Backend coupling | Package use | Proposed 0.3 tier and replacement |
| --- | --- | --- | --- | --- | --- |
| `StreamingJsonParser` (class alias) | Canonical incremental parser name. Strict partial state by default; `framing="ndjson"` also supports streaming records. Backend selection is internal. | Yes / Yes | No backend choice in its contract; runtime may use native code. | No | **Primary.** |
| `__version__` (metadata) | Module version string used for package and benchmark provenance; not a parsing operation. | Yes / No | No | No | **Compatibility.** Keep as package metadata; no replacement or removal planned. |
| `HighPerformanceStreamingJsonParser` (class) | The implementation class object aliased by `StreamingJsonParser`; no user-facing semantic distinction. Internal tests and benchmarks now use the canonical name; implementation class metadata still uses this historical name. | No / No | No backend choice in its contract. | Yes | **Compatibility.** Use `StreamingJsonParser` in new code. Keep the alias and identity; warning/removal require a later migration decision. |
| `ParseResult` (class alias) | Returned result fields are public: `status`, `value`, `complete`, and `error`. Its concrete class currently comes from the native extension when available, otherwise from the Python fallback; direct construction is not a promised API. | Yes / No | **Yes:** concrete result class identity varies with native availability; field behavior is backend-independent. | Yes | **Primary.** See the field contract below. |
| `ParseStatus` (enum) | `EMPTY`, `PARTIAL`, `COMPLETE`, and `INVALID` states returned by the incremental parser. | Yes / No | No | Yes | **Primary.** |
| `decode_complete_json` (function) | Decode one complete JSON document to a detached Python value. Optional `value_type` supports explicitly typed decoding. | Yes / Yes | No for generic decoding; typed mode uses optional `msgspec`. | Yes | **Primary.** |
| `decode_complete_json_view` (function) | Decode one complete document with view/proxy semantics when `simdjson` is installed; falls back to regular decoding otherwise. | Yes / Yes | **Yes:** view results are backend-specific. | No | **Advanced.** Use `decode_complete_json` when ordinary Python values are required. |
| `decode_ndjson` (function) | Decode one NDJSON payload to a list of records; optional `record_type` requests typed records. | Yes / Yes | No for generic decoding; typed mode uses optional `msgspec`. | Yes | **Primary** for generic NDJSON. |
| `decode_ndjson_adaptive` (function) | Infer and cache a specialized record decoder from NDJSON input, falling back to generic decoding. Output representation may be inferred `msgspec` records or ordinary values. | No / Yes | **Yes:** inferred typed records depend on optional `msgspec`. | No | **Advanced.** Use `decode_ndjson` for a predictable generic value contract or an explicit `record_type` for a declared schema. |
| `decode_structural_partial_json` (function) | Finish an available JSON prefix without maintaining an incremental parser; optionally retain a trailing unfinished string. Its snapshot/scalar behavior differs from strict incremental parsing. | Yes / Yes | **Yes:** current structural finishers use optional structural backends, with fallback selection. | Yes | **Primary** when the workload is an already-available prefix. |
| `extract_complete_json_paths` (function) | One-shot projection of selected paths from one complete document. Unlike typed extraction, accepts string and integer path segments and does not require a schema sample. | No / No | No | Yes | **Primary** complete-document one-shot. |
| `extract_complete_json_typed_paths` (function) | One-shot extraction through a sample-inferred `msgspec` record; object records and identifier-safe string paths are required. Overlaps generic path extraction with a narrower typed contract. | No / No | **Yes:** requires `msgspec`. | No | **Advanced.** Use `extract_complete_json_paths` for generic paths. |
| `extract_ndjson_paths` (function) | One-shot projection of selected paths from every NDJSON record using generic decoded records. | No / No | No | No | **Primary** NDJSON one-shot. |
| `extract_ndjson_paths_native` (function) | One-shot native selective NDJSON extraction. Semantics overlap `extract_ndjson_paths`; its distinguishing feature is forcing the optional backend. | No / No | **Yes:** native extension required; raises if unavailable. | No | **Experimental.** Use `extract_ndjson_paths` unless explicitly benchmarking or testing the backend. |
| `extract_ndjson_typed_paths` (function) | One-shot extraction through sample-inferred typed NDJSON records. Requires object records and identifier-safe string paths. | No / No | **Yes:** requires `msgspec`. | No | **Advanced.** Use `extract_ndjson_paths` for generic paths. |
| `extract_tuned_complete_json_paths` (function) | One-shot complete-document wrapper. It delegates to `extract_complete_json_paths` after preserving its current byte coercion; its `sample` parameter is unused, so it has no distinct tuning behavior. | No / No | No | No | **Internal candidate.** Replacement: `extract_complete_json_paths`. Keep compatibility behavior in 0.3; consider a 0.4 warning only after a fresh usage review, and removal no earlier than 1.0 after a warning period and another audit. |
| `extract_tuned_json_paths` (function) | One-shot convenience dispatcher for `framing="single"` or `"ndjson"`. The single-document branch delegates to `extract_complete_json_paths` after preserving byte coercion and ignores `sample`; the NDJSON branch delegates to the tuned NDJSON wrapper. A caller with runtime-selected framing can use one function. | No / No | No backend is directly selected. | No | **Advanced.** Prefer framing-specific primary one-shot functions when framing is known; retain this useful dispatcher without a deprecation plan. |
| `extract_tuned_ndjson_paths` (function) | One-shot NDJSON extraction through the tuned NDJSON factory, optionally using a representative sample. Distinct from generic extraction by its selection strategy, not output framing. | No / No | No backend is forced. | Yes | **Advanced.** For repeated inputs, prefer `make_tuned_json_path_extractor(..., framing="ndjson")`. |
| `make_complete_json_decoder` (function) | Reusable non-tuned complete-document decoder; can request a `value_type`. Overlaps the one-shot decoder and tuned factory by lifecycle/selection strategy. | No / No | Typed mode uses optional `msgspec`; generic route is backend-selected. | Yes | **Advanced.** Use `make_tuned_complete_json_decoder` for a stable representative workload. |
| `make_complete_json_typed_path_extractor` (function) | Reusable `msgspec` extractor inferred from a sample; limited to object-shaped, identifier-safe string paths. | No / No | **Yes:** requires `msgspec`. | Yes | **Advanced.** Use `make_tuned_json_path_extractor(..., framing="single")` for the backend-selecting path API. |
| `make_complete_json_view_decoder` (function) | Reusable complete-document view decoder with `simdjson` proxy semantics when available. | No / Yes | **Yes:** exposes backend-specific view semantics. | Yes | **Advanced.** Use `decode_complete_json` and `make_tuned_complete_json_decoder` for ordinary Python values. |
| `make_json_path_extractor` (function) | Reusable generic complete-document path projection; caches a projector and uses a compatible parser. | No / No | No backend is forced. | Yes | **Advanced.** Use `make_tuned_json_path_extractor(..., framing="single")` for workload-aware selection. |
| `make_ndjson_decoder` (function) | Reusable non-tuned NDJSON decoder, optionally with an explicit `record_type`. | Yes / Yes | Typed mode uses optional `msgspec`; generic route selects a backend. | Yes | **Advanced.** Use `make_tuned_ndjson_decoder` for a stable repeated workload; generic one-shot is `decode_ndjson`. |
| `make_ndjson_path_extractor` (function) | Reusable generic NDJSON path projection; materializes decoded records before projection. | No / No | No backend is forced. | Yes | **Advanced.** Use `make_tuned_json_path_extractor(..., framing="ndjson")` for the recommended reusable path. |
| `make_ndjson_path_extractor_native` (function) | Reusable native selective NDJSON extractor. Same high-level result purpose as the generic extractor, but forces the optional extension. | No / No | **Yes:** native extension required; raises if unavailable. | Yes | **Experimental.** Keep for backend tests and benchmark comparisons; do not recommend for normal use. |
| `make_ndjson_typed_path_extractor` (function) | Reusable `msgspec` NDJSON extractor inferred from a sample; limited to object records and identifier-safe string paths. | No / No | **Yes:** requires `msgspec`. | Yes | **Advanced.** Use the backend-selecting tuned path factory for the ordinary selective API. |
| `make_tuned_complete_json_decoder` (function) | Reusable complete-document decoder. A sample and size hint can trigger construction-time compatibility checks and calibration; supports materialized or view mode. | Yes / Yes | No backend is forced in materialize mode; view mode has backend-specific results. | No | **Primary** for repeated/stable complete-document workloads; use `mode="view"` only when view semantics are acceptable. |
| `make_tuned_complete_json_path_extractor` (function) | Reusable complete-document path extractor that may select typed extraction for compatible small object samples; otherwise uses the generic path extractor. | No / No | Typed route uses optional `msgspec`; generic route is backend-selected. | Yes | **Advanced.** Use `make_tuned_json_path_extractor(..., framing="single")`. |
| `make_tuned_json_path_extractor` (function) | Reusable selective extractor for either one document or NDJSON via semantic `framing`; owns the backend/strategy choice and preserves the reusable lifecycle distinction. | Yes / Yes | No backend is forced. | No | **Primary** reusable selective extraction API. |
| `make_tuned_ndjson_decoder` (function) | Reusable NDJSON decoder that can bind to a representative sample and payload size. Optional explicit record type delegates to the typed decoder. | No / Yes | No backend is forced; explicit typed mode uses `msgspec`. | No | **Primary** for repeated/stable NDJSON workloads. |
| `make_tuned_ndjson_path_extractor` (function) | Reusable NDJSON extractor that can select a typed path for a compatible sample; otherwise uses the generic extractor. | No / No | Typed route uses optional `msgspec`; generic route is backend-selected. | Yes | **Advanced.** Use `make_tuned_json_path_extractor(..., framing="ndjson")`. |
| `make_tuned_structural_partial_decoder` (function) | Reusable structural-prefix finisher bound to a sample's input representation and shape. It reparses prefixes rather than keeping strict incremental parser state. | No / Yes | **Yes:** selection among optional structural backends. | No | **Primary** for repeated/coarse structural prefixes; use `StreamingJsonParser` for strict chunk-by-chunk state. |

The README shows the quickstart and normal workflows, not every export. The
generated scorecard now recommends framing-specific one-shot extraction and
the reusable tuned factory. Its benchmark rows remain intact and do not
promote compatibility or backend-forcing names as normal recommendations.

## Repository and external usage audit

Audit date: 2026-09-25. The local audit parsed the current `__all__`, searched
all tracked repository text for each exact export name, and separately checked
Python import statements under `src/`, `tests/`, and `scripts/`. The table
below counts package-internal direct `Name(...)` call expressions in
`high_performance_parser.py`, distinct behavioral-test files, benchmark script
files, README mentions, Markdown documentation files, and example files. It
excludes this inventory and the API-set pin test from usage counts; the pin
test still verifies all 32 names. Test and script counts are file matches, not
runtime invocation totals. There is no tracked `examples/` directory.

| Export | Package calls | Test files | Benchmark scripts | README | Docs | Examples |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `StreamingJsonParser` | 0 | 7 | 7 | 1 | 2 | 0 |
| `__version__` | 0 | 1 | 3 | 1 | 5 | 0 |
| `HighPerformanceStreamingJsonParser` | 0 | 0 | 0 | 0 | 0 | 0 |
| `ParseResult` | 35 | 2 | 0 | 1 | 0 | 0 |
| `ParseStatus` | 0 | 4 | 4 | 1 | 0 | 0 |
| `decode_complete_json` | 5 | 2 | 4 | 1 | 7 | 0 |
| `decode_complete_json_view` | 0 | 1 | 1 | 1 | 1 | 0 |
| `decode_ndjson` | 6 | 2 | 2 | 1 | 1 | 0 |
| `decode_ndjson_adaptive` | 0 | 1 | 1 | 0 | 1 | 0 |
| `decode_structural_partial_json` | 0 | 1 | 3 | 1 | 1 | 0 |
| `extract_complete_json_paths` | 2 | 1 | 1 | 1 | 1 | 0 |
| `extract_complete_json_typed_paths` | 0 | 1 | 1 | 0 | 0 | 0 |
| `extract_ndjson_paths` | 0 | 1 | 1 | 1 | 1 | 0 |
| `extract_ndjson_paths_native` | 0 | 1 | 1 | 0 | 0 | 0 |
| `extract_ndjson_typed_paths` | 0 | 1 | 1 | 0 | 0 | 0 |
| `extract_tuned_complete_json_paths` | 0 | 1 | 1 | 0 | 0 | 0 |
| `extract_tuned_json_paths` | 0 | 1 | 1 | 0 | 0 | 0 |
| `extract_tuned_ndjson_paths` | 1 | 1 | 1 | 0 | 0 | 0 |
| `make_complete_json_decoder` | 2 | 1 | 3 | 0 | 0 | 0 |
| `make_complete_json_typed_path_extractor` | 2 | 1 | 1 | 0 | 0 | 0 |
| `make_complete_json_view_decoder` | 1 | 1 | 1 | 0 | 1 | 0 |
| `make_json_path_extractor` | 2 | 1 | 1 | 0 | 0 | 0 |
| `make_ndjson_decoder` | 2 | 1 | 2 | 1 | 1 | 0 |
| `make_ndjson_path_extractor` | 2 | 1 | 1 | 0 | 0 | 0 |
| `make_ndjson_path_extractor_native` | 1 | 1 | 1 | 0 | 0 | 0 |
| `make_ndjson_typed_path_extractor` | 2 | 1 | 1 | 0 | 0 | 0 |
| `make_tuned_complete_json_decoder` | 0 | 1 | 2 | 1 | 1 | 0 |
| `make_tuned_complete_json_path_extractor` | 1 | 1 | 1 | 0 | 0 | 0 |
| `make_tuned_json_path_extractor` | 0 | 1 | 1 | 1 | 1 | 0 |
| `make_tuned_ndjson_decoder` | 0 | 1 | 2 | 0 | 1 | 0 |
| `make_tuned_ndjson_path_extractor` | 2 | 1 | 1 | 0 | 0 | 0 |
| `make_tuned_structural_partial_decoder` | 0 | 2 | 3 | 0 | 1 | 0 |

All exports are present in `__all__` and pinned by `tests/test_public_api.py`.
The behavior tests are concentrated in `test_decode_helpers.py`, parser tests,
and benchmark contract tests; benchmark calls live primarily in
`scripts/benchmark_parser.py`. Runtime `__version__` is 0.2.3 and the native
distribution is 0.2.2, as required for this audit baseline.

For external use, exact quoted searches were run for
`HighPerformanceStreamingJsonParser`,
`extract_tuned_complete_json_paths`, `extract_tuned_json_paths`,
`extract_ndjson_paths_native`, and `make_ndjson_path_extractor_native`, plus
combined GitHub-domain queries. The web search index returned no independent
code matches. The unauthenticated GitHub code-search API returned HTTP 401
(`Requires authentication`), and grep.app returned HTTP 429, so the code-index
coverage is incomplete. No independent public usage was found in the accessible
search results as of 2026-09-25; this is not evidence that downstream usage is
absent. That uncertainty is why no exports are removed and no warnings are
added here.

The candidate-specific repository evidence is:

- `HighPerformanceStreamingJsonParser` was imported by parser tests and
  benchmarks before this audit. Those callers now use `StreamingJsonParser`;
  the class implementation and same-object alias remain necessary internally.
- `extract_tuned_complete_json_paths` remains exercised by
  `tests/test_decode_helpers.py` and two one-shot cases in
  `scripts/benchmark_parser.py`; the chart renderer preserves its benchmark
  label. It is not used by README examples or normal recommendations.
- `extract_tuned_json_paths` is behavior-tested for both framing modes and is
  compared in complete-document and NDJSON benchmark workloads. Its dynamic
  framing dispatch is useful when framing comes from runtime configuration.
- The two `_native` path APIs are tested and used by benchmark cases to force
  the native implementation. Their user-facing behavior overlaps the generic
  path APIs; backend forcing is their only reason to remain exported.

## Canonical workflows

### Incremental parsing

Use `StreamingJsonParser` with `ParseStatus` and the documented `ParseResult`
fields. It keeps state across chunks and reports strict `EMPTY`, `PARTIAL`,
`COMPLETE`, and `INVALID` states. Use `finish()` at end of input; for NDJSON,
choose `framing="ndjson"` and drain records with `poll_many()`.

`StreamingJsonParser` is currently assigned directly to
`HighPerformanceStreamingJsonParser`; the two names are the same class and
have the same constructor and behavior. The former is the sole canonical name.
The latter remains a compatibility alias, with no deprecation warning or
removal proposed in this PR. Benchmark-only needs for subclassing or backend
control belong in implementation modules rather than making the old name a
second recommendation.

### `ParseResult` fields

Public parser methods return a result object with four observable fields:

- `status` is always one of the public `ParseStatus` values: `EMPTY`,
  `PARTIAL`, `COMPLETE`, or `INVALID`.
- `value` is `None` for `EMPTY`; for `PARTIAL`, it is the current partial value
  when one is available (NDJSON may have no partial record value); for
  `COMPLETE`, it is the completed document or NDJSON record. For `INVALID`,
  `value` is unspecified and may be absent or a best-effort partial snapshot;
  callers must not treat it as a valid parsed unit.
- `complete` is `True` exactly when `status` is `COMPLETE`, including one
  completed NDJSON record. It is `False` for `EMPTY`, `PARTIAL`, and `INVALID`.
- `error` is `None` for `EMPTY`, `PARTIAL`, and `COMPLETE`; it is a non-empty
  string for `INVALID`. Exact error wording is not stable.

The parser may return a native or Python result class. The four fields and
their semantics are the contract; concrete type identity and direct
`ParseResult` construction are implementation details, even though the
current implementations happen to allow construction. With the default
`copy_value=False`, `value` is not promised to be detached or immutable. Pass
`copy_value=True` to `feed()`, `poll()`, or `finish()` when retaining a snapshot.

The package ships PEP 561 type information in `py.typed`. Its `ParseResult`
typing contract is a read-only protocol, so callers can inspect results without
depending on the native or Python class. `value` is typed as `object | None`:
the parser supports generic JSON values, explicit typed records, and partial
snapshots, so a narrower common type would be inaccurate. Narrow it with
`ParseStatus` checks and runtime type checks before using a specific shape.
Explicit `value_type` and `record_type` arguments preserve their record type
through decoding functions and decoder factories. APIs that infer generated
records dynamically, plus view and complete-document extraction APIs that may
expose optional `simdjson` proxies, keep broad result types because their
concrete value types are not statically knowable. Extraction signatures still
preserve whether one value or a tuple/list of selected values is returned.
CI uses Pyright in strict mode against downstream examples, targeting Python
3.10, and checks one intentionally invalid call to ensure bad JSON input types
are rejected. This keeps static analysis focused on the installed public API.

### Complete JSON

- One document returning regular Python values: `decode_complete_json(data)`.
- Repeated stable workload: `make_tuned_complete_json_decoder(sample=..., payload_size_hint=...)`.
- Reusable without a representative workload: advanced `make_complete_json_decoder()`.
- View/proxy results: advanced `decode_complete_json_view()` or
  `make_complete_json_view_decoder()`; those APIs intentionally expose
  `simdjson`-style semantics and should not define the backend-agnostic path.

### NDJSON

- One payload: `decode_ndjson(data)`.
- Repeated stable workload: `make_tuned_ndjson_decoder(sample=..., payload_size_hint=...)`.
- Records arriving in chunks: `StreamingJsonParser(framing="ndjson")`.
- Explicit schemas, inferred typed records, and reusable untuned decoders remain
  advanced APIs. Typed decoding is useful but depends on `msgspec` and changes
  result types, so it is not part of the primary generic contract.

### Partial JSON

Strict incremental partial state belongs to `StreamingJsonParser` and retains
the parser's accumulated state, including unfinished string contents. Structural
partial finishing belongs to `decode_structural_partial_json(prefix)` and
`make_tuned_structural_partial_decoder(...)`: these finishers reparse the
available prefix, may omit an unfinished trailing string, and may complete
scalar prefixes differently. They express a different semantic choice, not a
backend variant of strict streaming.

### Selective extraction

- One complete document: `extract_complete_json_paths(data, *paths)`.
- One NDJSON payload: `extract_ndjson_paths(data, *paths)`.
- Repeated/stable extraction: `make_tuned_json_path_extractor(*paths,
  framing="single" or "ndjson", sample=..., payload_size_hint=...)`.

One-shot functions express framing and return projected values. Factories
preserve construction/reuse as a lifecycle choice. Typed extractors and
backend-forcing functions remain advanced or experimental; they do not need to
be learned for ordinary selective extraction.

## Overlap and backend policy

The overlapping extraction families reduce to four choices:

1. **Framing:** one complete document or NDJSON; choose the corresponding
   one-shot API or set the reusable factory's `framing`.
2. **Lifecycle:** one-shot function versus a factory reused across inputs.
3. **Schema:** generic Python values versus explicit or sample-inferred
   `msgspec` records.
4. **Backend exposure:** ordinary backend selection versus explicitly forced
   native functions.

“Tuned” names do not consistently mean measured backend calibration across all
wrappers. In particular, `extract_tuned_complete_json_paths` ignores `sample`
and uses the generic complete path factory, while the NDJSON tuned wrapper
passes workload information to its reusable factory. The primary contract
therefore names framing and lifecycle directly; the inventory preserves the
existing aliases until migration is deliberate.

The two `*_native` path functions force the optional Rust extension, can fail
when it is unavailable, and do not provide a distinct user-level framing or
result semantic. They are kept exported as **Experimental** for tests and
benchmarks. Normal callers should allow the library to choose a compatible
backend.

Typed decoding/extraction is **Advanced**. The API is valuable for callers who
already use `msgspec`, but sample-inferred schemas impose object/string-path
constraints and produce typed structs rather than ordinary dictionaries.
`decode_ndjson_adaptive` makes inference implicit and can fall back to generic
objects, so callers needing a stable result type should choose an explicit
`record_type` instead.

No `advanced` or `experimental` module namespace is proposed in this PR. The
current classification and doc page provide the needed distinction without
package-layout churn; a namespace should be considered only with a concrete
migration benefit.

## Compatibility and deprecation plan

This audit keeps all 32 exports and introduces no warnings. The migration
matrix distinguishes supported Advanced APIs from compatibility aliases,
backend-forcing Experimental APIs, and the one Internal candidate. Advanced
means supported and does not imply future deprecation.

| Current API | Current tier | Canonical replacement | 0.3 action | Earliest warning | Earliest removal |
| --- | --- | --- | --- | --- | --- |
| `decode_complete_json_view` | Advanced | `decode_complete_json` only when detached Python values are wanted; no view-equivalent replacement | Keep supported for callers choosing view/proxy semantics. | None planned. | Not planned. |
| `decode_ndjson_adaptive` | Advanced | `decode_ndjson` or explicit `record_type` when stable output types are wanted | Keep supported; retain inferred adaptive behavior. | None planned. | Not planned. |
| `extract_complete_json_typed_paths` | Advanced | `extract_complete_json_paths` for generic paths and values | Keep supported for `msgspec` typed extraction. | None planned. | Not planned. |
| `extract_ndjson_typed_paths` | Advanced | `extract_ndjson_paths` for generic records | Keep supported for typed NDJSON extraction. | None planned. | Not planned. |
| `extract_tuned_json_paths` | Advanced | `extract_complete_json_paths` / `extract_ndjson_paths` for fixed framing; `make_tuned_json_path_extractor(..., framing=...)` for reuse | Keep the runtime framing dispatcher; its dynamic framing convenience is distinct and tested. | None planned. | Not planned. |
| `extract_tuned_ndjson_paths` | Advanced | `extract_ndjson_paths` for generic one-shot extraction; unified tuned factory for repeated input | Keep supported; sample-informed one-shot selection remains available. | None planned. | Not planned. |
| `make_complete_json_decoder` | Advanced | `decode_complete_json` for one call; tuned decoder for stable repeated workloads | Keep supported as an untuned reusable decoder. | None planned. | Not planned. |
| `make_complete_json_typed_path_extractor` | Advanced | `make_tuned_json_path_extractor(..., framing="single")` when generic projected values are sufficient | Keep supported for callers who want typed records. | None planned. | Not planned. |
| `make_complete_json_view_decoder` | Advanced | `make_tuned_complete_json_decoder` only when materialized values are acceptable | Keep supported for callers choosing view/proxy semantics. | None planned. | Not planned. |
| `make_json_path_extractor` | Advanced | `make_tuned_json_path_extractor(..., framing="single")` for workload-aware selection | Keep supported as a generic reusable extractor. | None planned. | Not planned. |
| `make_ndjson_decoder` | Advanced | `decode_ndjson` for one call; tuned decoder for stable repeated workloads | Keep supported, including its explicit `record_type` option. | None planned. | Not planned. |
| `make_ndjson_path_extractor` | Advanced | `make_tuned_json_path_extractor(..., framing="ndjson")` | Keep supported as a generic reusable extractor. | None planned. | Not planned. |
| `make_ndjson_typed_path_extractor` | Advanced | Unified NDJSON tuned factory when ordinary projected values are sufficient | Keep supported for typed record projection. | None planned. | Not planned. |
| `make_tuned_complete_json_path_extractor` | Advanced | `make_tuned_json_path_extractor(..., framing="single")` | Keep supported as the framing-specific tuned factory. | None planned. | Not planned. |
| `make_tuned_ndjson_path_extractor` | Advanced | `make_tuned_json_path_extractor(..., framing="ndjson")` | Keep supported as the framing-specific tuned factory. | None planned. | Not planned. |
| `extract_ndjson_paths_native` | Experimental | `extract_ndjson_paths` unless native forcing is the explicit goal | Retain as an exported diagnostic hook for 0.3; it forces the optional native implementation. Benchmark code already imports it from the implementation module. | None; experimental status is explicit. | Reassess the top-level export no earlier than 0.4 after a renewed usage review; not scheduled. |
| `make_ndjson_path_extractor_native` | Experimental | `make_tuned_json_path_extractor(..., framing="ndjson")` unless native forcing is the explicit goal | Retain as an exported diagnostic hook for 0.3; it forces the optional native implementation. Benchmark code already imports it from the implementation module. | None; experimental status is explicit. | Reassess the top-level export no earlier than 0.4 after a renewed usage review; not scheduled. |
| `HighPerformanceStreamingJsonParser` | Compatibility | `StreamingJsonParser` | Keep the exact same class object and behavior; internal tests and benchmarks use the canonical name. | 0.4 review only; warning would require breaking the identity-preserving alias, so none is scheduled. | 1.0+ only after another usage review; not scheduled. |
| `__version__` | Compatibility | None; package metadata remains available | Keep the conventional package version export. | None planned. | Not planned. |
| `extract_tuned_complete_json_paths` | Internal candidate | `extract_complete_json_paths`; unified factory for a reused tuned workload | Keep signature and ignored-`sample` behavior; delegate to the canonical one-shot function after byte coercion. Retain direct use in the benchmark comparison and compatibility tests. | 0.4 review only after a fresh external-use check; no warning in 0.3. | 1.0+ after a warning period and another usage audit; not scheduled. |

For any future warning, first remove non-measurement internal callers so the
warning is attributable to callers who directly choose the compatibility API.
Use `DeprecationWarning` with `stacklevel=2`; do not warn on import. Do not
remove an export before 1.0 without a separate compatibility decision and
evidence supporting that break.

## Public contract test and signature review

`tests/test_public_api.py` pins the exact `__all__` set, checks every listed
name resolves, and verifies that `StreamingJsonParser` and
`HighPerformanceStreamingJsonParser` remain the same class object. Deliberate
surface changes must update both the test and this inventory. The test protects
the contract without freezing internal module layout or backend choice.

The current signatures consistently accept `str | bytes | bytearray` for
payloads. Differences to resolve before or during consolidation:

- The implementation still uses `Any` for backend-selected internal values;
  the installed package stubs now give decoder and extractor factories
  callable return types and preserve single/multiple path result shapes.
- Explicit `value_type` and `record_type` arguments preserve their class type
  through decoder helpers. Sample-inferred typed path extractors retain broad
  selected-value types because their generated record classes are dynamic.
- Generic paths accept `str | int` segments, while typed paths accept only
  string segments and enforce identifier-safe names.
- `decode_complete_json` calls the schema argument `value_type`, while NDJSON
  uses `record_type`; parser constructor options add the same split.
- `sample` and `payload_size_hint` are not consistent across the family-specific
  and unified factory signatures. Most notably, one-shot
  `extract_tuned_complete_json_paths` accepts but ignores `sample`.
- `framing` is available on the unified path APIs but omitted from
  framing-specific factories. This is reasonable for semantic clarity, but
  should be stated consistently in their docstrings.

These are contract-review findings, not grounds for breaking signature changes
under 0.2.x. Aside from this documentation, the 0.3 proposal makes no backend,
performance, benchmark, or package-version changes.

## Current 0.3 direction

| Question | Proposed answer |
| --- | --- |
| Canonical incremental parser? | `StreamingJsonParser`; `HighPerformanceStreamingJsonParser` is a compatibility alias. |
| One complete document? | `decode_complete_json`. |
| Repeated complete-document workload? | `make_tuned_complete_json_decoder`; use its default materialized Python-value mode. |
| Complete-document view semantics? | Advanced `decode_complete_json_view` / `make_complete_json_view_decoder`. |
| One NDJSON payload? | `decode_ndjson`. |
| Repeated NDJSON workload? | `make_tuned_ndjson_decoder`. |
| Streaming NDJSON? | `StreamingJsonParser(framing="ndjson")`. |
| Strict partial state vs structural finishing? | Persistent strict state uses `StreamingJsonParser`; prefix reparsing uses `decode_structural_partial_json` or its tuned factory and may omit unfinished strings. |
| Selective extraction one-shot and reusable? | `extract_complete_json_paths` / `extract_ndjson_paths`; reusable `make_tuned_json_path_extractor(..., framing=...)`. |
| Typed decoding? | Advanced, with explicit `msgspec` dependency/schema behavior. |
| Direct native/backend forcing? | No for normal users; retain the two native path exports as experimental benchmark/test hooks. |
| Names kept for compatibility? | Keep `HighPerformanceStreamingJsonParser`, `extract_tuned_json_paths`, and `__version__`; review `extract_tuned_complete_json_paths` for staged deprecation. |

## Recommended next implementation PR

The public API contract, compatibility dispositions, and PEP 561 typing are
now documented and tested. The next PR should focus on linting and coverage
infrastructure around the stabilized API; it should not reopen API-tier or
signature design without new compatibility evidence.
