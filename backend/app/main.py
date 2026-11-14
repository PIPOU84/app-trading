"""API REST de l'application (FastAPI).

Lancer : .venv\\Scripts\\python -m uvicorn app.main:app --reload --app-dir backend
Documentation interactive : http://127.0.0.1:8000/docs
"""
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analysis.indicators import add_all
from .analysis.macro import asset_macro_bias, market_regime
from .config import MAX_RISK_PCT, SCAN_HOUR, SCAN_MINUTE, SUPPORTED_ACCOUNT_CCY
from .assets import favorite_ids
from .db import SessionLocal, get_session, init_db
from .models import Asset, Setting, Signal, Snapshot, WatchlistItem
from .providers import yahoo
from .risk.sizing import size_position
from .services.analysis import analyze_asset, recommendations, run_scan, scan_one
from .services.data import fx_rate, load_prices, supported_currencies
from .services.ingest import REFRESH_STATUS, ensure_h4, refresh_all, refresh_asset

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

DISCLAIMER = ("Outil d'aide à la décision, pas un conseil en investissement. "
              "Le trading comporte un risque de perte en capital.")


def refresh_and_scan() -> None:
    REFRESH_STATUS["scanning"] = True  # avant refresh_all : l'interface attend la fin du scan
    try:
        refresh_all()
        with SessionLocal() as s:
            run_scan(s)
    finally:
        REFRESH_STATUS["scanning"] = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    scheduler = None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone="Europe/Paris")
        scheduler.add_job(refresh_and_scan, "cron", hour=SCAN_HOUR, minute=SCAN_MINUTE, id="daily_scan")
        scheduler.start()
        log.info("Scan quotidien programmé à %02d:%02d (heure de Paris)", SCAN_HOUR, SCAN_MINUTE)
    except Exception:
        log.exception("Planificateur non démarré")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="App Trading Swing", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def _asset(s: Session, symbol: str) -> Asset:
    a = s.scalar(select(Asset).where(Asset.symbol == symbol.upper()))
    if a is None:
        raise HTTPException(404, f"Actif inconnu : {symbol}")
    return a


@app.get("/api/health")
def health():
    return {"status": "ok", "disclaimer": DISCLAIMER}


@app.get("/api/assets")
def list_assets(s: Session = Depends(get_session)):
    return [dict(symbol=a.symbol, name=a.name, asset_class=a.asset_class, currency=a.currency,
                 provider_symbol=a.provider_symbol) for a in s.scalars(select(Asset).where(Asset.active))]


# ---------------------------------------------------------------- données

@app.post("/api/refresh")
def refresh(scan: bool = True):
    """Lance la mise à jour des données en arrière-plan (environ 1 minute)."""
    if REFRESH_STATUS["running"] or REFRESH_STATUS.get("scanning"):
        return REFRESH_STATUS
    threading.Thread(target=refresh_and_scan if scan else refresh_all, daemon=True).start()
    return {"started": True}


@app.get("/api/refresh/status")
def refresh_status():
    return REFRESH_STATUS


@app.get("/api/prices/{symbol}")
def prices(symbol: str, tf: str = Query("1D", pattern="^(1M|1W|1D|4H)$"), limit: int = Query(500, le=5000),
           s: Session = Depends(get_session)):
    """Bougies + moyennes mobiles, au format attendu par TradingView Lightweight Charts."""
    a = _asset(s, symbol)
    df = load_prices(s, a.id, tf)
    if df.empty:
        raise HTTPException(404, "Pas de données : lance une mise à jour.")
    df = add_all(df).tail(limit)
    t = [int(pd.Timestamp(ts).timestamp()) for ts in df.index]
    candles = [dict(time=ti, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
               for ti, r in zip(t, df.itertuples())]

    def line(col):
        return [dict(time=ti, value=float(v)) for ti, v in zip(t, df[col]) if not pd.isna(v)]

    return dict(symbol=a.symbol, timeframe=tf, candles=candles,
                overlays={k: line(k) for k in ("sma20", "sma50", "sma200")},
                rsi=line("rsi14"))


# ---------------------------------------------------------------- analyse

@app.get("/api/macro")
def macro(s: Session = Depends(get_session)):
    r = market_regime(s)
    per_asset = []
    for a in s.scalars(select(Asset).where(Asset.active)):
        b, why = asset_macro_bias(a.asset_class, a.symbol, r)
        per_asset.append(dict(symbol=a.symbol, name=a.name, bias=round(b, 2),
                              label="haussier" if b > 0.25 else "baissier" if b < -0.25 else "neutre", reasons=why))
    return dict(regime=r, assets=per_asset)


@app.get("/api/analysis/{symbol}")
def analysis(symbol: str, s: Session = Depends(get_session)):
    a = _asset(s, symbol)
    ensure_h4(s, a)  # H4 téléchargé à la demande pour les produits hors favoris
    res = analyze_asset(s, a)
    res["favorite"] = a.id in favorite_ids(s)
    res["disclaimer"] = DISCLAIMER
    return res


@app.get("/api/overview")
def overview(s: Session = Depends(get_session)):
    """Vue d'ensemble de tous les produits (lue dans les résumés du dernier scan : instantané)."""
    favs = favorite_ids(s)
    snaps = {sn.asset_id: sn.data for sn in s.scalars(select(Snapshot))}
    out = []
    for a in s.scalars(select(Asset).where(Asset.active).order_by(Asset.category, Asset.name)):
        d = snaps.get(a.id)
        if d is None:
            out.append(dict(symbol=a.symbol, name=a.name, asset_class=a.asset_class, category=a.category,
                            favorite=a.id in favs, error="Pas encore analysé : lance une mise à jour."))
        else:
            out.append({**d, "favorite": a.id in favs, "category": a.category})
    return out


@app.get("/api/recommendations")
def get_recommendations(s: Session = Depends(get_session)):
    return recommendations(s)


# ---------------------------------------------------------------- recherche, ajout, favoris, actualités

@app.get("/api/search")
def search(q: str = Query(min_length=1, max_length=50), s: Session = Depends(get_session)):
    """Recherche d'abord dans les produits suivis, puis dans tout l'univers Yahoo Finance."""
    ql = q.lower()
    local = [dict(symbol=a.symbol, name=a.name, category=a.category, provider_symbol=a.provider_symbol, tracked=True)
             for a in s.scalars(select(Asset).where(Asset.active))
             if ql in a.name.lower() or ql in a.symbol.lower() or ql in a.provider_symbol.lower()][:10]
    tracked = {r["provider_symbol"] for r in local} | set(
        s.scalars(select(Asset.provider_symbol).where(Asset.active)))
    try:
        remote = [dict(r, tracked=False) for r in yahoo.search(q) if r["provider_symbol"] not in tracked]
    except Exception:
        remote = []
    return dict(tracked=local, results=remote)


class AddAssetIn(BaseModel):
    provider_symbol: str = Field(min_length=1, max_length=30)
    name: str | None = None


QUOTE_TYPES = {"EQUITY": "Ajouts : actions", "ETF": "Ajouts : ETF", "MUTUALFUND": "Ajouts : fonds",
               "INDEX": "Ajouts : indices (CFD)", "CURRENCY": "Ajouts : forex", "FUTURE": "Ajouts : matières premières",
               "CRYPTOCURRENCY": "Ajouts : crypto"}


@app.post("/api/assets")
def add_asset(body: AddAssetIn, s: Session = Depends(get_session)):
    """Ajoute n'importe quel produit Yahoo Finance au suivi (ex. BMW.DE, ^FCHI, SOL-USD, USDMXN=X)."""
    ps = body.provider_symbol.strip().upper()
    existing = s.scalar(select(Asset).where(Asset.provider_symbol == ps))
    if existing:
        if not existing.active:
            existing.active = True
            s.commit()
        return dict(symbol=existing.symbol, existing=True)
    try:
        info = yahoo.describe(ps)
    except Exception as e:
        raise HTTPException(422, f"Produit introuvable chez Yahoo Finance : {ps} ({e})")
    qt = (info.get("quote_type") or "").upper()
    ccy, factor = info.get("currency"), 1.0
    if ccy in ("GBp", "GBX"):  # actions de Londres cotées en pence
        ccy, factor = "GBP", 0.01
    if not ccy or qt not in QUOTE_TYPES:
        raise HTTPException(422, f"Type de produit non géré ({qt or 'inconnu'}).")
    ccy = ccy.upper()
    if qt == "CURRENCY":
        ccy = ps.replace("=X", "")[3:6]
    if ccy not in supported_currencies(s):
        raise HTTPException(422, f"Devise {ccy} non gérée : ajoute d'abord la paire USD{ccy}=X pour la conversion.")

    symbol = {"CURRENCY": ps.replace("=X", ""), "CRYPTOCURRENCY": ps.split("-")[0]}.get(qt, ps)
    if s.scalar(select(Asset).where(Asset.symbol == symbol)):
        symbol = ps
    spec = dict(symbol=symbol, provider_symbol=ps, name=body.name or info.get("name") or ps, currency=ccy,
                category=QUOTE_TYPES[qt], quote_factor=factor, origin="perso")
    if qt == "CURRENCY":
        spec.update(asset_class="forex", unit_label="unités de devise de base", contract_size=100_000,
                    micro_contract_size=1_000, qty_step=1_000, pip_size=0.01 if ccy == "JPY" else 0.0001)
    elif qt == "CRYPTOCURRENCY":
        spec.update(asset_class="crypto", unit_label=symbol, qty_step=0.0001)
    elif qt == "FUTURE":
        spec.update(asset_class="commodity", unit_label="unités du sous-jacent", qty_step=0.01)
    elif qt == "INDEX":
        spec.update(asset_class="stock_us" if ccy == "USD" else "stock_eu", unit_label="CFD (par point)", qty_step=0.1)
    else:
        spec.update(asset_class="stock_us" if ccy == "USD" else "stock_eu", unit_label="titres", qty_step=1.0)
    a = Asset(**spec)
    s.add(a)
    s.commit()
    try:
        refresh_asset(s, a, hourly=True)
        s.commit()
    except Exception as e:
        s.rollback()
        s.delete(a)
        s.commit()
        raise HTTPException(422, f"Impossible de télécharger l'historique de {ps} : {e}")
    res = scan_one(s, a)
    return dict(symbol=a.symbol, existing=False, error=res.get("error"))


@app.delete("/api/assets/{symbol}")
def remove_asset(symbol: str, s: Session = Depends(get_session)):
    a = _asset(s, symbol)
    a.active = False
    s.query(WatchlistItem).filter(WatchlistItem.asset_id == a.id).delete()
    s.commit()
    return {"removed": a.symbol}


def _set_fav_flag(s: Session, a: Asset, value: bool) -> None:
    sn = s.get(Snapshot, a.id)
    if sn is not None:
        sn.data = {**sn.data, "favorite": value}


@app.post("/api/favorites/{symbol}")
def add_favorite(symbol: str, s: Session = Depends(get_session)):
    a = _asset(s, symbol)
    if a.id not in favorite_ids(s):
        s.add(WatchlistItem(watchlist_id=1, asset_id=a.id))
    _set_fav_flag(s, a, True)
    s.commit()
    return {"favorite": True}


@app.delete("/api/favorites/{symbol}")
def remove_favorite(symbol: str, s: Session = Depends(get_session)):
    a = _asset(s, symbol)
    s.query(WatchlistItem).filter(WatchlistItem.watchlist_id == 1, WatchlistItem.asset_id == a.id).delete()
    _set_fav_flag(s, a, False)
    s.commit()
    return {"favorite": False}


_NEWS_CACHE: dict[str, tuple[float, list]] = {}


@app.get("/api/news/{symbol}")
def news(symbol: str, s: Session = Depends(get_session)):
    """Dernières actualités du produit (Yahoo Finance), mises en cache 30 minutes."""
    a = _asset(s, symbol)
    hit = _NEWS_CACHE.get(a.symbol)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        items = yahoo.fetch_news(a.provider_symbol, 10)
    except Exception:
        items = []
    _NEWS_CACHE[a.symbol] = (time.time(), items)
    return items


@app.post("/api/scan")
def scan(s: Session = Depends(get_session)):
    return run_scan(s)


@app.get("/api/signals")
def signals(min_score: int = 0, s: Session = Depends(get_session)):
    rows = s.execute(select(Signal, Asset).join(Asset).where(Signal.status == "active", Signal.score >= min_score,
                                                             Asset.active).order_by(Signal.score.desc())).all()
    favs = favorite_ids(s)
    out = []
    for sig, a in rows:
        d = {c.name: getattr(sig, c.name) for c in Signal.__table__.columns}
        d.update(symbol=a.symbol, name=a.name, asset_class=a.asset_class, category=a.category,
                 favorite=a.id in favs)
        out.append(d)
    return dict(signals=out, disclaimer=DISCLAIMER)


# ---------------------------------------------------------------- risque

class SettingsIn(BaseModel):
    capital: float = Field(gt=0)
    account_currency: str = "EUR"
    risk_pct: float = Field(gt=0, le=MAX_RISK_PCT)
    max_open_risk_pct: float = Field(gt=0, le=20)


@app.get("/api/settings")
def get_settings(s: Session = Depends(get_session)):
    st = s.get(Setting, 1)
    return dict(capital=st.capital, account_currency=st.account_currency, risk_pct=st.risk_pct,
                max_open_risk_pct=st.max_open_risk_pct, max_risk_pct=MAX_RISK_PCT)


@app.put("/api/settings")
def put_settings(body: SettingsIn, s: Session = Depends(get_session)):
    if body.account_currency not in SUPPORTED_ACCOUNT_CCY:
        raise HTTPException(422, f"Devise du compte : {', '.join(SUPPORTED_ACCOUNT_CCY)}")
    st = s.get(Setting, 1)
    for k, v in body.model_dump().items():
        setattr(st, k, v)
    s.commit()
    return get_settings(s)


class SizeIn(BaseModel):
    symbol: str
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    capital: float | None = Field(default=None, gt=0)
    risk_pct: float | None = Field(default=None, gt=0)


@app.post("/api/size")
def size(body: SizeIn, s: Session = Depends(get_session)):
    a = _asset(s, body.symbol)
    st = s.get(Setting, 1)
    try:
        rate = fx_rate(s, st.account_currency, a.currency)
        return size_position(asset_class=a.asset_class, unit_label=a.unit_label, qty_step=a.qty_step,
                             contract_size=a.contract_size, micro_contract_size=a.micro_contract_size,
                             entry=body.entry, stop=body.stop, capital=body.capital or st.capital,
                             risk_pct=body.risk_pct or st.risk_pct, account_currency=st.account_currency,
                             quote_currency=a.currency, quote_per_account=rate, quote_factor=a.quote_factor or 1.0)
    except ValueError as e:
        raise HTTPException(422, str(e))


# ---------------------------------------------------------------- interface HTML
# Montée en dernier : les routes /api/* ci-dessus restent prioritaires.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
