"""Données Yahoo Finance (gratuites) via yfinance : actions, ETF, forex, futures, crypto."""
import logging
import time
from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)
COLS = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """OHLCV indexé par horodatage naïf.

    - Journalier : on garde la date locale du marché (sinon une séance parisienne
      à minuit heure de Paris deviendrait la veille en UTC).
    - Intraday : converti en UTC.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=COLS)
    df = df.rename(columns=lambda c: str(c).lower())
    for c in COLS:
        if c not in df.columns:
            df[c] = 0.0
    df = df[COLS].copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None) if interval.endswith("d") else idx.tz_convert("UTC").tz_localize(None)
    df.index = idx
    df.index.name = "ts"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df["volume"] = df["volume"].fillna(0.0)
    return df.dropna(subset=["open", "high", "low", "close"])


def fetch_ohlcv(provider_symbol: str, interval: str, period: str) -> pd.DataFrame:
    df = yf.Ticker(provider_symbol).history(period=period, interval=interval, auto_adjust=True, actions=False)
    return _normalize(df, interval)


def fetch_daily_batch(provider_symbols: list[str], period: str, chunk: int = 40) -> dict[str, pd.DataFrame]:
    """Télécharge le journalier de nombreux produits en quelques requêtes groupées."""
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(provider_symbols), chunk):
        part = provider_symbols[i:i + chunk]
        try:
            raw = yf.download(part, period=period, interval="1d", group_by="ticker", auto_adjust=True,
                              threads=True, progress=False)
        except Exception:
            log.exception("Téléchargement groupé échoué")
            continue
        for sym in part:
            try:
                sub = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            df = _normalize(sub, "1d")
            if not df.empty:
                out[sym] = df
        time.sleep(0.5)  # courtoisie envers le service gratuit
    return out


def fetch_close_series(provider_symbol: str, period: str = "5y") -> pd.Series:
    return fetch_ohlcv(provider_symbol, "1d", period)["close"]


def fetch_earnings_dates(provider_symbol: str) -> list[date]:
    """Prochaines dates de publication de résultats (actions). Liste vide si indisponible."""
    try:
        cal = yf.Ticker(provider_symbol).calendar
    except Exception:
        return []
    raw = cal.get("Earnings Date") if isinstance(cal, dict) else None
    if not raw:
        return []
    out = []
    for d in raw if isinstance(raw, (list, tuple)) else [raw]:
        if isinstance(d, datetime):
            out.append(d.date())
        elif isinstance(d, date):
            out.append(d)
    return out


def search(query: str, max_results: int = 10) -> list[dict]:
    """Recherche de produits par nom ou code (actions, ETF, devises, futures, crypto)."""
    res = yf.Search(query, max_results=max_results, news_count=0)
    out = []
    for q in res.quotes or []:
        out.append(dict(provider_symbol=q.get("symbol"), name=q.get("longname") or q.get("shortname") or q.get("symbol"),
                        exchange=q.get("exchDisp") or q.get("exchange"), quote_type=q.get("quoteType"),
                        sector=q.get("sectorDisp") or q.get("sector")))
    return [o for o in out if o["provider_symbol"]]


def describe(provider_symbol: str) -> dict:
    """Devise et type d'un produit, lus dans les métadonnées de son historique."""
    t = yf.Ticker(provider_symbol)
    t.history(period="5d", interval="1d")
    meta = getattr(t, "history_metadata", None) or {}
    return dict(currency=meta.get("currency"), quote_type=meta.get("instrumentType"),
                name=meta.get("longName") or meta.get("shortName") or provider_symbol)


def fetch_news(provider_symbol: str, count: int = 10) -> list[dict]:
    items = yf.Ticker(provider_symbol).get_news(count=count) or []
    out = []
    for it in items:
        c = it.get("content", it)
        title = c.get("title")
        if not title:
            continue
        url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link")
        pub = c.get("pubDate") or c.get("displayTime")
        if not pub and it.get("providerPublishTime"):
            pub = datetime.fromtimestamp(it["providerPublishTime"], tz=timezone.utc).isoformat()
        out.append(dict(title=title, url=url, published=pub,
                        source=(c.get("provider") or {}).get("displayName") or c.get("publisher"),
                        summary=c.get("summary")))
    return out
