# Changelog

## 0.2.0 - 2026-09-22

- Added strict incremental parsing with explicit `EMPTY`, `PARTIAL`, `COMPLETE`, and `INVALID` results.
- Added complete-document, NDJSON, structural partial, typed, and selective extraction APIs.
- Added workload-aware backend selection and an optional Rust acceleration package.
- Replaced the permissive pre-0.2 `StreamingJsonParser` with the strict incremental parser.
- Added release packaging, benchmark artifacts, and public API documentation.
