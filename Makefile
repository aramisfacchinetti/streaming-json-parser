.PHONY: help benchmark-artifacts verify-benchmark-artifacts benchmark-community-corpus benchmark-release-artifacts verify-release-benchmark-artifacts verify-community-benchmark-artifacts benchmark-strategy benchmark-ndjson benchmark-partial benchmark-partial-matrix native-wheel native-install

help:
	@printf '%s\n' 'Available targets:'
	@printf '%s\n' '  make benchmark-artifacts        Regenerate benchmark snapshot, scorecard, and SVG charts'
	@printf '%s\n' '  make verify-benchmark-artifacts Verify generated reports and charts against the snapshot and current measurements'
	@printf '%s\n' '  make benchmark-community-corpus Run the TkTech complete-load corpus (set COMMUNITY_JSON_CORPUS_DIR)'
	@printf '%s\n' '  make benchmark-release-artifacts Generate all release benchmarks from a clean tree and installed packages'
	@printf '%s\n' '  make verify-release-benchmark-artifacts Verify all release benchmarks using installed packages'
	@printf '%s\n' '  make verify-community-benchmark-artifacts Verify the saved community corpus report and chart'
	@printf '%s\n' '  make benchmark-strategy       Compare complete-document backend strategies'
	@printf '%s\n' '  make benchmark-ndjson         Compare strict NDJSON backend strategies'
	@printf '%s\n' '  make benchmark-partial          Compare true incremental and partial JSON finishers'
	@printf '%s\n' '  make benchmark-partial-matrix   Compare partial strategies across shapes and chunk sizes'
	@printf '%s\n' '  make native-wheel               Build the optional Rust incremental backend wheel'
	@printf '%s\n' '  make native-install             Build and install the optional Rust incremental backend'

benchmark-artifacts:
	python scripts/benchmark_parser.py --artifacts

verify-benchmark-artifacts:
	python scripts/benchmark_parser.py --verify-artifacts

benchmark-community-corpus:
	@if [ -z "$(COMMUNITY_JSON_CORPUS_DIR)" ]; then echo 'Set COMMUNITY_JSON_CORPUS_DIR to TkTech/json_benchmark/data'; exit 2; fi
	python scripts/benchmark_community_corpus.py --corpus-dir "$(COMMUNITY_JSON_CORPUS_DIR)" --output-dir docs

benchmark-release-artifacts:
	@if [ -z "$(COMMUNITY_JSON_CORPUS_DIR)" ]; then echo 'Set COMMUNITY_JSON_CORPUS_DIR to TkTech/json_benchmark/data'; exit 2; fi
	python scripts/benchmark_release_artifacts.py --corpus-dir "$(COMMUNITY_JSON_CORPUS_DIR)"

verify-release-benchmark-artifacts:
	@if [ -z "$(COMMUNITY_JSON_CORPUS_DIR)" ]; then echo 'Set COMMUNITY_JSON_CORPUS_DIR to TkTech/json_benchmark/data'; exit 2; fi
	@resolved_corpus_dir="$$(cd "$(COMMUNITY_JSON_CORPUS_DIR)" && pwd -P)"; \
	BENCHMARK_USE_INSTALLED_PACKAGE=1 BENCHMARK_ARTIFACT_COMMAND="make benchmark-release-artifacts COMMUNITY_JSON_CORPUS_DIR=$$resolved_corpus_dir" python scripts/benchmark_parser.py --verify-artifacts
	python scripts/benchmark_community_corpus.py --verify --output-dir docs

verify-community-benchmark-artifacts:
	python scripts/benchmark_community_corpus.py --verify --output-dir docs

benchmark-strategy:
	python scripts/benchmark_strategy_matrix.py --format markdown

benchmark-ndjson:
	python scripts/benchmark_ndjson_strategy_matrix.py --format markdown

benchmark-partial:
	python scripts/benchmark_partial_parser.py

benchmark-partial-matrix:
	python scripts/benchmark_partial_strategy_matrix.py

native-wheel:
	maturin build --release --manifest-path rust_native/Cargo.toml

native-install: native-wheel
	python -m pip install --force-reinstall rust_native/target/wheels/*.whl
