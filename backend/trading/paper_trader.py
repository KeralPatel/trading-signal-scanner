"""
Paper Trader — position lifecycle management.

Trailing-stop tiers (for BUY):
  Tier 0  : initial SL (1.5% below entry)
  Tier 1  : price hits +3%  → SL moves to breakeven (entry)
  Tier 2  : price hits +6%  → SL moves to entry + 3%
  Tier N  : price hits +(N*3)% → SL = entry + (N-1)*3%

SELL mirrors BUY in the opposite direction.
On SL hit → close position flat; no reversal.
"""
from __future__ import annotations

import logging
from datetime import datetime

import pytz
from sqlalchemy.orm import Session

from db.models import Position, Signal

IST = pytz.timezone("Asia/Kolkata")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pnl(pos: Position, price: float) -> tuple[float, float]:
    multiplier = 1 if pos.direction == "BUY" else -1
    gross = multiplier * (price - pos.entry_price) * pos.lot_size * pos.lots
    pct = multiplier * (price - pos.entry_price) / pos.entry_price * 100
    return round(gross, 2), round(pct, 4)


# ---------------------------------------------------------------------------
# Main paper-trade operations
# ---------------------------------------------------------------------------

def open_position(db: Session, signal_id: int, signal: dict) -> Position:
    """Create a new open paper-trade position from a signal."""
    pos = Position(
        signal_id=signal_id,
        symbol=signal["symbol"],
        direction=signal["direction"],
        entry_price=signal["entry_price"],
        entry_time=datetime.now(IST).replace(tzinfo=None),
        sl_price=signal["sl_price"],
        original_sl=signal["sl_price"],
        trailing_tier=0,
        lots=signal["lots"],
        lot_size=signal["lot_size"],
        current_price=signal["current_price"],
        pnl=0.0,
        pnl_pct=0.0,
        status="open",
    )
    db.add(pos)

    # Mark signal as executed
    sig = db.query(Signal).filter(Signal.id == signal_id).first()
    if sig:
        sig.status = "executed"

    db.commit()
    db.refresh(pos)
    logger.info("Opened paper position: %s %s @ %.2f SL=%.2f lots=%d",
                pos.direction, pos.symbol, pos.entry_price, pos.sl_price, pos.lots)
    return pos


def update_position(db: Session, pos: Position, current_price: float, step_pct: float) -> str | None:
    """
    Called every scan tick. Updates P&L, checks SL, advances trailing stop.
    Returns exit reason string if position should close, else None.
    """
    pos.current_price = current_price
    pos.pnl, pos.pnl_pct = _pnl(pos, current_price)

    entry = pos.entry_price
    step = step_pct / 100.0  # e.g. 0.03

    if pos.direction == "BUY":
        # Advance trailing tier
        next_tier = pos.trailing_tier + 1
        tier_target = entry * (1.0 + next_tier * step)
        if current_price >= tier_target:
            pos.trailing_tier = next_tier
            if next_tier == 1:
                new_sl = entry  # breakeven
            else:
                new_sl = entry * (1.0 + (next_tier - 1) * step)
            if new_sl > pos.sl_price:  # only ratchet upward
                pos.sl_price = round(new_sl, 2)
                logger.info("Trailing stop advanced: %s SL → %.2f (tier %d)",
                            pos.symbol, pos.sl_price, pos.trailing_tier)

        # Check SL hit
        if current_price <= pos.sl_price:
            return "trailing_sl" if pos.trailing_tier > 0 else "sl_hit"

    else:  # SELL
        next_tier = pos.trailing_tier + 1
        tier_target = entry * (1.0 - next_tier * step)
        if current_price <= tier_target:
            pos.trailing_tier = next_tier
            if next_tier == 1:
                new_sl = entry  # breakeven
            else:
                new_sl = entry * (1.0 - (next_tier - 1) * step)
            if new_sl < pos.sl_price:  # only ratchet downward
                pos.sl_price = round(new_sl, 2)

        if current_price >= pos.sl_price:
            return "trailing_sl" if pos.trailing_tier > 0 else "sl_hit"

    db.commit()
    return None


def close_position(db: Session, pos: Position, exit_price: float, reason: str) -> Position:
    """Mark position as closed."""
    pos.exit_price = exit_price
    pos.exit_time = datetime.now(IST).replace(tzinfo=None)
    pos.exit_reason = reason
    pos.pnl, pos.pnl_pct = _pnl(pos, exit_price)
    pos.status = "closed"
    db.commit()
    db.refresh(pos)
    logger.info("Closed position: %s %s entry=%.2f exit=%.2f P&L=%.2f reason=%s",
                pos.direction, pos.symbol, pos.entry_price, exit_price, pos.pnl, reason)
    return pos


def get_open_position(db: Session) -> Position | None:
    return db.query(Position).filter(Position.status == "open").first()
