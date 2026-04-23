from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsBody(BaseModel):
    capital: float = Field(gt=0)
    risk_pct: float = Field(gt=0, le=100)
    sl_pct_intraday: float = Field(gt=0, le=100)
    sl_pct_nextday: float = Field(gt=0, le=100)
    trailing_step: float = Field(gt=0, le=100)


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    s = _get_or_create(db)
    return _serialize(s)


@router.put("")
def update_settings(body: SettingsBody, db: Session = Depends(get_db)):
    s = _get_or_create(db)
    s.capital = body.capital
    s.risk_pct = body.risk_pct
    s.sl_pct_intraday = body.sl_pct_intraday
    s.sl_pct_nextday = body.sl_pct_nextday
    s.trailing_step = body.trailing_step
    s.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(s)
    return _serialize(s)


def _get_or_create(db: Session) -> Settings:
    s = db.query(Settings).first()
    if not s:
        s = Settings()
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _serialize(s: Settings) -> dict:
    return {
        "capital": s.capital,
        "risk_pct": s.risk_pct,
        "sl_pct_intraday": s.sl_pct_intraday,
        "sl_pct_nextday": s.sl_pct_nextday,
        "trailing_step": s.trailing_step,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
