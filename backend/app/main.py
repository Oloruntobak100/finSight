import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.routers import analytics, banking, books, chat, oauth, qb_reports, reconciliation, reports, synthetic_feed, transactions, users, webhooks
from app.scheduler.jobs import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)


async def _startup_live_feed_catchup() -> None:
    """Process overdue synthetic live drips after deploy or Railway restart."""
    await asyncio.sleep(3)
    try:
        from app.scheduler.tasks import synthetic_feed_drip_all

        result = await synthetic_feed_drip_all()
        if isinstance(result, dict) and result.get("processed"):
            logger.info("Startup live feed catch-up: %s", result)
    except Exception:
        logger.exception("Startup live feed catch-up failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    asyncio.create_task(_startup_live_feed_catchup())
    yield
    stop_scheduler()


app = FastAPI(
    title="FinSight AI API",
    description="AI-powered financial intelligence platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return JSON 500s so CORS middleware can attach headers (avoids browser CORS masking)."""
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    if isinstance(exc, RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.include_router(banking.router)
app.include_router(synthetic_feed.router)
app.include_router(oauth.router)
app.include_router(books.router)
app.include_router(users.router)
app.include_router(qb_reports.router)
app.include_router(reconciliation.router)
app.include_router(transactions.router)
app.include_router(analytics.router)
app.include_router(chat.router)
app.include_router(reports.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "finsight-api"}
