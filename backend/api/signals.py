from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Signal, Settings, Position
from trading.paper_trader import open_position, get_open_position

router = APIRouter(prefix="/api/signals", tags=["signals"])


class ExecuteBody(BaseModel):
    current_price: float


@router.get("")
def list_signals(db: Session = Depends(get_db)):
    """Return all pending signals for today (not yet executed or expired)."""
    signals = (
        db.query(Signal)
        .filter(Signal.status == "pending")
        .order_by(Signal.triggered_at.desc())
        .all()
    )
    return [_serialize(s) for s in signals]


@router.post("/{signal_id}/execute")
def execute_signal(signal_id: int, body: ExecuteBody, db: Session = Depends(get_db)):
    """User selects a signal from the dashboard — creates a paper trade."""
    # Only one position allowed at a time
    open_pos = get_open_position(db)
    if open_pos:
        raise HTTPException(
            status_code=400,
            detail=f"Position already open: {open_pos.symbol}. Close it first.",
        )

    sig = db.query(Signal).filter(Signal.id == signal_id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")
    if sig.status != "pending":
        raise HTTPException(status_code=400, detail=f"Signal is already {sig.status}")

    settings = db.query(Settings).first()
    if not settings:
        raise HTTPException(status_code=500, detail="Settings not configured")

    signal_dict = {
        "symbol": sig.symbol,
        "direction": sig.direction,
        "entry_price": sig.entry_price,
        "sl_price": sig.sl_price,
        "lots": sig.lots,
        "lot_size": sig.lot_size,
        "current_price": body.current_price,
    }
    pos = open_position(db, signal_id=sig.id, signal=signal_dict)
    return {"message": "Position opened", "position_id": pos.id}


@router.delete("/{signal_id}")
def dismiss_signal(signal_id: int, db: Session = Depends(get_db)):
    """Dismiss / expire a signal manually."""
    sig = db.query(Signal).filter(Signal.id == signal_id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")
    sig.status = "expired"
    db.commit()
    return {"message": "Signal dismissed"}


def _serialize(s: Signal) -> dict:
    return {
        "id": s.id,
        "symbol": s.symbol,
        "direction": s.direction,
        "signal_type": s.signal_type,
        "entry_price": s.entry_price,
        "sl_price": s.sl_price,
        "sl_pct": s.sl_pct,
        "lots": s.lots,
        "lot_size": s.lot_size,
        "capital_risk": s.capital_risk,
        "status": s.status,
        "triggered_at": s.triggered_at.isoformat() if s.triggered_at else None,
    }
