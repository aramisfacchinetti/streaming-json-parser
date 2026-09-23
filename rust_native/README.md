# streaming-json-parser-native

Optional Rust acceleration for the `streaming-json-parser` Python package.

Prebuilt native wheels are not currently published. The Python facade works
without the extension. To build and install it from this checkout, activate a
Python virtual environment and run these commands from the repository root:

```bash
python -m pip install -e '.[native-build]'
cd rust_native
maturin develop --release
```

Building the extension requires Rust 1.83 or newer.
