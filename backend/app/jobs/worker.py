"""arq entry point. Run with: arq app.jobs.worker.WorkerSettings

Reads settings from the environment at import time, as arq expects plain class attributes.
"""

from arq.connections import RedisSettings

from app.config import get_settings
from app.jobs.tasks import FUNCTIONS, shutdown, startup
from app.services.jobs import QUEUE_NAME

_settings = get_settings()


class WorkerSettings:
    functions = FUNCTIONS
    queue_name = QUEUE_NAME
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = _settings.job_timeout_seconds
    # The jobs row is the source of truth; a failed or interrupted job is not silently re-run.
    max_tries = 1
    retry_jobs = False
