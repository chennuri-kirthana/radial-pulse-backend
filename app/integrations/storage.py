"""Object storage (S3) adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ObjectInfo:
    size_bytes: int
    content_type: str | None
    etag: str | None


class ObjectStorage(Protocol):
    def presign_put(
        self, key: str, content_type: str, ttl_seconds: int, content_length: int | None = None
    ) -> tuple[str, dict[str, str]]: ...

    def presign_get(self, key: str, ttl_seconds: int, download_name: str | None = None) -> str: ...

    def head(self, key: str) -> ObjectInfo | None: ...

    def delete(self, key: str) -> None: ...


class S3ObjectStorage:
    """S3 implementation. Credentials come from the ECS task role — never from config.

    Encryption: the bucket enforces SSE-KMS by default (Terraform ``storage`` module),
    so clients only send ``Content-Type`` with the presigned PUT.
    """

    def __init__(self, bucket: str, region: str, client: Any | None = None) -> None:
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                region_name=region,
                config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
            )
        self._s3 = client
        self._bucket = bucket

    def presign_put(
        self, key: str, content_type: str, ttl_seconds: int, content_length: int | None = None
    ) -> tuple[str, dict[str, str]]:
        """``content_length`` is SIGNED into the URL: S3 refuses a body of any other size, so a
        presigned URL cannot be used to store a bigger file than the one that was checked.
        Browsers send Content-Length themselves, so it is not in the returned headers."""
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key, "ContentType": content_type}
        if content_length is not None:
            params["ContentLength"] = content_length
        url = self._s3.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=ttl_seconds, HttpMethod="PUT"
        )
        return str(url), {"Content-Type": content_type}

    def presign_get(self, key: str, ttl_seconds: int, download_name: str | None = None) -> str:
        params: dict[str, str] = {"Bucket": self._bucket, "Key": key}
        if download_name:
            safe = download_name.replace('"', "").replace("\n", "").replace("\r", "")
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        return str(self._s3.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl_seconds))

    def head(self, key: str) -> ObjectInfo | None:
        from botocore.exceptions import ClientError

        try:
            meta = self._s3.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return ObjectInfo(
            size_bytes=int(meta["ContentLength"]), content_type=meta.get("ContentType"), etag=meta.get("ETag")
        )

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self._bucket, Key=key)
