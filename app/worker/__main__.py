"""Worker entrypoint: `python -m app.worker` (ECS service `worker`, same image as the API)."""

from __future__ import annotations

import logging
import signal
import time

from app.assessments.engines import EngineRegistry
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.jobs.queue import DatabaseJobQueue, JobConsumer, SqsJobQueue
from app.worker.runner import run_forever

logger = logging.getLogger("app.worker")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, "radial-pulse-worker", settings.app_env, settings.service_version)
    session_factory = get_sessionmaker()
    consumer: JobConsumer
    if settings.job_queue_backend == "sqs" and settings.job_queue_url:
        consumer = SqsJobQueue(settings.job_queue_url, settings.aws_region, settings.job_queue_wait_seconds)
    else:
        consumer = DatabaseJobQueue(session_factory)
    engines = EngineRegistry.from_entry_points()
    logger.info(
        "worker started",
        extra={"queue": settings.job_queue_backend, "engines": [k.value for k in engines.keys()]},  # noqa: SIM118,
    )

    stopping = {"now": False}

    def _stop(*_: object) -> None:  # ECS sends SIGTERM on deploy/scale-in
        stopping["now"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    idle = (lambda: time.sleep(5)) if settings.job_queue_backend == "database" else (lambda: None)
    run_forever(consumer, session_factory, engines, stop=lambda: stopping["now"], idle_sleep=idle)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
