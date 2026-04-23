from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Position
from trading.paper_trader import close_position, get_open_position

router = APIRouter(prefix="/api/position", tags=["position"])


@router.get("")
def get_position(db: Session = Depends(get_db)):
    """Return the current open position or null."""
    pos = get_open_position(db)
    if not pos:
        return None
    return _serialize(pos)


@router.post("/exit")
def exit_position(db: Session = Depends(get_db)):
    """Manually exit the open position at current price."""
    pos = get_open_position(db)
    if not pos:
        raise HTTPException(status_code=404, detail="No open position")
    pos = close_position(db, pos, exit_price=pos.current_price, reason="manual_exit")
    return {"message": "Position closed", "pnl": pos.pnl}


def _serialize(pos: Position) -> dict:
    return {
        "id": pos.id,
        "symbol": pos.symbol,
        "direction": pos.direction,
        "entry_price": pos.entry_price,
        "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
        "sl_price": pos.sl_price,
        "original_sl": pos.original_sl,
        "trailing_tier": pos.trailing_tier,
        "lots": pos.lots,
        "lot_size": pos.lot_size,
        "current_price": pos.current_price,
        "pnl": pos.pnl,
        "pnl_pct": pos.pnl_pct,
        "status": pos.status,
    }
