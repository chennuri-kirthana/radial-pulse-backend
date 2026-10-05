"""Job queue: tells the worker "job X is ready". The `background_jobs` row is the truth.

Backends
--------
* ``sqs``      — AWS. One standard queue + a dead-letter queue (Terraform `queue` module).
                 Retries = SQS redelivery after the visibility timeout; after
                 `maxReceiveCount` deliveries the message moves to the DLQ (alarmed).
* ``database`` — local development. Enqueue is a no-op (the row is already `queued`);
                 the worker polls `background_jobs` with FOR UPDATE SKIP LOCKED.
* ``memory``   — tests.

Message contract (JSON, versioned):

    {"schema_version": 1, "job_id": "<uuid>", "clinic_id": "<uuid>", "job_type": "assessment.run"}

Messages carry ids only — never data, tokens or personal information.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import JobStatus, JobType

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class JobMessage:
    job_id: UUID
    clinic_id: UUID
    job_type: JobType
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "job_id": str(self.job_id),
                "clinic_id": str(self.clinic_id),
                "job_type": self.job_type.value,
            }
        )

    @classmethod
    def from_json(cls, body: str) -> JobMessage:
        data = json.loads(body)
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported job message schema_version {data.get('schema_version')}")
        return cls(
            job_id=UUID(data["job_id"]), clinic_id=UUID(data["clinic_id"]), job_type=JobType(data["job_type"])
        )


@dataclass
class ReceivedJob:
    message: JobMessage
    #: Backend handle used to acknowledge (SQS receipt handle).
    handle: Any = None


class JobQueue(Protocol):
    """Producer side (the API)."""

    def enqueue(self, message: JobMessage) -> None: ...


class JobConsumer(Protocol):
    """Consumer side (the worker)."""

    def receive(self) -> list[ReceivedJob]: ...

    def ack(self, job: ReceivedJob) -> None: ...


# --------------------------------------------------------------------------- SQS
class SqsJobQueue:
    def __init__(
        self, queue_url: str, region: str, wait_seconds: int = 20, client: Any | None = None
    ) -> None:
        if client is None:
            import boto3

            client = boto3.client("sqs", region_name=region)
        self._sqs = client
        self._url = queue_url
        self._wait = wait_seconds

    def enqueue(self, message: JobMessage) -> None:
        self._sqs.send_message(
            QueueUrl=self._url,
            MessageBody=message.to_json(),
            MessageAttributes={"job_type": {"DataType": "String", "StringValue": message.job_type.value}},
        )

    def receive(self) -> list[ReceivedJob]:
        resp = self._sqs.receive_message(
            QueueUrl=self._url, MaxNumberOfMessages=1, WaitTimeSeconds=self._wait
        )
        return [
            ReceivedJob(message=JobMessage.from_json(m["Body"]), handle=m["ReceiptHandle"])
            for m in resp.get("Messages", [])
        ]

    def ack(self, job: ReceivedJob) -> None:
        self._sqs.delete_message(QueueUrl=self._url, ReceiptHandle=job.handle)


# ----------------------------------------------------------------------- database
class DatabaseJobQueue:
    """Local development only: the worker polls the table. Not used in AWS."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory = session_factory

    def enqueue(self, message: JobMessage) -> None:
        return None  # the committed `queued` row IS the message

    def receive(self) -> list[ReceivedJob]:
        from app.db.tenant import set_tenant_scope
        from app.models import BackgroundJob

        if self._session_factory is None:
            return []
        with self._session_factory() as session:
            # Scanning for work spans clinics; each job is then processed with a ONE-clinic scope.
            set_tenant_scope(session, None)
            stmt = (
                select(BackgroundJob.id, BackgroundJob.clinic_id, BackgroundJob.job_type)
                .where(BackgroundJob.status == JobStatus.QUEUED)
                .order_by(BackgroundJob.created_at)
                .limit(1)
            )
            rows = session.execute(stmt).all()
        return [ReceivedJob(message=JobMessage(job_id=r[0], clinic_id=r[1], job_type=r[2])) for r in rows]

    def ack(self, job: ReceivedJob) -> None:
        return None


# ------------------------------------------------------------------------- memory
@dataclass
class InMemoryJobQueue:
    messages: list[JobMessage] = field(default_factory=list)
    acked: list[JobMessage] = field(default_factory=list)

    def enqueue(self, message: JobMessage) -> None:
        self.messages.append(message)

    def receive(self) -> list[ReceivedJob]:
        return [ReceivedJob(message=m) for m in list(self.messages)]

    def ack(self, job: ReceivedJob) -> None:
        self.messages.remove(job.message)
        self.acked.append(job.message)
