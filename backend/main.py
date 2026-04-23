import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

from db.database import Base, engine
from db.models import Settings, Watchlist  # noqa: F401 — ensure models are registered
from api.signals import router as signals_router
from api.position import router as position_router
from api.history import router as history_router
from api.settings import router as settings_router
from api.watchlist import router as watchlist_router
from scheduler import create_scheduler, scanner_state, job_premarkets_init


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables
    Base.metadata.create_all(bind=engine)

    # Seed default settings if missing
    from db.database import SessionLocal
    from db.models import Settings as S
    db = SessionLocal()
    try:
        if not db.query(S).first():
            db.add(S())
            db.commit()
    finally:
        db.close()

    # Start background scheduler
    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(title="Top Bottom Strategy API", version="1.0.0", lifespan=lifespan)

# CORS — allow Vercel frontend
frontend_url = os.getenv("FRONTEND_URL", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals_router)
app.include_router(position_router)
app.include_router(history_router)
app.include_router(settings_router)
app.include_router(watchlist_router)


@app.get("/api/scanner")
def get_scanner():
    """Live scanner state — all F&O stocks with signal status."""
    return {
        "rows": scanner_state["rows"],
        "last_scan": scanner_state["last_scan"],
        "market_open": scanner_state["market_open"],
        "initialized": scanner_state["initialized"],
        "error": scanner_state["error"],
    }


@app.post("/api/scanner/trigger")
def trigger_scan():
    """Manually trigger a pre-market init (for testing outside market hours)."""
    import threading
    t = threading.Thread(target=job_premarkets_init, daemon=True)
    t.start()
    return {"message": "Pre-market init triggered in background"}


@app.get("/health")
def health():
    return {"status": "ok"}
