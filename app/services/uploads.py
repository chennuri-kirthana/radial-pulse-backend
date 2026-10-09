"""Private files in S3 (CLAUDE.md rule 11). Only keys are stored in the database.

1. ``ticket()``  : a presigned PUT for ONE key, with the size signed in (S3 refuses other sizes).
2. the browser / app uploads straight to S3.
3. ``check_uploaded()`` : on "complete", the object must exist with the size and type promised.
4. views are short-lived presigned GET links (``view_link``); the caller audits each view.

There is no download endpoint. Presigned URLs are never logged.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import InvalidRequestError, ServiceUnavailableError
from app.integrations.storage import ObjectStorage
from app.schemas.common import UploadTicket

#: How long upload and view links work (open question Q5; 5 minutes until decided).
UPLOAD_URL_TTL_SECONDS = 300
VIEW_URL_TTL_SECONDS = 300


@dataclass(frozen=True)
class FileRule:
    """What one kind of file may be: allowed types (→ file extension) and the largest size."""

    types: dict[str, str]
    max_bytes: int

    def check(self, content_type: str, size_bytes: int) -> str:
        """The file extension for ``content_type``, or 400 with fields."""
        ext = self.types.get(content_type)
        if ext is None:
            raise InvalidRequestError(
                "This file type is not allowed.",
                fields={"content_type": "Use one of: " + ", ".join(sorted(self.types)) + "."},
            )
        if not 0 < size_bytes <= self.max_bytes:
            raise InvalidRequestError(
                "This file is too big.",
                fields={"size_bytes": f"Must be between 1 and {self.max_bytes} bytes."},
            )
        return ext


def ticket(storage: ObjectStorage | None, key: str, content_type: str, size_bytes: int) -> UploadTicket:
    if storage is None:
        raise ServiceUnavailableError("File storage is not set up (S3_ASSETS_BUCKET).")
    url, headers = storage.presign_put(key, content_type, UPLOAD_URL_TTL_SECONDS, content_length=size_bytes)
    return UploadTicket(key=key, upload_url=url, headers=headers, expires_in_seconds=UPLOAD_URL_TTL_SECONDS)


def check_uploaded(storage: ObjectStorage, key: str, size_bytes: int, content_type: str) -> None:
    """The file must be in S3 with exactly the promised size (and type, when S3 reports one)."""
    info = storage.head(key)
    if info is None:
        raise InvalidRequestError("The file has not been uploaded yet.", fields={"file": "Upload it first."})
    if info.size_bytes != size_bytes or (info.content_type and info.content_type != content_type):
        raise InvalidRequestError(
            "The uploaded file is not the one announced.", fields={"file": "Upload again."}
        )


def view_link(storage: ObjectStorage, key: str) -> str:
    return storage.presign_get(key, VIEW_URL_TTL_SECONDS)
