import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .database import Base, engine
from . import models  # noqa: F401  (register models with Base.metadata)
from .jobs.rollup import run_rollup
from .routes.billing import router as billing_router
from .routes.generate import router as generate_router
from .routes.usage import router as usage_router
from .routes.webhooks import router as webhooks_router

logger = logging.getLogger("uvicorn.error")


def _scheduler(stop_event: threading.Event, interval_seconds: int) -> None:
    """Daemon thread that runs the usage rollup job periodically."""
    while not stop_event.wait(interval_seconds):
        try:
            written = run_rollup()
            logger.info("Usage rollup job completed: %d snapshot rows", written)
        except Exception:
            logger.exception("Usage rollup job failed; will retry next cycle")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = threading.Event()
    worker = threading.Thread(
        target=_scheduler,
        args=(stop_event, settings.rollup_interval_seconds),
        daemon=True,
        name="usage-rollup",
    )
    worker.start()

    yield

    stop_event.set()
    worker.join(timeout=5)


app = FastAPI(
    title="Usage Metering & Billing Engine",
    version="2.0.0",
    lifespan=lifespan,
)

Base.metadata.create_all(bind=engine)

app.include_router(generate_router)
app.include_router(usage_router)
app.include_router(billing_router)
app.include_router(webhooks_router)


@app.get("/")
def root():
    return {
        "service": "Usage Metering & Billing Engine",
        "status": "ok",
    }
