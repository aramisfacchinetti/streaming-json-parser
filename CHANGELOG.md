# Changelog

## Unreleased

## Native package 0.2.3 - 2026-10-02

- Refresh the locked parser dependencies to `sonic-rs 0.5.10` and compatible `sonic-number 0.1.3`.

## 0.3.0 - 2026-09-29

- Added PEP 561 typing with `py.typed`, package-owned stubs, and a type-complete public API, including useful generic and overloaded decoder/extractor interfaces.
- Stabilized the documented 32-export API contract, tiers, canonical `StreamingJsonParser` name, complete/NDJSON/selective extraction guidance, and observable `ParseResult` fields while retaining compatibility, experimental, and internal-candidate exports.
- Linked the public API guide from the README with a stable URL that also works on PyPI.

## 0.2.3 - 2026-09-25

- Strict Python fallback and standard-library complete/NDJSON decoding now reject numeric overflow such as `1e400` instead of returning a non-finite float, aligning those paths with the native strict parser.

## 0.2.2 - 2026-09-24

- Updated README links so the PyPI project page can render its documentation and benchmark images.
- Synchronized the public `__version__` attribute with the 0.2.2 core distribution.
- Refreshed benchmark provenance for core 0.2.2 with native 0.2.1.

## 0.2.1 - 2026-09-24

- Fixed complete JSON decoding for non-ASCII Unicode escapes when the optional `yyjson` backend is installed.

## 0.2.0 - 2026-09-22

- Added strict incremental parsing with explicit `EMPTY`, `PARTIAL`, `COMPLETE`, and `INVALID` results.
- Added complete-document, NDJSON, structural partial, typed, and selective extraction APIs.
- Added workload-aware backend selection and an optional Rust acceleration package.
- Replaced the permissive pre-0.2 `StreamingJsonParser` with the strict incremental parser.
- Added release packaging, benchmark artifacts, and public API documentation.
