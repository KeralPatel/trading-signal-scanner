from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Position

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def get_history(db: Session = Depends(get_db)):
    trades = (
        db.query(Position)
        .filter(Position.status == "closed")
        .order_by(Position.exit_time.desc())
        .all()
    )
    serialized = [_serialize(t) for t in trades]

    # Summary stats
    total = len(serialized)
    wins = sum(1 for t in serialized if (t["pnl"] or 0) > 0)
    total_pnl = sum(t["pnl"] or 0 for t in serialized)

    return {
        "trades": serialized,
        "stats": {
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": total - wins,
            "win_rate": round(wins / total * 100, 1) if total else 0.0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total, 2) if total else 0.0,
        },
    }


def _serialize(pos: Position) -> dict:
    duration_min: float | None = None
    if pos.entry_time and pos.exit_time:
        delta = pos.exit_time - pos.entry_time
        duration_min = round(delta.total_seconds() / 60, 1)

    return {
        "id": pos.id,
        "symbol": pos.symbol,
        "direction": pos.direction,
        "entry_price": pos.entry_price,
        "exit_price": pos.exit_price,
        "lots": pos.lots,
        "lot_size": pos.lot_size,
        "pnl": pos.pnl,
        "pnl_pct": pos.pnl_pct,
        "exit_reason": pos.exit_reason,
        "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
        "exit_time": pos.exit_time.isoformat() if pos.exit_time else None,
        "duration_min": duration_min,
    }
