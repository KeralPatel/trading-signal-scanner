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
import threading
from datetime import datetime

import pytz

from scheduler import create_scheduler, scanner_state, job_premarkets_init, job_market_open

IST = pytz.timezone("Asia/Kolkata")

# Market session boundaries (IST)
_MARKET_OPEN_H, _MARKET_OPEN_M = 9, 15
_MARKET_CLOSE_H, _MARKET_CLOSE_M = 15, 29
_PREINIT_H, _PREINIT_M = 8, 45


def _catchup_on_startup():
    """
    If the service starts mid-session (e.g. after a redeploy or Render cold start),
    the 8:45 and 9:15 scheduled jobs have already passed. Replay them so the
    scanner is immediately live instead of waiting until tomorrow.
    """
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday / Sunday — no market
        return

    total_minutes = now.hour * 60 + now.minute

    pre_init_minutes = _PREINIT_H * 60 + _PREINIT_M          # 525
    market_open_minutes = _MARKET_OPEN_H * 60 + _MARKET_OPEN_M  # 555
    market_close_minutes = _MARKET_CLOSE_H * 60 + _MARKET_CLOSE_M  # 929

    if pre_init_minutes <= total_minutes <= market_close_minutes:
        # We're inside (or past) the pre-market window — run init in background
        t = threading.Thread(target=job_premarkets_init, daemon=True)
        t.start()

    if market_open_minutes <= total_minutes <= market_close_minutes:
        # Market is currently open — flip the flag immediately
        job_market_open()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables — wrapped so a DB outage at startup doesn't kill the service
    try:
        Base.metadata.create_all(bind=engine)
        from db.database import SessionLocal
        from db.models import Settings as S
        db = SessionLocal()
        try:
            if not db.query(S).first():
                db.add(S())
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logging.error("DB init failed (will retry on first request): %s", exc)

    # Start background scheduler
    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler

    # Replay missed startup jobs if we launched during market hours
    _catchup_on_startup()

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


@app.get("/api/debug/db")
def debug_db():
    """Show which database URL is active (masked password)."""
    from db.database import DATABASE_URL
    masked = DATABASE_URL
    if "@" in DATABASE_URL:
        # hide password: postgresql://user:PASS@host/db → postgresql://user:***@host/db
        parts = DATABASE_URL.split("@")
        creds = parts[0].rsplit(":", 1)
        masked = creds[0] + ":***@" + parts[1]
    return {"database_url": masked}


@app.get("/api/debug/nse")
def debug_nse():
    """Test NSE connectivity — call this to check if NSE APIs are reachable."""
    import requests
    results = {}

    # Test 1: NSE homepage (session warm-up)
    try:
        r = requests.get("https://www.nseindia.com", timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        results["homepage"] = {"status": r.status_code, "ok": r.status_code == 200}
    except Exception as e:
        results["homepage"] = {"status": "error", "ok": False, "error": str(e)}

    # Test 2: F&O quotes endpoint
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.nseindia.com/",
        })
        session.get("https://www.nseindia.com", timeout=10)
        r = session.get(
            "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O",
            timeout=15
        )
        data = r.json()
        count = len(data.get("data", []))
        results["fo_quotes"] = {"status": r.status_code, "ok": count > 0, "rows": count}
    except Exception as e:
        results["fo_quotes"] = {"status": "error", "ok": False, "error": str(e)}

    return results
