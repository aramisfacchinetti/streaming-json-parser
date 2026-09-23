# streaming-json-parser-native

Optional Rust acceleration for the `streaming-json-parser` Python package.

Once the native distribution has been published, install the Python package and
native extension with:

```bash
python -m pip install streaming-json-parser streaming-json-parser-native
```

Version 0.2.1 provides a prebuilt wheel for CPython 3.12 on Linux x86_64 and
for CPython 3.10 through 3.14 on macOS arm64. For other Python versions or
platforms, pip builds from the source distribution, which requires Rust 1.83 or
newer. The Python package works without the native extension.

To build and install the extension from this checkout, activate a Python
virtual environment and run these commands from the repository root:

```bash
python -m pip install -e '.[native-build]'
cd rust_native
maturin develop --release
```

Building the extension requires Rust 1.83 or newer.
