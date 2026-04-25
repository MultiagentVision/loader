from types import SimpleNamespace

import pytest

from app.db.models import FileStatus
from app.services.dedupe import (
    extract_minio_checksum,
    should_skip_from_db,
    should_skip_from_minio,
)


@pytest.mark.unit
def test_should_skip_from_db_requires_uploaded_status_and_path_and_checksum() -> None:
    row = SimpleNamespace(
        status=FileStatus.UPLOADED.value,
        checksum="AA",
        minio_path="main/1_a.mp4",
    )
    assert should_skip_from_db(row, incoming_checksum="aa", canonical_path="main/1_a.mp4") is True
    assert should_skip_from_db(row, incoming_checksum="bb", canonical_path="main/1_a.mp4") is False


@pytest.mark.unit
def test_should_skip_from_minio_requires_both_checksums() -> None:
    assert should_skip_from_minio(object_checksum="a", incoming_checksum="A") is True
    assert should_skip_from_minio(object_checksum=None, incoming_checksum="A") is False


@pytest.mark.unit
def test_extract_minio_checksum_case_insensitive_keys() -> None:
    assert extract_minio_checksum({"X-Amz-Meta-Checksum": "abc"}) == "abc"
    assert extract_minio_checksum({"checksum": "abc"}) == "abc"
