import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_release_artifacts.py"
MODULE_SPEC = importlib.util.spec_from_file_location("release_benchmark_artifacts_for_tests", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
release_benchmark = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(release_benchmark)


def test_release_guard_rejects_tracked_and_untracked_changes(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=" M README.md\n?? docs/new-report.json\n")

    monkeypatch.setattr(release_benchmark.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="requires a clean Git working tree") as error:
        release_benchmark._require_clean_tree(tmp_path)

    assert "README.md" in str(error.value)
    assert "docs/new-report.json" in str(error.value)
    assert calls[0][0] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]


def test_release_guard_returns_revision_for_a_clean_tree(monkeypatch, tmp_path):
    responses = iter((SimpleNamespace(stdout=""), SimpleNamespace(stdout="abc123\n")))
    monkeypatch.setattr(release_benchmark.subprocess, "run", lambda *_args, **_kwargs: next(responses))

    assert release_benchmark._require_clean_tree(tmp_path) == "abc123"


def test_release_version_check_accepts_core_and_community_metadata_shapes():
    core_version = release_benchmark._project_version(release_benchmark.REPO_ROOT / "pyproject.toml")
    native_version = release_benchmark._project_version(
        release_benchmark.REPO_ROOT / "rust_native" / "pyproject.toml"
    )
    core_environment = {
        "installed_distribution_version": core_version,
        "package_module_version": core_version,
        "package_source": "installed distribution",
        "native_extension": {"version": native_version, "importable": True},
    }
    community_environment = {
        "installed_distribution_version": core_version,
        "package_module_version": core_version,
        "package_source": "installed distribution",
        "native_extension_version": native_version,
        "native_extension_importable": True,
    }

    release_benchmark._require_release_versions(
        {"environment": core_environment},
        {"environment": community_environment},
    )
