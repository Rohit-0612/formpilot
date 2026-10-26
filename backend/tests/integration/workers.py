"""The real arq worker, configured like WorkerSettings but on the test Redis and database."""

from arq.connections import RedisSettings
from arq.worker import Worker

from app.config import Settings
from app.jobs.worker import WorkerSettings


def make_worker(
    settings: Settings, *, burst: bool = True, extra_functions: list | None = None
) -> Worker:
    """A Worker configured exactly like WorkerSettings, but on the test Redis and database."""
    return Worker(
        functions=[*WorkerSettings.functions, *(extra_functions or [])],
        queue_name=WorkerSettings.queue_name,
        on_startup=WorkerSettings.on_startup,
        on_shutdown=WorkerSettings.on_shutdown,
        job_timeout=WorkerSettings.job_timeout,
        max_tries=WorkerSettings.max_tries,
        retry_jobs=WorkerSettings.retry_jobs,
        health_check_interval=WorkerSettings.health_check_interval,
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        ctx={"settings": settings},
        burst=burst,
        handle_signals=False,
        poll_delay=0.05,
    )
