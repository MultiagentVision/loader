from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import BinaryIO

from minio import Minio
from minio.datatypes import Object as MinioObject
from minio.error import S3Error


class MinioObjectStore:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
    ) -> None:
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self.bucket = bucket

    def ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self.bucket):
            self._client.make_bucket(self.bucket)

    def bucket_exists(self) -> bool:
        return self._client.bucket_exists(self.bucket)

    def stat_object(self, object_name: str) -> MinioObject | None:
        try:
            return self._client.stat_object(self.bucket, object_name)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return None
            raise

    def list_objects(self, prefix: str) -> Iterator[MinioObject]:
        """Iterate over all objects under *prefix* (recursive). Returns name and size only; no user-metadata."""
        return self._client.list_objects(self.bucket, prefix=prefix, recursive=True)

    def get_object_stream(
        self,
        object_name: str,
        *,
        offset: int = 0,
        length: int | None = None,
    ):
        """Return a MinIO object stream, optionally constrained to a byte range."""
        kwargs = {"offset": offset}
        if length is not None:
            kwargs["length"] = length
        return self._client.get_object(self.bucket, object_name, **kwargs)

    def presigned_get_object(self, object_name: str, *, expires: timedelta | None = None) -> str:
        """Return a temporary GET URL for manual ffmpeg/ffprobe checks."""
        return self._client.presigned_get_object(
            self.bucket,
            object_name,
            expires=expires or timedelta(minutes=15),
        )

    def put_object_stream(
        self,
        object_name: str,
        data: BinaryIO,
        length: int,
        metadata: dict[str, str],
    ) -> None:
        self._client.put_object(
            self.bucket,
            object_name,
            data,
            length,
            metadata=metadata,
        )

    def put_object_multipart_stream(
        self,
        object_name: str,
        data: BinaryIO,
        part_size: int,
        metadata: dict[str, str],
    ) -> None:
        """Use multipart upload when length is unknown or very large."""
        self._client.put_object(
            self.bucket,
            object_name,
            data,
            length=-1,
            part_size=part_size,
            metadata=metadata,
        )
