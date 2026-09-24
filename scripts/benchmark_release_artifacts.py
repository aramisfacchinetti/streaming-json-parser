#!/usr/bin/env python3
"""Generate published benchmark artifacts from a clean installed release."""

from __future__ import annotations

import argparse
import importlib.metadata
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
    core_snapshot: dict[str, object], community_snapshot: dict[str, object]
) -> None:
    core_environment = core_snapshot["environment"]
    community_environment = community_snapshot["environment"]
    expected_core = _project_version(REPO_ROOT / "pyproject.toml")
    expected_native = _project_version(REPO_ROOT / "rust_native" / "pyproject.toml")

    for label, environment in (
        ("core benchmark", core_environment),
        ("community benchmark", community_environment),
    ):
        core_version = environment.get("installed_distribution_version")
        if core_version != expected_core:
            raise RuntimeError(
                f"{label} requires installed streaming-json-parser {expected_core}; "
                f"found {core_version or 'not installed'}"
            )
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


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    args = parser.parse_args()

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
    import benchmark_parser

    core_snapshot = benchmark_parser.collect_current_snapshot()
    community_snapshot = benchmark_community_corpus.collect_snapshot(corpus_dir)
    _require_release_versions(core_snapshot, community_snapshot)

    for snapshot_name, environment in (
        ("core", core_snapshot["environment"]),
        ("community", community_snapshot["environment"]),
    ):
        if environment.get("working_tree_dirty") is not False:
            raise RuntimeError(f"{snapshot_name} benchmark did not observe a clean working tree")
        if environment.get("commit_sha", environment.get("source_revision")) != revision:
            raise RuntimeError(f"{snapshot_name} benchmark observed a different source revision")

    if _require_clean_tree(REPO_ROOT) != revision:
        raise RuntimeError("Source revision changed while collecting release benchmark measurements")

    core_paths = benchmark_parser.write_artifact_bundle(DOCS_ROOT, core_snapshot)
    community_paths = benchmark_community_corpus.write_artifacts(community_snapshot, DOCS_ROOT)
    print(f"Generated release benchmarks with core {core_version} and native {native_version}.")
    print(f"Source revision: {revision}")
    for path in (*core_paths.values(), *community_paths.values()):
        print(path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
