# streaming-json-parser-native

Optional Rust acceleration for the `streaming-json-parser` Python package.

Once the native distribution has been published, install the Python package and
native extension with:

```bash
python -m pip install streaming-json-parser streaming-json-parser-native
```

Version 0.2.0 provides a prebuilt wheel only for CPython 3.12 on Linux x86_64.
CI builds macOS arm64 wheels for CPython 3.10 through 3.14; they will be
published with a future native package release. Until then, pip builds from the
source distribution on macOS, which requires Rust 1.83 or newer. The Python
package works without the native extension.

To build and install the extension from this checkout, activate a Python
virtual environment and run these commands from the repository root:

```bash
python -m pip install -e '.[native-build]'
cd rust_native
maturin develop --release
```

Building the extension requires Rust 1.83 or newer.
