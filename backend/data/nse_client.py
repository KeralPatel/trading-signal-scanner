"""NSE Unofficial API client + yfinance helpers.
Designed with a clean interface so the data layer can be swapped
to ICICI Breeze (or any other provider) by replacing this file.
"""
import time
import logging
from io import StringIO
from datetime import datetime

import requests
import yfinance as yf
import pandas as pd
import pytz

IST = pytz.timezone("Asia/Kolkata")
logger = logging.getLogger(__name__)

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}


class NSEClient:
    BASE = "https://www.nseindia.com"
    ARCHIVE_BASE = "https://archives.nseindia.com"
    SESSION_TTL = 270  # seconds before session refresh (inside cache TTL)

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_NSE_HEADERS)
        self._init_time: float = 0.0

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    def _ensure_session(self) -> None:
        if time.time() - self._init_time > self.SESSION_TTL:
            try:
                self.session.get(self.BASE, timeout=10)
                self._init_time = time.time()
                time.sleep(0.3)
            except Exception as exc:
                logger.warning("NSE session refresh failed: %s", exc)

    # ------------------------------------------------------------------
    # F&O quotes (batch, all stocks in one request)
    # ------------------------------------------------------------------
    def get_fo_quotes(self) -> list[dict]:
        """Return all F&O-eligible equities with live market data."""
        self._ensure_session()
        url = f"{self.BASE}/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
        try:
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            return data.get("data", [])
        except Exception as exc:
            logger.error("get_fo_quotes failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Lot sizes from NSE archives CSV
    # ------------------------------------------------------------------
    def get_lot_sizes(self) -> dict[str, int]:
        """Fetch current F&O lot sizes. Returns {SYMBOL: lot_size}."""
        url = f"{self.ARCHIVE_BASE}/content/fo/fo_mktlots.csv"
        try:
            r = requests.get(url, headers=_NSE_HEADERS, timeout=15)
            r.raise_for_status()
            df = pd.read_csv(StringIO(r.text), header=None, skiprows=1)
            result: dict[str, int] = {}
            for _, row in df.iterrows():
                try:
                    symbol = str(row.iloc[0]).strip().upper()
                    instrument = str(row.iloc[1]).strip()
                    lot_raw = str(row.iloc[2]).strip().replace(",", "")
                    if symbol and "FUTSTK" in instrument and lot_raw.isdigit():
                        result[symbol] = int(lot_raw)
                except (IndexError, ValueError):
                    continue
            return result
        except Exception as exc:
            logger.error("get_lot_sizes failed: %s", exc)
            return {}


# ---------------------------------------------------------------------------
# yfinance helpers — historical OHLC (swap these for live provider later)
# ---------------------------------------------------------------------------

def get_prev_day_ohlc_bulk(symbols: list[str]) -> dict[str, dict]:
    """
    Batch-fetch previous day OHLC + today's open for all symbols via yfinance.
    Returns {SYMBOL: {open, high, low, close, today_open}}.
    """
    if not symbols:
        return {}
    yf_symbols = [f"{s}.NS" for s in symbols]
    try:
        raw = yf.download(
            tickers=" ".join(yf_symbols),
            period="5d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )
    except Exception as exc:
        logger.error("yfinance bulk download failed: %s", exc)
        return {}

    result: dict[str, dict] = {}
    for sym in symbols:
        yf_sym = f"{sym}.NS"
        try:
            if len(symbols) == 1:
                hist = raw.dropna()
            else:
                hist = raw[yf_sym].dropna()

            if len(hist) < 2:
                continue

            prev = hist.iloc[-2]
            today = hist.iloc[-1]
            result[sym] = {
                "open": float(prev["Open"]),
                "high": float(prev["High"]),
                "low": float(prev["Low"]),
                "close": float(prev["Close"]),
                "today_open": float(today["Open"]),
            }
        except Exception:
            continue
    return result


def get_first_15min_candle(symbol: str) -> dict | None:
    """
    Return the 9:15–9:30 IST candle for today using yfinance 15-min data.
    Returns {open, high, low, close} or None.
    """
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        hist = ticker.history(period="1d", interval="15m", auto_adjust=True)
        hist = hist.dropna()
        if hist.empty:
            return None
        row = hist.iloc[0]
        return {
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
        }
    except Exception as exc:
        logger.warning("15-min candle fetch failed for %s: %s", symbol, exc)
        return None
