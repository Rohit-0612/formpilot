# Every route module declares APIRouter(prefix=API_PREFIX) itself instead of getting the prefix
# from include_router(): FastAPI only bakes a router's own prefix into route.path, and the request
# logger reads route.path to log the full route template (e.g. /api/v1/health).
API_PREFIX = "/api/v1"
