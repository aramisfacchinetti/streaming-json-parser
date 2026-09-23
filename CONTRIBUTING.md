# Contributing

## Development setup

```bash
python -m pip install -e '.[test]'
pytest
```

The optional benchmark and native workflows are documented in the main
[README](README.md). Keep changes focused, preserve strict parser semantics,
and add a regression test for behavior changes.

Before opening a pull request, run:

```bash
python -m pytest -q
python -m compileall -q src tests scripts
git diff --check
```

For packaging changes, also run `python -m build` and `python -m twine check
dist/*`.
