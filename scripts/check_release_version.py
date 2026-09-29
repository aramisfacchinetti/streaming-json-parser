"""Validate the published core release tag against its built artifacts."""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tarfile
from email.parser import BytesParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile

_CORE_RELEASE_TAG = re.compile(
    r"v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))"
)


def version_from_tag(tag: str) -> str:
    match = _CORE_RELEASE_TAG.fullmatch(tag)
    if match is None:
        raise ValueError(f"expected a core release tag in vX.Y.Z form; got {tag!r}")
    return match.group(1)


def distribution_versions(dist_dir: Path) -> tuple[str, str]:
    wheels = sorted(dist_dir.glob("streaming_json_parser-*.whl"))
    sdists = sorted(dist_dir.glob("streaming_json_parser-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError(
            "expected exactly one streaming_json_parser wheel and one sdist in "
            f"{dist_dir}; found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
        )

    with ZipFile(wheels[0]) as wheel:
        metadata_paths = [
            name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError(f"expected one wheel METADATA file in {wheels[0].name}")
        wheel_metadata = BytesParser().parsebytes(wheel.read(metadata_paths[0]))

    with tarfile.open(sdists[0], "r:gz") as sdist:
        metadata_members = [
            member
            for member in sdist.getmembers()
            if member.isfile()
            and member.name.count("/") == 1
            and member.name.endswith("/PKG-INFO")
        ]
        if len(metadata_members) != 1:
            raise ValueError(f"expected one sdist PKG-INFO file in {sdists[0].name}")
        metadata_file = sdist.extractfile(metadata_members[0])
        if metadata_file is None:
            raise ValueError(f"could not read PKG-INFO from {sdists[0].name}")
        sdist_metadata = BytesParser().parsebytes(metadata_file.read())

    wheel_version = wheel_metadata.get("Version")
    sdist_version = sdist_metadata.get("Version")
    if not wheel_version or not sdist_version:
        raise ValueError("built distribution metadata is missing its Version field")
    return wheel_version, sdist_version


def module_version(source_file: Path) -> str:
    module = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    values: list[object] = []
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            values.append(ast.literal_eval(statement.value))
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "__version__"
            and statement.value is not None
        ):
            values.append(ast.literal_eval(statement.value))

    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError(f"expected one literal string __version__ in {source_file}")
    return values[0]


def validate_versions(
    tag: str, wheel_version: str, sdist_version: str, runtime_version: str
) -> str:
    tag_version = version_from_tag(tag)
    if wheel_version != sdist_version:
        raise ValueError(
            f"release tag {tag!r}: wheel metadata version {wheel_version!r} "
            f"does not match sdist metadata version {sdist_version!r}"
        )
    if tag_version != wheel_version:
        raise ValueError(
            f"release tag {tag!r} resolves to {tag_version!r}, but built package "
            f"metadata version is {wheel_version!r}"
        )
    if runtime_version != wheel_version:
        raise ValueError(
            f"release tag {tag!r} and built package metadata resolve to "
            f"{wheel_version!r}, but streaming_json_parser.__version__ is "
            f"{runtime_version!r}"
        )
    return tag_version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="GitHub release tag (expected vX.Y.Z)")
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--source-file",
        type=Path,
        default=Path("src/streaming_json_parser/__init__.py"),
    )
    args = parser.parse_args()

    try:
        version_from_tag(args.tag)
        wheel_version, sdist_version = distribution_versions(args.dist_dir)
        runtime_version = module_version(args.source_file)
        version = validate_versions(
            args.tag, wheel_version, sdist_version, runtime_version
        )
    except (OSError, ValueError, tarfile.TarError, BadZipFile) as error:
        print(f"release version validation failed: {error}", file=sys.stderr)
        return 1

    print(
        f"Release tag {args.tag} matches wheel/sdist metadata and "
        f"streaming_json_parser.__version__ ({version})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
