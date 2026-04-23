"""
Top Bottom Strategy — Signal Engine

BUY rules (normal day):
  Entry  : price breaks above min(prev_high, prev_close * 1.03)
  SL     : 1.5% below entry (intraday); max(prev_low, entry * 0.97) next-day
  0.25%  : if SL diff < 0.25%, SL = prev_low

BUY rules (gap-up day):
  Entry  : price breaks above 1st 15-min candle HIGH (9:30+)
  SL     : 1.5% below entry (intraday)
  0.25%  : if SL diff < 0.25%, SL = 15-min candle LOW

SELL rules mirror BUY in the opposite direction.
On SL hit → exit flat (no reversal).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StockState:
    symbol: str
    lot_size: int = 0
    # Previous day
    prev_high: float = 0.0
    prev_low: float = 0.0
    prev_close: float = 0.0
    # Today
    day_open: float = 0.0
    is_gap_up: bool = False
    is_gap_down: bool = False
    # 15-min candle (locked at 9:30)
    fifteen_min_high: Optional[float] = None
    fifteen_min_low: Optional[float] = None
    candle_locked: bool = False
    # Pre-computed triggers (normal day only)
    buy_trigger: float = 0.0
    sell_trigger: float = 0.0
    # Signal control
    signal_fired: Optional[str] = None   # 'BUY' | 'SELL'
    last_price: float = 0.0
    # For display: distance to trigger as % of current price
    dist_to_buy_pct: float = 0.0
    dist_to_sell_pct: float = 0.0


class SignalEngine:
    def __init__(self, settings):
        self.settings = settings
        self.states: dict[str, StockState] = {}

    # ------------------------------------------------------------------
    # Initialisation (called once per trading day per stock)
    # ------------------------------------------------------------------
    def initialize_stock(
        self,
        symbol: str,
        lot_size: int,
        prev_ohlc: dict,
        current_price: float,
    ) -> None:
        pct3 = self.settings.sl_pct_nextday / 100.0  # 0.03
        state = StockState(symbol=symbol, lot_size=lot_size)
        state.prev_high = prev_ohlc["high"]
        state.prev_low = prev_ohlc["low"]
        state.prev_close = prev_ohlc["close"]
        state.day_open = current_price
        state.last_price = current_price

        # Gap detection: any non-zero gap counts
        state.is_gap_up = current_price > prev_ohlc["close"]
        state.is_gap_down = current_price < prev_ohlc["close"]

        # Normal-day triggers: whichever price is closer (hit first)
        state.buy_trigger = min(state.prev_high, state.prev_close * (1 + pct3))
        state.sell_trigger = max(state.prev_low, state.prev_close * (1 - pct3))

        self.states[symbol] = state

    def lock_fifteen_min_candle(
        self, symbol: str, high: float, low: float
    ) -> None:
        if symbol in self.states:
            s = self.states[symbol]
            s.fifteen_min_high = high
            s.fifteen_min_low = low
            s.candle_locked = True

    # ------------------------------------------------------------------
    # Per-tick signal check
    # ------------------------------------------------------------------
    def check_signal(self, symbol: str, current_price: float) -> Optional[dict]:
        if symbol not in self.states:
            return None
        s = self.states[symbol]
        s.last_price = current_price
        self._update_distances(s, current_price)

        if s.signal_fired:
            return None  # already fired today

        if s.is_gap_up:
            return self._check_gap_up(s, current_price)
        if s.is_gap_down:
            return self._check_gap_down(s, current_price)
        return self._check_normal(s, current_price)

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------
    def _check_gap_up(self, s: StockState, price: float) -> Optional[dict]:
        if not s.candle_locked or s.fifteen_min_high is None:
            return None
        if price > s.fifteen_min_high:
            return self._build_signal(s, "BUY", s.fifteen_min_high, "gap_up", price)
        return None

    def _check_gap_down(self, s: StockState, price: float) -> Optional[dict]:
        if not s.candle_locked or s.fifteen_min_low is None:
            return None
        if price < s.fifteen_min_low:
            return self._build_signal(s, "SELL", s.fifteen_min_low, "gap_down", price)
        return None

    def _check_normal(self, s: StockState, price: float) -> Optional[dict]:
        if price > s.buy_trigger:
            return self._build_signal(s, "BUY", s.buy_trigger, "normal", price)
        if price < s.sell_trigger:
            return self._build_signal(s, "SELL", s.sell_trigger, "normal", price)
        return None

    # ------------------------------------------------------------------
    # Signal construction
    # ------------------------------------------------------------------
    def _build_signal(
        self,
        s: StockState,
        direction: str,
        entry: float,
        signal_type: str,
        current_price: float,
    ) -> dict:
        sl_pct_intra = self.settings.sl_pct_intraday / 100.0  # 0.015
        sl_pct_next = self.settings.sl_pct_nextday / 100.0    # 0.03

        if direction == "BUY":
            sl_raw = entry * (1.0 - sl_pct_intra)
            # 0.25% rule: if SL is too close, use candle/prev-day low
            if (entry - sl_raw) / entry < 0.0025:
                sl_raw = (
                    s.fifteen_min_low
                    if signal_type == "gap_up" and s.fifteen_min_low
                    else s.prev_low
                )
            sl = sl_raw
            # Next-day SL (shown as info, not the active SL)
            sl_nextday = max(s.prev_low, entry * (1.0 - sl_pct_next))
        else:  # SELL
            sl_raw = entry * (1.0 + sl_pct_intra)
            if (sl_raw - entry) / entry < 0.0025:
                sl_raw = (
                    s.fifteen_min_high
                    if signal_type == "gap_down" and s.fifteen_min_high
                    else s.prev_high
                )
            sl = sl_raw
            sl_nextday = min(s.prev_high, entry * (1.0 + sl_pct_next))

        sl_distance = abs(entry - sl) / entry if sl != entry else sl_pct_intra

        # Lot calculation: target 3% capital risk
        capital = self.settings.capital
        risk_amount = capital * (self.settings.risk_pct / 100.0)
        contract_value = entry * s.lot_size
        lots = (
            max(1, int(risk_amount / (contract_value * sl_distance)))
            if contract_value > 0 and sl_distance > 0
            else 1
        )

        # Gap metric: distance (%) between 15-min trigger and SL
        gap_metric: Optional[float] = None
        if signal_type in ("gap_up", "gap_down") and sl > 0:
            gap_metric = round(abs(entry - sl) / sl * 100, 2)

        s.signal_fired = direction

        return {
            "symbol": s.symbol,
            "direction": direction,
            "signal_type": signal_type,
            "entry_price": round(entry, 2),
            "sl_price": round(sl, 2),
            "sl_nextday": round(sl_nextday, 2),
            "sl_pct": round(sl_distance * 100, 3),
            "lots": lots,
            "lot_size": s.lot_size,
            "capital_risk": round(risk_amount, 2),
            "current_price": round(current_price, 2),
            "prev_high": s.prev_high,
            "prev_low": s.prev_low,
            "prev_close": s.prev_close,
            "gap_metric": gap_metric,
        }

    def _update_distances(self, s: StockState, price: float) -> None:
        if s.is_gap_up and s.fifteen_min_high:
            s.dist_to_buy_pct = round(
                (s.fifteen_min_high - price) / price * 100, 2
            )
            s.dist_to_sell_pct = 0.0
        elif s.is_gap_down and s.fifteen_min_low:
            s.dist_to_sell_pct = round(
                (price - s.fifteen_min_low) / price * 100, 2
            )
            s.dist_to_buy_pct = 0.0
        elif not s.is_gap_up and not s.is_gap_down:
            s.dist_to_buy_pct = round(
                (s.buy_trigger - price) / price * 100, 2
            ) if s.buy_trigger > price else 0.0
            s.dist_to_sell_pct = round(
                (price - s.sell_trigger) / price * 100, 2
            ) if price > s.sell_trigger else 0.0

    # ------------------------------------------------------------------
    # Scanner snapshot for dashboard
    # ------------------------------------------------------------------
    def get_scanner_rows(self) -> list[dict]:
        rows = []
        for sym, s in self.states.items():
            trigger_price = None
            if s.is_gap_up and s.fifteen_min_high:
                trigger_price = s.fifteen_min_high
            elif s.is_gap_down and s.fifteen_min_low:
                trigger_price = s.fifteen_min_low
            else:
                trigger_price = s.buy_trigger  # shown as reference

            rows.append({
                "symbol": sym,
                "lot_size": s.lot_size,
                "prev_high": s.prev_high,
                "prev_low": s.prev_low,
                "prev_close": s.prev_close,
                "current_price": s.last_price,
                "buy_trigger": s.buy_trigger if not s.is_gap_up else s.fifteen_min_high,
                "sell_trigger": s.sell_trigger if not s.is_gap_down else s.fifteen_min_low,
                "is_gap_up": s.is_gap_up,
                "is_gap_down": s.is_gap_down,
                "candle_locked": s.candle_locked,
                "signal": s.signal_fired,
                "dist_to_buy_pct": s.dist_to_buy_pct,
                "dist_to_sell_pct": s.dist_to_sell_pct,
            })
        return rows

    def reset_daily(self) -> None:
        """Call at start of each new trading day to clear fired signals."""
        for s in self.states.values():
            s.signal_fired = None
            s.candle_locked = False
            s.fifteen_min_high = None
            s.fifteen_min_low = None
