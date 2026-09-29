import io
import tarfile
import zipfile

import pytest

from scripts.check_release_version import (
    distribution_versions,
    validate_versions,
    version_from_tag,
)


def test_release_tag_requires_v_prefixed_numeric_triplet():
    assert version_from_tag("v0.3.0") == "0.3.0"

    for tag in ("0.3.0", "vv0.3.0", "v0.3", "v0.3.0-rc1"):
        with pytest.raises(ValueError, match="expected a core release tag in vX.Y.Z form"):
            version_from_tag(tag)


def test_release_tag_and_distribution_versions_must_match():
    assert validate_versions("v0.3.0", "0.3.0", "0.3.0", "0.3.0") == "0.3.0"

    with pytest.raises(ValueError, match="tag 'v0.3.1'.*metadata version is '0.3.0'"):
        validate_versions("v0.3.1", "0.3.0", "0.3.0", "0.3.0")


def test_runtime_version_must_match_distribution_metadata():
    with pytest.raises(ValueError, match="__version__ is '0.2.3'"):
        validate_versions("v0.3.0", "0.3.0", "0.3.0", "0.2.3")


def test_wheel_and_sdist_versions_must_match():
    with pytest.raises(ValueError, match="wheel metadata version '0.3.0'.*sdist metadata version '0.3.1'"):
        validate_versions("v0.3.0", "0.3.0", "0.3.1", "0.3.0")


def test_distribution_versions_reads_top_level_sdist_metadata(tmp_path):
    metadata = b"Metadata-Version: 2.1\nName: streaming-json-parser\nVersion: 0.3.0\n\n"
    wheel_path = tmp_path / "streaming_json_parser-0.3.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr("streaming_json_parser-0.3.0.dist-info/METADATA", metadata)

    sdist_path = tmp_path / "streaming_json_parser-0.3.0.tar.gz"
    with tarfile.open(sdist_path, "w:gz") as sdist:
        for name in (
            "streaming_json_parser-0.3.0/PKG-INFO",
            "streaming_json_parser-0.3.0/src/streaming_json_parser.egg-info/PKG-INFO",
        ):
            member = tarfile.TarInfo(name)
            member.size = len(metadata)
            sdist.addfile(member, io.BytesIO(metadata))

    assert distribution_versions(tmp_path) == ("0.3.0", "0.3.0")
