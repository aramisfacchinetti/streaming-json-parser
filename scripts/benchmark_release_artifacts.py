#!/usr/bin/env python3
"""Generate published benchmark artifacts from a clean installed release."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
DOCS_ROOT = REPO_ROOT / "docs"


def _git_status(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _require_clean_tree(repo_root: Path) -> str:
    status = _git_status(repo_root)
    if status.strip():
        changed_paths = "\n".join(f"  {line}" for line in status.splitlines())
        raise RuntimeError(
            "Release benchmark generation requires a clean Git working tree. "
            "Commit, stash, or remove these changes before retrying:\n" + changed_paths
        )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not revision:
        raise RuntimeError("Could not determine the source revision for release benchmarks")
    return revision


def _project_version(pyproject_path: Path) -> str:
    in_project_section = False
    for line in pyproject_path.read_text().splitlines():
        section = re.fullmatch(r"\s*\[([^]]+)\]\s*", line)
        if section:
            in_project_section = section.group(1) == "project"
            continue
        if in_project_section:
            version = re.fullmatch(r"\s*version\s*=\s*['\"]([^'\"]+)['\"]\s*", line)
            if version:
                return version.group(1)
    raise RuntimeError(f"Could not read [project].version from {pyproject_path}")


def _require_release_versions(
    core_snapshot: dict[str, object],
    community_snapshot: dict[str, object],
    incremental_snapshot: dict[str, object],
) -> None:
    core_environment = core_snapshot["environment"]
    community_environment = community_snapshot["environment"]
    incremental_environment = incremental_snapshot["environment"]
    expected_core = _project_version(REPO_ROOT / "pyproject.toml")
    expected_native = _project_version(REPO_ROOT / "rust_native" / "pyproject.toml")

    for label, environment in (
        ("core benchmark", core_environment),
        ("community benchmark", community_environment),
        ("strict incremental benchmark", incremental_environment),
    ):
        core_version = environment.get("installed_distribution_version")
        if core_version != expected_core:
            raise RuntimeError(
                f"{label} requires installed streaming-json-parser {expected_core}; "
                f"found {core_version or 'not installed'}"
            )
        native = environment.get("native_extension")
        if native is not None:
            native_version = native.get("version", native.get("distribution_version"))
            native_importable = native.get("importable")
        else:
            native_version = environment.get("native_extension_version")
            native_importable = environment.get("native_extension_importable")
        if native_version != expected_native or native_importable is not True:
            raise RuntimeError(
                f"{label} requires importable streaming-json-parser-native {expected_native}; "
                f"found {native_version or 'not installed'} "
                f"(importable: {native_importable is True})"
            )
        if environment.get("package_source") != "installed distribution":
            raise RuntimeError(f"{label} did not import the installed core distribution")

    core_module_version = core_environment.get("package_module_version")
    community_module_version = community_environment.get("package_module_version")
    if core_module_version != community_module_version:
        raise RuntimeError("Core and community benchmarks imported different module versions")
    if core_module_version != incremental_environment.get("package_module_version"):
        raise RuntimeError("Core and strict incremental benchmarks imported different module versions")
    native = incremental_environment.get("native_extension", {})
    if native.get("abi3_binary") is not True:
        raise RuntimeError("Strict incremental release benchmark did not import an ABI3 native binary")
    if incremental_snapshot.get("semantics_family") != "strict_incremental":
        raise RuntimeError("Strict incremental release benchmark mixed semantic families")
    if community_snapshot.get("methodology", {}).get("clock") != "time.perf_counter":
        raise RuntimeError("Community benchmark must use time.perf_counter elapsed wall-clock timing")
    if incremental_snapshot.get("methodology", {}).get("clock") != "time.perf_counter":
        raise RuntimeError("Strict incremental benchmark must use time.perf_counter elapsed wall-clock timing")


def _verify_current_release_artifacts(docs_root: Path) -> None:
    expected_core = _project_version(REPO_ROOT / "pyproject.toml")
    expected_native = _project_version(REPO_ROOT / "rust_native" / "pyproject.toml")
    current_core = importlib.metadata.version("streaming-json-parser")
    current_native = importlib.metadata.version("streaming-json-parser-native")
    if current_core != expected_core or current_native != expected_native:
        raise RuntimeError(
            "Release benchmark verification requires installed core/native distributions "
            f"{expected_core}/{expected_native}; found {current_core}/{current_native}"
        )
    core_distribution = importlib.metadata.distribution("streaming-json-parser")
    native_distribution = importlib.metadata.distribution("streaming-json-parser-native")
    core_module = importlib.import_module("streaming_json_parser")
    native_package = importlib.import_module("streaming_json_parser_native")
    native_binary = importlib.import_module(
        "streaming_json_parser_native.streaming_json_parser_native"
    )
    if Path(core_module.__file__).resolve() != Path(
        core_distribution.locate_file("streaming_json_parser/__init__.py")
    ).resolve():
        raise RuntimeError("Release benchmark verification imported core outside its installed distribution")
    packaged_native_files = {
        Path(native_distribution.locate_file(entry)).resolve()
        for entry in (native_distribution.files or ())
    }
    if (
        Path(native_package.__file__).resolve() not in packaged_native_files
        or Path(native_binary.__file__).resolve() not in packaged_native_files
    ):
        raise RuntimeError(
            "Release benchmark verification imported the native binary outside its installed distribution"
        )

    snapshots = {
        "core": json.loads((docs_root / "benchmark-snapshot.json").read_text()),
        "community": json.loads((docs_root / "community-json-benchmark.json").read_text()),
        "incremental": json.loads((docs_root / "incremental-benchmark.json").read_text()),
    }
    provenance = []
    for name, snapshot in snapshots.items():
        environment = snapshot.get("environment", {})
        if environment.get("installed_distribution_version") != expected_core:
            raise RuntimeError(f"{name} benchmark has stale core package provenance")
        if environment.get("package_source") != "installed distribution":
            raise RuntimeError(f"{name} benchmark was not generated from the installed core distribution")
        if environment.get("package_module_version") != expected_core:
            raise RuntimeError(f"{name} benchmark has stale core module provenance")
        native = environment.get("native_extension", {})
        if name == "community":
            native_version = environment.get("native_extension_version")
            native_importable = environment.get("native_extension_importable")
        else:
            native_version = native.get("version", native.get("distribution_version"))
            native_importable = native.get("importable")
        if native_version != expected_native or native_importable is not True:
            raise RuntimeError(f"{name} benchmark has stale native package provenance")
        revision = environment.get("commit_sha", environment.get("source_revision"))
        if not revision or environment.get("working_tree_dirty") is not False:
            raise RuntimeError(f"{name} benchmark lacks clean source revision provenance")
        provenance.append(revision)
    if len(set(provenance)) != 1:
        raise RuntimeError("Release benchmark snapshots record different source revisions")
    comparison = json.loads(
        (docs_root / "abi3-incremental-investigation.json").read_text()
    )
    # This dated ABI-mode study is a historical development comparison. Keep
    # its recorded core version intact while requiring the unchanged native
    # package and its own source provenance to remain present.
    if (
        not comparison.get("core_distribution_version")
        or comparison.get("native_distribution_version") != expected_native
        or not comparison.get("source_revision")
    ):
        raise RuntimeError("ABI3 investigation has missing or stale provenance")
    if snapshots["incremental"]["environment"]["native_extension"].get("abi3_binary") is not True:
        raise RuntimeError("Incremental release snapshot does not record an ABI3 binary")
    if snapshots["incremental"].get("semantics_family") != "strict_incremental":
        raise RuntimeError("Incremental release snapshot mixed semantic families")
    if snapshots["incremental"].get("methodology", {}).get("clock") != "time.perf_counter":
        raise RuntimeError("Incremental release snapshot does not record elapsed wall-clock timing")
    if snapshots["community"].get("methodology", {}).get("clock") != "time.perf_counter":
        raise RuntimeError("Community JSON snapshot does not record elapsed wall-clock timing")
    community_report = (docs_root / "community-json-benchmark.md").read_text()
    if "process CPU time" in community_report or "CPU ms/load" in community_report:
        raise RuntimeError("Community JSON report contains stale process-CPU timing labels")


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.verify:
        _verify_current_release_artifacts(DOCS_ROOT)
        print("release benchmark versions and methodology are current")
        return 0
    if args.corpus_dir is None:
        parser.error("--corpus-dir is required unless --verify is used")

    corpus_dir = args.corpus_dir.expanduser().resolve()
    if not corpus_dir.is_dir():
        parser.error(f"corpus directory does not exist: {corpus_dir}")

    revision = _require_clean_tree(REPO_ROOT)
    try:
        core_version = importlib.metadata.version("streaming-json-parser")
        native_version = importlib.metadata.version("streaming-json-parser-native")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "Release benchmark generation requires installed core and native distributions"
        ) from exc

    release_command = (
        "make benchmark-release-artifacts "
        f"COMMUNITY_JSON_CORPUS_DIR={shlex.quote(str(corpus_dir))}"
    )
    os.environ["BENCHMARK_USE_INSTALLED_PACKAGE"] = "1"
    os.environ["BENCHMARK_ARTIFACT_COMMAND"] = release_command
    if str(SCRIPTS_ROOT) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_ROOT))

    import benchmark_community_corpus
    import benchmark_incremental
    import benchmark_parser

    core_snapshot = benchmark_parser.collect_current_snapshot()
    community_snapshot = benchmark_community_corpus.collect_snapshot(corpus_dir)
    incremental_snapshot = benchmark_incremental.collect_snapshot()
    _require_release_versions(core_snapshot, community_snapshot, incremental_snapshot)

    for snapshot_name, environment in (
        ("core", core_snapshot["environment"]),
        ("community", community_snapshot["environment"]),
        ("strict incremental", incremental_snapshot["environment"]),
    ):
        if environment.get("working_tree_dirty") is not False:
            raise RuntimeError(f"{snapshot_name} benchmark did not observe a clean working tree")
        if environment.get("commit_sha", environment.get("source_revision")) != revision:
            raise RuntimeError(f"{snapshot_name} benchmark observed a different source revision")

    if _require_clean_tree(REPO_ROOT) != revision:
        raise RuntimeError("Source revision changed while collecting release benchmark measurements")

    core_paths = benchmark_parser.write_artifact_bundle(DOCS_ROOT, core_snapshot)
    community_paths = benchmark_community_corpus.write_artifacts(community_snapshot, DOCS_ROOT)
    incremental_paths = benchmark_incremental.write_artifacts(incremental_snapshot, DOCS_ROOT)
    print(f"Generated release benchmarks with core {core_version} and native {native_version}.")
    print(f"Source revision: {revision}")
    for path in (*core_paths.values(), *community_paths.values(), *incremental_paths):
        print(path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
