## Summary

<!-- What changes, and why? -->

## Motivation / context

<!-- What user problem or maintenance need does this address? -->

## Behavior and API impact

<!-- Describe runtime or public API effects, or state that there are none. -->

## Verification

<!-- List commands and results. For native changes, the existing native CI is authoritative. -->

## Checklist

- [ ] Tests are added or updated when behavior changes.
- [ ] User-facing documentation is updated when behavior changes; public export changes are described in `docs/public-api.md`.
- [ ] `make check` passes, or any limitations are explained above.
- [ ] For packaging changes, `python -m build` and `python -m twine check dist/*` pass.
- [ ] Benchmark artifacts change only for an intentional methodology or result update.
- [ ] Package version changes are limited to an intentional release PR.
