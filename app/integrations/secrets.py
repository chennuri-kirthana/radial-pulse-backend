"""Where connected-account tokens live: AWS Secrets Manager (never the database, never logs).

One secret per clinic + platform, named ``<prefix>/<env>/connections/<clinic_id>/<platform>``,
encrypted with the environment's KMS key. The database keeps only the secret's ARN.

AWS permissions needed: docs/infrastructure/backend-aws-needs.md. The API may create, update,
restore and delete secrets under that name prefix; the worker may only read them.
"""

from __future__ import annotations

import json
from typing import Any, Protocol


class SecretStore(Protocol):
    def save(self, name: str, value: dict[str, Any]) -> str:
        """Create or replace the secret; return its reference (ARN)."""
        ...

    def delete(self, ref: str) -> None:
        """Schedule deletion (recoverable for 7 days). Missing secrets are ignored."""
        ...


class AwsSecretStore:
    def __init__(self, region: str, kms_key_id: str | None = None) -> None:
        import boto3  # imported lazily: only the API needs it, and tests use a fake

        self._client = boto3.client("secretsmanager", region_name=region)
        self._kms_key_id = kms_key_id

    def save(self, name: str, value: dict[str, Any]) -> str:
        body = json.dumps(value)
        client = self._client
        try:
            kwargs: dict[str, Any] = {
                "Name": name,
                "SecretString": body,
                "Tags": [{"Key": "app", "Value": "radial-pulse"}, {"Key": "kind", "Value": "connection"}],
            }
            if self._kms_key_id:
                kwargs["KmsKeyId"] = self._kms_key_id
            created = client.create_secret(**kwargs)
            return str(created["ARN"])
        except client.exceptions.ResourceExistsException:
            pass
        except client.exceptions.InvalidRequestException:
            # The name is waiting to be deleted (the clinic disconnected recently): bring it back.
            client.restore_secret(SecretId=name)
        updated = client.put_secret_value(SecretId=name, SecretString=body)
        return str(updated["ARN"])

    def delete(self, ref: str) -> None:
        try:
            self._client.delete_secret(SecretId=ref, RecoveryWindowInDays=7)
        except (
            self._client.exceptions.ResourceNotFoundException,
            self._client.exceptions.InvalidRequestException,  # already scheduled for deletion
        ):
            return
