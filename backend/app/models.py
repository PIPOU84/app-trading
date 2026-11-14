"""Schéma de la base de données."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True)
    provider_symbol: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    asset_class: Mapped[str] = mapped_column(String(20))  # stock_us, stock_eu, forex, commodity, crypto
    currency: Mapped[str] = mapped_column(String(3))       # devise de cotation (P&L)
    unit_label: Mapped[str] = mapped_column(String(30), default="unités")
    contract_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    micro_contract_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    pip_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty_step: Mapped[float] = mapped_column(Float, default=1.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    category: Mapped[str] = mapped_column(String(40), default="Autres")
    # Multiplicateur cours -> devise (ex. céréales cotées en cents : 0,01 ; actions de Londres en pence : 0,01)
    quote_factor: Mapped[float] = mapped_column(Float, default=1.0)
    origin: Mapped[str] = mapped_column(String(10), default="catalogue")  # catalogue, perso


class Snapshot(Base):
    """Résumé d'analyse par actif, recalculé à chaque scan (écrans Marchés et Recommandations)."""
    __tablename__ = "snapshots"
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    data: Mapped[dict] = mapped_column(JSON)


class Price(Base):
    __tablename__ = "prices"
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(3), primary_key=True)  # 1M, 1W, 1D, 4H
    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)


class Level(Base):
    __tablename__ = "levels"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    timeframe: Mapped[str] = mapped_column(String(3))
    kind: Mapped[str] = mapped_column(String(20))  # support, resistance, pivot
    price_low: Mapped[float] = mapped_column(Float)
    price_high: Mapped[float] = mapped_column(Float)
    touches: Mapped[int] = mapped_column(Integer)
    strength: Mapped[float] = mapped_column(Float)
    detected_at: Mapped[datetime] = mapped_column(DateTime)


class MacroPoint(Base):
    __tablename__ = "macro_series"
    series_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # VIX, DXY, US10Y...
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class CotReport(Base):  # phase 2
    __tablename__ = "cot_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    report_date: Mapped[date] = mapped_column(Date)
    noncomm_long: Mapped[float] = mapped_column(Float)
    noncomm_short: Mapped[float] = mapped_column(Float)
    comm_long: Mapped[float] = mapped_column(Float)
    comm_short: Mapped[float] = mapped_column(Float)
    net_percentile_3y: Mapped[float | None] = mapped_column(Float, nullable=True)


class News(Base):  # phase 2
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime)
    sentiment: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))  # earnings, central_bank, macro
    title: Mapped[str] = mapped_column(String(200))
    importance: Mapped[int] = mapped_column(Integer, default=2)


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    bar_date: Mapped[date] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(String(5))  # long, short
    setup_type: Mapped[str] = mapped_column(String(30))
    entry_low: Mapped[float] = mapped_column(Float)
    entry_high: Mapped[float] = mapped_column(Float)
    entry_ref: Mapped[float] = mapped_column(Float)
    order_type: Mapped[str] = mapped_column(String(100))
    stop: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[float] = mapped_column(Float)
    tp3: Mapped[float] = mapped_column(Float)
    rr_tp1: Mapped[float] = mapped_column(Float)
    rr_tp2: Mapped[float] = mapped_column(Float)
    score: Mapped[int] = mapped_column(Integer)
    score_breakdown: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[str] = mapped_column(String(10))
    horizon: Mapped[str] = mapped_column(String(60))
    horizon_days: Mapped[int] = mapped_column(Integer)
    h4_confirmation: Mapped[bool] = mapped_column(Boolean)
    invalidation: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)
    rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active, expired


class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    capital: Mapped[float] = mapped_column(Float)
    account_currency: Mapped[str] = mapped_column(String(3))
    risk_pct: Mapped[float] = mapped_column(Float)
    max_open_risk_pct: Mapped[float] = mapped_column(Float)


class Watchlist(Base):  # phase 2
    __tablename__ = "watchlists"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class WatchlistItem(Base):  # phase 2
    __tablename__ = "watchlist_items"
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id"), primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), primary_key=True)
