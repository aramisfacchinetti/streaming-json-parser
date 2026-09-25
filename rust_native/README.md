# streaming-json-parser-native

Optional Rust acceleration for the `streaming-json-parser` Python package.

Once the native distribution has been published, install the Python package and
native extension with:

```bash
python -m pip install streaming-json-parser streaming-json-parser-native
```

Version 0.2.2 provides ABI-stable wheels for GIL-enabled CPython 3.10 and newer
on Linux x86_64 and arm64 (manylinux2014), Windows x86_64, and macOS arm64
(macOS 11 or newer). Each platform and architecture uses one wheel across
supported CPython versions. On other platforms or architectures, pip builds
from the source distribution, which requires Rust 1.83 or newer. The Python
package works without the native extension.

To build and install the extension from this checkout, activate a Python
virtual environment and run these commands from the repository root:

```bash
python -m pip install -e '.[native-build]'
cd rust_native
maturin develop --release
```

Building the extension requires Rust 1.83 or newer.
