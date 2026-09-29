"""Job commands for developers and CI.

    python -m app.jobs.cli ping              # enqueue a ping job
    python -m app.jobs.cli ping --wait 30    # ...and wait until it is done (exit 1 otherwise)

Output goes through the structured logger (job id and final status).
"""

import argparse
import asyncio
import sys
import time
import uuid

from app.config import Settings, get_settings
from app.db.models import JobStatus, JobType
from app.db.session import make_engine, make_sessionmaker
from app.logging import configure_logging, get_logger
from app.services.jobs import JobService, JobStore, create_queue

log = get_logger("app.jobs.cli")

_FINAL_STATUSES = {JobStatus.DONE.value, JobStatus.FAILED.value}


async def enqueue_ping(settings: Settings) -> uuid.UUID:
    engine = make_engine(settings)
    queue = await create_queue(settings)
    try:
        async with make_sessionmaker(engine)() as session:
            job = await JobService(session, queue).create_job(JobType.PING)
            return job.id
    finally:
        await queue.aclose()
        await engine.dispose()


async def wait_for_job(
    settings: Settings, job_id: uuid.UUID, timeout_seconds: float, poll_seconds: float = 0.2
) -> str:
    """Poll the jobs row until it is done/failed. Returns its status, or "timeout"."""
    engine = make_engine(settings)
    store = JobStore(make_sessionmaker(engine))
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            job = await store.get(job_id)
            if job is not None and job.status in _FINAL_STATUSES:
                return job.status
            if time.monotonic() >= deadline:
                return "timeout"
            await asyncio.sleep(poll_seconds)
    finally:
        await engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.jobs.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    ping = commands.add_parser("ping", help="enqueue a no-op ping job")
    ping.add_argument(
        "--wait", type=float, default=0, metavar="SECONDS", help="wait for the job to finish"
    )
    return parser


async def run(argv: list[str], settings: Settings) -> int:
    args = _parser().parse_args(argv)
    job_id = await enqueue_ping(settings)
    if args.wait <= 0:
        return 0
    status = await wait_for_job(settings, job_id, args.wait)
    log.info("job_finished", job_id=str(job_id), status=status)
    return 0 if status == JobStatus.DONE.value else 1


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    return asyncio.run(run(sys.argv[1:] if argv is None else argv, settings))


if __name__ == "__main__":
    sys.exit(main())
