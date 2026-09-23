.PHONY: help benchmark-artifacts verify-benchmark-artifacts benchmark-strategy benchmark-ndjson benchmark-partial benchmark-partial-matrix native-wheel native-install

help:
	@printf '%s\n' 'Available targets:'
	@printf '%s\n' '  make benchmark-artifacts        Regenerate benchmark snapshot and scorecard artifacts'
	@printf '%s\n' '  make verify-benchmark-artifacts Verify generated artifacts against current measurements'
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
