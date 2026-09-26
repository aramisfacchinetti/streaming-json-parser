# Contributing

## Development setup

```bash
python -m pip install -e '.[test,typecheck,quality]'
```

The optional benchmark and native workflows are documented in the main
[README](README.md). Keep changes focused, preserve strict parser semantics,
and add a regression test for behavior changes.

## Python quality checks

Run the focused checks with:

```bash
make lint
make typecheck
make test
make coverage
```

`make check` runs linting, both typing checks, and the full test suite with
branch coverage. The authoritative coverage job uses Python 3.12 and the
`test` and `quality` extras. It installs the optional test backends declared by
`test` and omits the separate `accelerated`, `benchmark`, and native extras, so
coverage does not depend on a developer's global environment. Coverage
measures the shipped Python package; it does not combine Rust coverage with
Python coverage.

Before opening a pull request, run `make check`, then:

```bash
python -m compileall -q src tests scripts
git diff --check
```

For packaging changes, also run `python -m build` and `python -m twine check
dist/*`.
