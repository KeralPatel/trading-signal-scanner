"""NSE data client — all data sourced directly from NSE APIs, no yfinance/pandas."""
import csv
import logging
import time
from datetime import date, timedelta
from io import StringIO

import pytz
import requests

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
    SESSION_TTL = 270  # seconds before session refresh

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_NSE_HEADERS)
        self._init_time: float = 0.0

    def _ensure_session(self) -> None:
        if time.time() - self._init_time > self.SESSION_TTL:
            try:
                self.session.get(self.BASE, timeout=10)
                self._init_time = time.time()
                time.sleep(0.3)
            except Exception as exc:
                logger.warning("NSE session refresh failed: %s", exc)

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

    def get_quote_equity(self, symbol: str) -> dict:
        """Return full quote for one equity symbol."""
        self._ensure_session()
        url = f"{self.BASE}/api/quote-equity?symbol={symbol}"
        try:
            r = self.session.get(url, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.error("get_quote_equity failed for %s: %s", symbol, exc)
            return {}

    def get_lot_sizes(self) -> dict[str, int]:
        """Fetch current F&O lot sizes from NSE archives CSV."""
        url = f"{self.ARCHIVE_BASE}/content/fo/fo_mktlots.csv"
        try:
            r = requests.get(url, headers=_NSE_HEADERS, timeout=15)
            r.raise_for_status()
            result: dict[str, int] = {}
            reader = csv.reader(StringIO(r.text))
            next(reader, None)  # skip header
            for row in reader:
                try:
                    symbol = row[0].strip().upper()
                    instrument = row[1].strip()
                    lot_raw = row[2].strip().replace(",", "")
                    if symbol and "FUTSTK" in instrument and lot_raw.isdigit():
                        result[symbol] = int(lot_raw)
                except (IndexError, ValueError):
                    continue
            return result
        except Exception as exc:
            logger.error("get_lot_sizes failed: %s", exc)
            return {}


# ---------------------------------------------------------------------------
# NSE historical OHLC — replaces yfinance for pre-market init
# ---------------------------------------------------------------------------

def _prev_trading_date() -> date:
    """Return the most recent weekday before today (handles weekends)."""
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= timedelta(days=1)
    return d


def _fetch_historical_ohlc(session: requests.Session, symbol: str, trading_date: date) -> dict | None:
    """
    Fetch daily OHLC for one symbol from NSE historical CM equity API.
    Tries up to 3 prior weekdays to handle exchange holidays.
    """
    d = trading_date
    for _ in range(3):
        date_str = d.strftime("%d-%m-%Y")
        url = (
            f"https://www.nseindia.com/api/historical/cm/equity"
            f'?symbol={symbol}&series=["EQ"]&from={date_str}&to={date_str}'
        )
        try:
            r = session.get(url, timeout=10)
            r.raise_for_status()
            rows = r.json().get("data", [])
            if rows:
                row = rows[0]
                return {
                    "open":       float(row.get("CH_OPENING_PRICE", 0)),
                    "high":       float(row.get("CH_TRADE_HIGH_PRICE", 0)),
                    "low":        float(row.get("CH_TRADE_LOW_PRICE", 0)),
                    "close":      float(row.get("CH_CLOSING_PRICE", 0)),
                    "today_open": float(row.get("CH_OPENING_PRICE", 0)),
                }
        except Exception as exc:
            logger.debug("historical OHLC fetch for %s on %s: %s", symbol, date_str, exc)
        # Go back one more weekday
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        time.sleep(0.05)
    return None


def get_prev_day_ohlc_bulk(symbols: list[str]) -> dict[str, dict]:
    """
    Fetch previous trading day OHLC for a list of NSE symbols.
    Uses Yahoo Finance chart API — works from any server globally.
    Returns {SYMBOL: {open, high, low, close, today_open}}.
    """
    if not symbols:
        return {}

    _YF_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    result: dict[str, dict] = {}
    for sym in symbols:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS"
        params = {"interval": "1d", "range": "5d"}
        try:
            r = requests.get(url, params=params, headers=_YF_HEADERS, timeout=10)
            r.raise_for_status()
            res = r.json().get("chart", {}).get("result")
            if not res:
                logger.warning("No chart data from Yahoo for %s", sym)
                continue
            res = res[0]
            ohlcv = res.get("indicators", {}).get("quote", [{}])[0]
            opens  = ohlcv.get("open", [])
            highs  = ohlcv.get("high", [])
            lows   = ohlcv.get("low", [])
            closes = ohlcv.get("close", [])
            # Filter out None values
            valid = [
                (opens[i], highs[i], lows[i], closes[i])
                for i in range(len(opens))
                if opens[i] and highs[i] and lows[i] and closes[i]
            ]
            if len(valid) < 2:
                logger.warning("Not enough OHLC rows for %s (%d valid)", sym, len(valid))
                continue
            prev  = valid[-2]
            today = valid[-1]
            result[sym] = {
                "open":       float(prev[0]),
                "high":       float(prev[1]),
                "low":        float(prev[2]),
                "close":      float(prev[3]),
                "today_open": float(today[0]),
            }
            logger.info("OHLC loaded for %s: prev_H=%.2f prev_L=%.2f", sym, prev[1], prev[2])
        except Exception as exc:
            logger.warning("OHLC fetch failed for %s: %s", sym, exc)
        time.sleep(0.05)
    return result


# ---------------------------------------------------------------------------
# 15-min candle via NSE quote intraDayHighLow (called at 09:30 IST)
# ---------------------------------------------------------------------------

def get_first_15min_candle(symbol: str) -> dict | None:
    """
    Return the 9:15–9:30 candle via Yahoo Finance 15-min data.
    Works from any server globally.
    Returns {open, high, low, close} or None.
    """
    _YF_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS"
    params = {"interval": "15m", "range": "1d"}
    try:
        r = requests.get(url, params=params, headers=_YF_HEADERS, timeout=10)
        r.raise_for_status()
        res = r.json().get("chart", {}).get("result")
        if not res:
            return None
        ohlcv = res[0].get("indicators", {}).get("quote", [{}])[0]
        opens  = ohlcv.get("open", [])
        highs  = ohlcv.get("high", [])
        lows   = ohlcv.get("low", [])
        closes = ohlcv.get("close", [])
        if not opens or not highs[0] or not lows[0]:
            return None
        return {
            "open":  float(opens[0]  or 0),
            "high":  float(highs[0]  or 0),
            "low":   float(lows[0]   or 0),
            "close": float(closes[0] or 0),
        }
    except Exception as exc:
        logger.warning("15-min candle fetch failed for %s: %s", symbol, exc)
    return None
