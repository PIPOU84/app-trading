"""Lecture des données stockées (prix, séries macro, taux de change)."""
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Asset, MacroPoint, Price


def load_prices(s: Session, asset_id: int, timeframe: str, limit: int | None = None) -> pd.DataFrame:
    """Lecture directe via pandas (bien plus rapide que l'ORM pour des milliers de bougies)."""
    sql = ("SELECT ts, open, high, low, close, volume FROM prices WHERE asset_id = ? AND timeframe = ? "
           "ORDER BY ts DESC" + (f" LIMIT {int(limit)}" if limit else ""))
    dbapi = s.connection().connection.driver_connection
    df = pd.read_sql_query(sql, dbapi, params=(asset_id, timeframe))
    df["ts"] = pd.to_datetime(df["ts"])
    return df.set_index("ts").sort_index()


def load_macro(s: Session, series_id: str, limit: int = 400) -> pd.Series:
    rows = s.execute(select(MacroPoint.date, MacroPoint.value).where(MacroPoint.series_id == series_id)
                     .order_by(MacroPoint.date.desc()).limit(limit)).all()
    if not rows:
        return pd.Series(dtype=float, name=series_id)
    ser = pd.Series({pd.Timestamp(d): v for d, v in rows}, name=series_id)
    return ser.sort_index()


def _last_close(s: Session, symbol: str) -> float | None:
    a = s.scalar(select(Asset).where(Asset.symbol == symbol))
    if a is None:
        return None
    return s.scalar(select(Price.close).where(Price.asset_id == a.id, Price.timeframe == "1D")
                    .order_by(Price.ts.desc()).limit(1))


def usd_per(s: Session, ccy: str) -> float:
    """Combien de dollars vaut 1 unité de la devise."""
    if ccy == "USD":
        return 1.0
    px = _last_close(s, f"{ccy}USD")
    if px:
        return px
    px = _last_close(s, f"USD{ccy}")
    if px:
        return 1 / px
    raise ValueError(f"Taux de change {ccy}/USD indisponible : lance une mise à jour des données "
                     f"(ou ajoute la paire USD{ccy} au suivi).")


def supported_currencies(s: Session) -> set[str]:
    out = {"USD"}
    for sym in s.scalars(select(Asset.symbol).where(Asset.asset_class == "forex")):
        if sym.endswith("USD"):
            out.add(sym[:3])
        elif sym.startswith("USD"):
            out.add(sym[3:])
    return out


def fx_rate(s: Session, from_ccy: str, to_ccy: str) -> float:
    """Nombre d'unités de `to_ccy` pour 1 unité de `from_ccy`."""
    if from_ccy == to_ccy:
        return 1.0
    return usd_per(s, from_ccy) / usd_per(s, to_ccy)
