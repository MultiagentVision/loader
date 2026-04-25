from __future__ import annotations

from typing import BinaryIO

from minio import Minio
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

    def stat_object(self, object_name: str):
        try:
            return self._client.stat_object(self.bucket, object_name)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return None
            raise

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
