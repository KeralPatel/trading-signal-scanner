from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Watchlist

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class AddSymbolBody(BaseModel):
    symbol: str
    lot_size: int = 0   # 0 = auto-lookup from NSE CSV


@router.get("")
def list_watchlist(db: Session = Depends(get_db)):
    items = db.query(Watchlist).order_by(Watchlist.symbol).all()
    return [_serialize(w) for w in items]


@router.post("")
def add_symbol(body: AddSymbolBody, db: Session = Depends(get_db)):
    sym = body.symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol cannot be empty")

    existing = db.query(Watchlist).filter(Watchlist.symbol == sym).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"{sym} is already in the watchlist")

    lot_size = body.lot_size
    if lot_size == 0:
        lot_size = _lookup_lot_size(sym)

    entry = Watchlist(symbol=sym, lot_size=lot_size)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _serialize(entry)


@router.put("/{symbol}/lot-size")
def update_lot_size(symbol: str, lot_size: int, db: Session = Depends(get_db)):
    sym = symbol.upper()
    entry = db.query(Watchlist).filter(Watchlist.symbol == sym).first()
    if not entry:
        raise HTTPException(status_code=404, detail=f"{sym} not in watchlist")
    entry.lot_size = lot_size
    db.commit()
    return _serialize(entry)


@router.delete("/{symbol}")
def remove_symbol(symbol: str, db: Session = Depends(get_db)):
    sym = symbol.upper()
    entry = db.query(Watchlist).filter(Watchlist.symbol == sym).first()
    if not entry:
        raise HTTPException(status_code=404, detail=f"{sym} not in watchlist")
    db.delete(entry)
    db.commit()
    return {"message": f"{sym} removed"}


def _lookup_lot_size(symbol: str) -> int:
    """Try to fetch lot size from NSE archives CSV. Returns 0 if not found."""
    try:
        from data.nse_client import NSEClient
        client = NSEClient()
        lot_map = client.get_lot_sizes()
        return lot_map.get(symbol, 0)
    except Exception:
        return 0


def _serialize(w: Watchlist) -> dict:
    return {
        "symbol": w.symbol,
        "lot_size": w.lot_size,
        "added_at": w.added_at.isoformat() if w.added_at else None,
    }
