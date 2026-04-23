from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from .database import Base


class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    capital = Column(Float, default=500000.0)
    risk_pct = Column(Float, default=3.0)
    sl_pct_intraday = Column(Float, default=1.5)
    sl_pct_nextday = Column(Float, default=3.0)
    trailing_step = Column(Float, default=3.0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Watchlist(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), unique=True, nullable=False)
    lot_size = Column(Integer, default=0)
    added_at = Column(DateTime, default=datetime.utcnow)


class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), index=True)
    direction = Column(String(10))        # BUY or SELL
    signal_type = Column(String(20))      # normal, gap_up, gap_down
    entry_price = Column(Float)
    sl_price = Column(Float)
    sl_pct = Column(Float)
    lots = Column(Integer)
    lot_size = Column(Integer)
    capital_risk = Column(Float)
    status = Column(String(20), default="pending")  # pending, executed, expired
    triggered_at = Column(DateTime, default=datetime.utcnow)


class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    symbol = Column(String(50), index=True)
    direction = Column(String(10))
    entry_price = Column(Float)
    entry_time = Column(DateTime, default=datetime.utcnow)
    sl_price = Column(Float)
    original_sl = Column(Float)
    trailing_tier = Column(Integer, default=0)
    lots = Column(Integer)
    lot_size = Column(Integer)
    current_price = Column(Float)
    pnl = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    exit_price = Column(Float, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    exit_reason = Column(String(50), nullable=True)
    status = Column(String(20), default="open")   # open, closed
    created_at = Column(DateTime, default=datetime.utcnow)
