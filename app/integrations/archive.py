"""Where archived rows go: Amazon S3 in AWS, a local folder for development and tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ArchiveStore(Protocol):
    def put(self, key: str, body: bytes) -> None: ...


class S3ArchiveStore:
    """Writes gzipped JSON-lines files to the archive bucket (SSE-KMS).

    Credentials come from the ECS task role of the archive task — never from config. The task
    role needs only ``s3:PutObject`` on this bucket (and ``kms:GenerateDataKey`` on its key).
    """

    def __init__(
        self, bucket: str, region: str, kms_key_id: str | None = None, client: Any | None = None
    ) -> None:
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region)
        self._s3 = client
        self._bucket = bucket
        self._kms_key_id = kms_key_id

    def put(self, key: str, body: bytes) -> None:
        extra: dict[str, Any] = {"ServerSideEncryption": "aws:kms"}
        if self._kms_key_id:
            extra["SSEKMSKeyId"] = self._kms_key_id
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType="application/x-ndjson",
            ContentEncoding="gzip",
            **extra,
        )


class LocalArchiveStore:
    """Same layout as S3, on disk. For local development and tests only."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def put(self, key: str, body: bytes) -> None:
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
