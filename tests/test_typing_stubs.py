import ast
from pathlib import Path

import streaming_json_parser
import streaming_json_parser.high_performance_parser as implementation

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "streaming_json_parser"


def test_package_stub_exports_match_runtime_public_api():
    stub = ast.parse((PACKAGE_DIR / "__init__.pyi").read_text())
    stub_exports = None
    declared_names = set()

    for node in stub.body:
        if isinstance(node, ast.ImportFrom):
            declared_names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            declared_names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
                stub_exports = ast.literal_eval(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    declared_names.add(target.id)

    assert stub_exports is not None
    assert set(stub_exports) == set(streaming_json_parser.__all__)
    assert set(stub_exports) <= declared_names


def test_implementation_stub_declares_only_runtime_public_symbols():
    stub = ast.parse((PACKAGE_DIR / "high_performance_parser.pyi").read_text())
    declared_public_names = {
        node.name
        for node in stub.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        and not node.name.startswith("_")
    }

    assert declared_public_names
    assert all(hasattr(implementation, name) for name in declared_public_names)


def test_canonical_parser_stub_is_the_compatibility_alias():
    stub = ast.parse((PACKAGE_DIR / "__init__.pyi").read_text())
    alias = next(
        node
        for node in stub.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "StreamingJsonParser"
            for target in node.targets
        )
    )
    assert isinstance(alias.value, ast.Name)
    assert alias.value.id == "HighPerformanceStreamingJsonParser"
