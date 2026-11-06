"""arq entry point. Run with: arq app.jobs.worker.WorkerSettings

Reads settings from the environment at import time, as arq expects plain class attributes.
"""

from arq.connections import RedisSettings
from arq.cron import cron

from app.config import get_settings
from app.jobs.tasks import FUNCTIONS, expire_documents, shutdown, startup
from app.services.jobs import QUEUE_NAME

_settings = get_settings()

# The expiry sweep, hourly at minute 0; the worker's startup also sweeps once (tasks.startup).
CRON_JOBS = [cron(expire_documents, minute=0)]


class WorkerSettings:
    functions = FUNCTIONS
    queue_name = QUEUE_NAME
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    cron_jobs = CRON_JOBS
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = _settings.job_timeout_seconds
    # The jobs row is the source of truth; a failed or interrupted job is not silently re-run.
    max_tries = 1
    retry_jobs = False
    # The worker refreshes a Redis key this often (TTL = interval + 1 s); `arq --check` (the
    # compose healthcheck) passes only while the key exists. arq's default is one hour.
    health_check_interval = 30
