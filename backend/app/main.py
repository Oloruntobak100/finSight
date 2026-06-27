from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import analytics, banking, books, chat, oauth, qb_reports, reconciliation, reports, synthetic_feed, transactions, users, webhooks
from app.scheduler.jobs import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
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
)

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
