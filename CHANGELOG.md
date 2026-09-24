# Changelog

## Unreleased

## 0.2.2 - 2026-09-24

- Updated README links so the PyPI project page can render its documentation and benchmark images.
- Refreshed benchmark provenance for core 0.2.2 with native 0.2.1.

## 0.2.1 - 2026-09-24

- Fixed complete JSON decoding for non-ASCII Unicode escapes when the optional `yyjson` backend is installed.

## 0.2.0 - 2026-09-22

- Added strict incremental parsing with explicit `EMPTY`, `PARTIAL`, `COMPLETE`, and `INVALID` results.
- Added complete-document, NDJSON, structural partial, typed, and selective extraction APIs.
- Added workload-aware backend selection and an optional Rust acceleration package.
- Replaced the permissive pre-0.2 `StreamingJsonParser` with the strict incremental parser.
- Added release packaging, benchmark artifacts, and public API documentation.
