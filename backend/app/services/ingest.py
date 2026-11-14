"""Téléchargement et stockage des données (prix, macro, dates de résultats)."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from ..assets import MACRO_SERIES, favorite_ids
from ..config import DAILY_PERIOD, HOURLY_PERIOD
from ..db import SessionLocal
from ..models import Asset, Event, MacroPoint, Price
from ..providers import fred, yahoo

log = logging.getLogger(__name__)

AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

REFRESH_STATUS: dict = {"running": False, "scanning": False, "started_at": None, "finished_at": None,
                        "errors": [], "done": 0, "total": 0, "step": ""}


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df.resample(rule).agg(AGG).dropna(subset=["open", "close"])


def store_prices(s: Session, asset_id: int, timeframe: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    s.execute(delete(Price).where(Price.asset_id == asset_id, Price.timeframe == timeframe))
    rows = [dict(asset_id=asset_id, timeframe=timeframe, ts=ts.to_pydatetime(),
                 open=float(r.open), high=float(r.high), low=float(r.low), close=float(r.close),
                 volume=float(r.volume)) for ts, r in zip(df.index, df.itertuples())]
    s.execute(insert(Price), rows)
    return len(rows)


def store_daily(s: Session, a: Asset, daily: pd.DataFrame) -> None:
    week_rule = "W-SUN" if a.asset_class == "crypto" else "W-FRI"
    store_prices(s, a.id, "1D", daily)
    store_prices(s, a.id, "1W", resample(daily, week_rule))
    store_prices(s, a.id, "1M", resample(daily, "MS"))


def store_earnings(s: Session, a: Asset, dates: list[date]) -> None:
    s.execute(delete(Event).where(Event.asset_id == a.id, Event.kind == "earnings"))
    for d in dates:
        s.add(Event(asset_id=a.id, date=d, kind="earnings", title=f"Résultats {a.name}", importance=3))


def refresh_asset(s: Session, a: Asset, hourly: bool = True) -> None:
    """Mise à jour complète d'un seul actif (utilisée pour un produit ajouté ou ouvert à la demande)."""
    daily = yahoo.fetch_ohlcv(a.provider_symbol, "1d", DAILY_PERIOD)
    if daily.empty:
        raise RuntimeError(f"Aucune donnée journalière pour {a.provider_symbol}")
    store_daily(s, a, daily)
    if hourly:
        store_prices(s, a.id, "4H", resample(yahoo.fetch_ohlcv(a.provider_symbol, "1h", HOURLY_PERIOD), "4h"))
    if _has_earnings(a):
        store_earnings(s, a, yahoo.fetch_earnings_dates(a.provider_symbol))


def _has_earnings(a: Asset) -> bool:
    """Seules les actions publient des résultats (pas les ETF, fonds ni indices)."""
    cat = (a.category or "").lower()
    return a.asset_class.startswith("stock") and not any(k in cat for k in ("etf", "fonds", "indices"))


def ensure_h4(s: Session, a: Asset, max_age_days: int = 2) -> None:
    """Télécharge le H4 d'un actif hors favoris quand on ouvre sa page (si absent ou trop ancien)."""
    last = s.scalar(select(func.max(Price.ts)).where(Price.asset_id == a.id, Price.timeframe == "4H"))
    if last is None or datetime.now() - last > timedelta(days=max_age_days):
        try:
            df = resample(yahoo.fetch_ohlcv(a.provider_symbol, "1h", HOURLY_PERIOD), "4h")
            store_prices(s, a.id, "4H", df)
            s.commit()
        except Exception:
            s.rollback()
            log.exception("H4 indisponible pour %s", a.symbol)


def refresh_macro(s: Session) -> list[str]:
    errors = []
    for sid, source, code in MACRO_SERIES:
        try:
            ser = yahoo.fetch_close_series(code) if source == "yahoo" else fred.fetch_series(code)
            if ser.empty:
                raise RuntimeError("série vide")
            s.execute(delete(MacroPoint).where(MacroPoint.series_id == sid))
            s.execute(insert(MacroPoint), [dict(series_id=sid, date=pd.Timestamp(d).date(), value=float(v))
                                           for d, v in ser.items()])
        except Exception as e:  # une série manquante ne doit pas bloquer le reste
            errors.append(f"Macro {sid} : {e}")
    return errors


def refresh_all() -> dict:
    """Met à jour tous les produits + la macro. Journalier groupé ; H4 pour les favoris seulement."""
    if REFRESH_STATUS["running"]:
        return REFRESH_STATUS
    REFRESH_STATUS.update(running=True, started_at=datetime.now().isoformat(timespec="seconds"),
                          finished_at=None, errors=[], done=0, step="Cours journaliers")
    try:
        with SessionLocal() as s:
            assets = list(s.scalars(select(Asset).where(Asset.active)))
            favs = favorite_ids(s)
            REFRESH_STATUS["total"] = len(assets)

            batch = yahoo.fetch_daily_batch([a.provider_symbol for a in assets], DAILY_PERIOD)
            for a in assets:
                df = batch.get(a.provider_symbol)
                try:
                    if df is None or df.empty:  # repli : téléchargement individuel
                        df = yahoo.fetch_ohlcv(a.provider_symbol, "1d", DAILY_PERIOD)
                    if df.empty:
                        raise RuntimeError("aucune donnée")
                    store_daily(s, a, df)
                    s.commit()
                except Exception as e:
                    s.rollback()
                    REFRESH_STATUS["errors"].append(f"{a.symbol} ({a.provider_symbol}) : {e}")
                REFRESH_STATUS["done"] += 1

            REFRESH_STATUS["step"] = "H4 des favoris et dates de résultats"
            fav_assets = [a for a in assets if a.id in favs]
            stocks = [a for a in assets if _has_earnings(a)]
            with ThreadPoolExecutor(max_workers=6) as pool:
                h4 = dict(zip([a.id for a in fav_assets], pool.map(
                    lambda a: _safe(lambda: yahoo.fetch_ohlcv(a.provider_symbol, "1h", HOURLY_PERIOD)), fav_assets)))
                earn = dict(zip([a.id for a in stocks], pool.map(
                    lambda a: _safe(lambda: yahoo.fetch_earnings_dates(a.provider_symbol)) or [], stocks)))
            for a in fav_assets:
                if h4.get(a.id) is not None:
                    store_prices(s, a.id, "4H", resample(h4[a.id], "4h"))
            for a in stocks:
                store_earnings(s, a, earn.get(a.id, []))
            s.commit()

            REFRESH_STATUS["step"] = "Données macro"
            REFRESH_STATUS["errors"] += refresh_macro(s)
            s.commit()
    finally:
        REFRESH_STATUS.update(running=False, step="", finished_at=datetime.now().isoformat(timespec="seconds"))
    return REFRESH_STATUS


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def upcoming_events(s: Session, asset_id: int, until: date) -> list[Event]:
    return list(s.scalars(select(Event).where(Event.asset_id == asset_id, Event.date >= date.today(),
                                              Event.date <= until).order_by(Event.date)))
