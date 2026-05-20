"""
Scheduler — drives the scanner every minute during NSE market hours (IST).

Jobs:
  08:45 IST  — pre-market init (fetch prev-day OHLC, lot sizes);
               if a position is carried forward, upgrades its SL to
               next-day rules: max(prev_low, entry×0.97) for BUY
  09:15 IST  — market open
  09:30 IST  — lock 15-min candles for gap stocks
  every 1min — run_scan() during 09:15–15:29
  15:29 IST  — mark market closed; position carries forward (no force-close)
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    pass

IST = pytz.timezone("Asia/Kolkata")
logger = logging.getLogger(__name__)

# Shared mutable state — written by scheduler, read by API routes
scanner_state: dict = {
    "rows": [],           # list of StockState dicts for dashboard
    "signals": {},        # symbol -> signal dict (in-memory, pending signals)
    "last_scan": None,    # datetime of last scan
    "market_open": False,
    "initialized": False,
    "error": None,
}
_state_lock = threading.Lock()


def _get_db():
    from db.database import SessionLocal
    return SessionLocal()


def _get_settings(db):
    from db.models import Settings
    s = db.query(Settings).first()
    if not s:
        from db.models import Settings as S
        s = S()
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# Engine singleton (lazy init)
# ---------------------------------------------------------------------------
_engine = None
_nse_client = None


def _ensure_engine(settings):
    global _engine
    if _engine is None:
        from strategy.top_bottom import SignalEngine
        _engine = SignalEngine(settings)
    else:
        _engine.settings = settings
    return _engine


def _ensure_nse():
    global _nse_client
    if _nse_client is None:
        from data.nse_client import NSEClient
        _nse_client = NSEClient()
    return _nse_client


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def job_premarkets_init():
    """08:45 IST — fetch previous day OHLC for watchlist symbols only."""
    logger.info("Pre-market init starting…")
    db = _get_db()
    try:
        settings = _get_settings(db)
        engine = _ensure_engine(settings)
        engine.reset_daily()

        from db.models import Watchlist
        watchlist = db.query(Watchlist).all()
        if not watchlist:
            logger.warning("Watchlist is empty — add stocks via the dashboard")
            with _state_lock:
                scanner_state["error"] = "Watchlist is empty. Add stocks via Settings → Watchlist."
            return

        # Build lot_size map from watchlist (no need to fetch full NSE CSV)
        lot_sizes = {w.symbol: w.lot_size for w in watchlist if w.lot_size > 0}
        symbols = [w.symbol for w in watchlist]
        logger.info("Fetching prev-day OHLC for %d watchlist symbols…", len(symbols))

        from data.nse_client import get_prev_day_ohlc_bulk
        ohlc_map = get_prev_day_ohlc_bulk(symbols)

        initialized = 0
        for sym, ohlc in ohlc_map.items():
            lot = lot_sizes.get(sym, 1)   # default 1 if user forgot to set lot size
            if ohlc:
                engine.initialize_stock(
                    symbol=sym,
                    lot_size=lot,
                    prev_ohlc=ohlc,
                    current_price=ohlc["today_open"],
                )
                initialized += 1

        # Carry-forward: upgrade SL of any open position to next-day rules.
        # Intraday SL (1.5%) is replaced by max(prev_low, entry×sl_pct_nextday)
        # for BUY, or min(prev_high, entry×sl_pct_nextday) for SELL.
        # We only tighten the SL (never loosen it past the trailing stop level).
        from trading.paper_trader import get_open_position
        pos = get_open_position(db)
        if pos:
            sym = pos.symbol
            ohlc = ohlc_map.get(sym)
            if ohlc:
                nd_pct = settings.sl_pct_nextday / 100.0
                if pos.direction == "BUY":
                    nextday_sl = max(ohlc["low"], pos.entry_price * (1.0 - nd_pct))
                    if nextday_sl > pos.sl_price:
                        pos.sl_price = round(nextday_sl, 2)
                        logger.info("Carry-forward: BUY %s SL → %.2f (next-day rule)", sym, pos.sl_price)
                else:
                    nextday_sl = min(ohlc["high"], pos.entry_price * (1.0 + nd_pct))
                    if nextday_sl < pos.sl_price:
                        pos.sl_price = round(nextday_sl, 2)
                        logger.info("Carry-forward: SELL %s SL → %.2f (next-day rule)", sym, pos.sl_price)
                db.commit()

        with _state_lock:
            scanner_state["initialized"] = True
            scanner_state["error"] = None

        logger.info("Pre-market init done: %d stocks loaded", initialized)
    except Exception as exc:
        logger.error("Pre-market init failed: %s", exc)
        with _state_lock:
            scanner_state["error"] = str(exc)
    finally:
        db.close()


def job_market_open():
    """09:15 IST — mark market as open."""
    logger.info("Market open")
    with _state_lock:
        scanner_state["market_open"] = True


def job_lock_15min_candles():
    """
    09:30 IST — two responsibilities:
    1. Lock 15-min candles for gap stocks (for new signal entry triggers).
    2. Gap SL override for carried-forward positions:
         LONG  + gap-down > 3% → SL = 15-min candle LOW
         SHORT + gap-up   > 3% → SL = 15-min candle HIGH
       Uses live NSE open/prevClose for the gap calculation (more accurate
       than the pre-market NSE historical data fetched at 8:45).
    """
    logger.info("Locking 15-min candles…")
    db = _get_db()
    try:
        settings = _get_settings(db)
        engine = _ensure_engine(settings)
        nse = _ensure_nse()
        from data.nse_client import get_first_15min_candle
        from trading.paper_trader import get_open_position

        # --- Identify symbols that need candle data ---
        gap_stocks: set[str] = {
            sym for sym, s in engine.states.items()
            if s.is_gap_up or s.is_gap_down
        }

        # Check for a carried-forward position (entered on a previous day)
        pos = get_open_position(db)
        pos_symbol: str | None = None
        if pos:
            today = datetime.now(IST).date()
            entry_date = pos.entry_time.date() if pos.entry_time else today
            if entry_date < today:
                pos_symbol = pos.symbol

        # Fetch candles for all required symbols in one pass
        candle_syms = gap_stocks | ({pos_symbol} if pos_symbol else set())
        candle_map: dict[str, dict] = {}
        for sym in candle_syms:
            candle = get_first_15min_candle(sym)
            if candle:
                candle_map[sym] = candle

        # Lock scanner gap stocks
        for sym in gap_stocks:
            if sym in candle_map:
                engine.lock_fifteen_min_candle(
                    sym, candle_map[sym]["high"], candle_map[sym]["low"]
                )
        logger.info("Locked 15-min candles for %d gap stocks", len(gap_stocks))

        # --- Gap SL override for carried-forward position ---
        if pos_symbol and pos_symbol in candle_map:
            quotes = nse.get_fo_quotes()
            q = next((x for x in quotes if x.get("symbol") == pos_symbol), None)
            if q:
                today_open = float(q.get("open", 0) or 0)
                prev_close = float(q.get("previousClose", 0) or 0)
                if today_open > 0 and prev_close > 0:
                    gap_pct = (today_open - prev_close) / prev_close
                    candle = candle_map[pos_symbol]

                    if pos.direction == "BUY" and gap_pct < -0.03:
                        pos.sl_price = round(candle["low"], 2)
                        db.commit()
                        logger.info(
                            "Gap-down >3%% SL override: LONG %s gap=%.2f%% → SL=%.2f (15-min candle low)",
                            pos_symbol, gap_pct * 100, pos.sl_price,
                        )
                    elif pos.direction == "SELL" and gap_pct > 0.03:
                        pos.sl_price = round(candle["high"], 2)
                        db.commit()
                        logger.info(
                            "Gap-up >3%% SL override: SHORT %s gap=%.2f%% → SL=%.2f (15-min candle high)",
                            pos_symbol, gap_pct * 100, pos.sl_price,
                        )

    except Exception as exc:
        logger.error("lock_15min_candles failed: %s", exc)
    finally:
        db.close()


def job_run_scan():
    """Every 1-min during market hours — check signals, update position."""
    if not scanner_state.get("initialized") or not scanner_state.get("market_open"):
        return

    db = _get_db()
    try:
        settings = _get_settings(db)
        nse = _ensure_nse()
        engine = _ensure_engine(settings)

        quotes = nse.get_fo_quotes()
        if not quotes:
            logger.warning("Empty quotes from NSE — skipping scan")
            return

        # Only keep prices for symbols currently in the engine (watchlist)
        watched = set(engine.states.keys())
        price_map = {
            q["symbol"]: float(q.get("lastPrice") or q.get("last_price", 0))
            for q in quotes
            if q.get("symbol") and q["symbol"] in watched
        }

        # Check signals
        from db.models import Signal
        new_signals = {}
        for sym, price in price_map.items():
            if price <= 0:
                continue
            sig = engine.check_signal(sym, price)
            if sig:
                # Persist to DB if not already there today
                existing = (
                    db.query(Signal)
                    .filter(Signal.symbol == sym, Signal.status == "pending")
                    .first()
                )
                if not existing:
                    db_sig = Signal(
                        symbol=sig["symbol"],
                        direction=sig["direction"],
                        signal_type=sig["signal_type"],
                        entry_price=sig["entry_price"],
                        sl_price=sig["sl_price"],
                        sl_pct=sig["sl_pct"],
                        lots=sig["lots"],
                        lot_size=sig["lot_size"],
                        capital_risk=sig["capital_risk"],
                        status="pending",
                    )
                    db.add(db_sig)
                    db.commit()
                    logger.info("Signal fired: %s %s @ %.2f",
                                sig["direction"], sym, sig["entry_price"])
                new_signals[sym] = sig

        # Update open position
        from trading.paper_trader import get_open_position, update_position, close_position
        pos = get_open_position(db)
        if pos and pos.symbol in price_map:
            price = price_map[pos.symbol]
            exit_reason = update_position(db, pos, price, settings.trailing_step)
            if exit_reason:
                close_position(db, pos, price, exit_reason)
                logger.info("Position closed by scanner: %s reason=%s", pos.symbol, exit_reason)

        # Update shared state for API
        with _state_lock:
            scanner_state["rows"] = engine.get_scanner_rows()
            scanner_state["last_scan"] = datetime.now(IST).isoformat()

    except Exception as exc:
        logger.error("Scan failed: %s", exc, exc_info=True)
        with _state_lock:
            scanner_state["error"] = f"Scan error: {exc}"
    finally:
        db.close()


def job_end_of_day():
    """15:29 IST — market closes; position carries forward to next day."""
    logger.info("End-of-day: market closed, position carries forward")
    with _state_lock:
        scanner_state["market_open"] = False
        scanner_state["initialized"] = False


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=IST)

    scheduler.add_job(job_premarkets_init, CronTrigger(hour=8, minute=45, timezone=IST),
                      id="premarkets_init", replace_existing=True)

    scheduler.add_job(job_market_open, CronTrigger(hour=9, minute=15, timezone=IST),
                      id="market_open", replace_existing=True)

    scheduler.add_job(job_lock_15min_candles, CronTrigger(hour=9, minute=30, timezone=IST),
                      id="lock_15min", replace_existing=True)

    # Every minute Mon–Fri 09:15–15:29
    scheduler.add_job(
        job_run_scan,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*", timezone=IST),
        id="run_scan",
        replace_existing=True,
    )

    scheduler.add_job(job_end_of_day, CronTrigger(hour=15, minute=29, timezone=IST),
                      id="end_of_day", replace_existing=True)

    return scheduler
