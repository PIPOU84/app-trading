"""Analyse complète d'un actif, scan de tous les produits et recommandations."""
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..analysis.indicators import add_all
from ..analysis.levels import find_zones
from ..analysis.macro import asset_macro_bias, market_regime
from ..analysis.trend import daily_trend, weekly_trend
from ..assets import favorite_ids
from ..models import Asset, Level, Signal, Snapshot
from ..signals.engine import build_card, detect_setups, detect_watch, price_decimals
from .data import load_prices
from .ingest import upcoming_events

CARD_FIELDS = ("direction", "setup_type", "entry_low", "entry_high", "entry_ref", "order_type", "stop", "tp1",
               "tp2", "tp3", "rr_tp1", "rr_tp2", "score", "score_breakdown", "confidence", "horizon",
               "horizon_days", "h4_confirmation", "invalidation", "warnings", "rationale")


def _round_zones(zones: list[dict], dec: int) -> list[dict]:
    out = []
    for z in zones:
        z = dict(z)
        for k in ("low", "high", "mid"):
            z[k] = round(z[k], dec)
        out.append(z)
    return out


def _perf(close: pd.Series, bars: int) -> float | None:
    if len(close) <= bars:
        return None
    return round(float(close.iloc[-1] / close.iloc[-1 - bars] - 1) * 100, 2)


def analyze_asset(s: Session, a: Asset, regime: dict | None = None) -> dict:
    d = load_prices(s, a.id, "1D", limit=700)  # ~3 ans : assez pour MM200, zones et perf 1 an
    if len(d) < 220:
        return dict(symbol=a.symbol, name=a.name, error="Historique insuffisant (moins de 220 séances).")
    d = add_all(d)
    w = load_prices(s, a.id, "1W", limit=200)
    h4 = load_prices(s, a.id, "4H", limit=300)
    atr = float(d["atr14"].iloc[-1])
    zones = find_zones(d, atr)
    wt, dt = weekly_trend(w), daily_trend(d)
    regime = regime or market_regime(s)
    bias, why = asset_macro_bias(a.asset_class, a.symbol, regime)
    events = [(e.date, e.title) for e in upcoming_events(s, a.id, date.today() + timedelta(days=120))]

    signals, rejected = [], []
    for cand in detect_setups(d, zones, wt, atr):
        card, reason = build_card(asset_class=a.asset_class, symbol=a.symbol, name=a.name, d=d,
                                  h4=h4 if len(h4) else None, cand=cand, zones=zones, atr=atr, wt=wt,
                                  macro_bias=bias, macro_why=why, events=events)
        if card:
            signals.append(card)
        else:
            rejected.append(reason)
    best: dict[str, dict] = {}  # un seul signal par direction : le mieux noté
    for c in signals:
        if c["direction"] not in best or c["score"] > best[c["direction"]]["score"]:
            best[c["direction"]] = c
    signals = sorted(best.values(), key=lambda c: c["score"], reverse=True)
    signal_dirs = {c["direction"] for c in signals}
    watch = [x for x in detect_watch(d, zones, wt, atr) if x["direction"] not in signal_dirs]

    last = d.iloc[-1]
    dec = price_decimals(a.asset_class, a.symbol, float(last.close))
    num = lambda x: None if pd.isna(x) else round(float(x), dec)  # noqa: E731
    for x in watch:
        x["level"] = round(float(x["level"]), dec)
    close = d["close"]
    ytd_base = close[close.index < pd.Timestamp(date.today().year, 1, 1)]
    return dict(
        symbol=a.symbol, name=a.name, asset_class=a.asset_class, category=a.category, currency=a.currency,
        provider_symbol=a.provider_symbol, origin=a.origin,
        bar_date=pd.Timestamp(d.index[-1]).date().isoformat(), last_close=num(last.close),
        change_pct=round(float(last.close / d["close"].iloc[-2] - 1) * 100, 2),
        perf=dict(m1=_perf(close, 21), m3=_perf(close, 63), m6=_perf(close, 126), y1=_perf(close, 252),
                  ytd=round(float(close.iloc[-1] / ytd_base.iloc[-1] - 1) * 100, 2) if len(ytd_base) else None),
        indicators=dict(sma20=num(last.sma20), sma50=num(last.sma50), sma200=num(last.sma200),
                        rsi14=None if pd.isna(last.rsi14) else round(float(last.rsi14), 1),
                        atr14=num(last.atr14), atr_pct=round(float(last.atr14 / last.close * 100), 2),
                        adx=None if pd.isna(last.adx) else round(float(last.adx), 1),
                        macd_hist=None if pd.isna(last.macd_hist) else float(last.macd_hist),
                        above_sma200=bool(last.close > last.sma200) if not pd.isna(last.sma200) else None),
        weekly_trend=wt, daily_trend=dt, zones=_round_zones(zones, dec),
        macro=dict(bias=round(bias, 2), reasons=why, regime=regime["label"]),
        events=[dict(date=e[0].isoformat(), title=e[1]) for e in events],
        signals=signals, rejected=rejected, watch=watch,
    )


def snapshot_of(res: dict, is_fav: bool) -> dict:
    return dict(
        symbol=res["symbol"], name=res["name"], asset_class=res["asset_class"], category=res["category"],
        origin=res["origin"], favorite=is_fav, last_close=res["last_close"], change_pct=res["change_pct"],
        bar_date=res["bar_date"], perf=res["perf"], weekly_trend=res["weekly_trend"]["label"],
        weekly_score=res["weekly_trend"]["score"], daily_trend=res["daily_trend"]["label"],
        rsi14=res["indicators"]["rsi14"], atr_pct=res["indicators"]["atr_pct"],
        above_sma200=res["indicators"]["above_sma200"], macro_bias=res["macro"]["bias"],
        signals=[dict(direction=c["direction"], score=c["score"], setup_label=c["setup_label"]) for c in res["signals"]],
        watch=res["watch"], events=res["events"][:2],
    )


def run_scan(s: Session) -> list[dict]:
    """Analyse tous les produits, enregistre fiches, zones et résumés. Renvoie un résumé trié par score."""
    regime = market_regime(s)
    favs = favorite_ids(s)
    now = datetime.now()
    summary = []
    for a in s.scalars(select(Asset).where(Asset.active)):
        res = analyze_asset(s, a, regime)
        if res.get("error"):
            summary.append(dict(symbol=a.symbol, name=a.name, error=res["error"]))
            continue
        s.execute(update(Signal).where(Signal.asset_id == a.id, Signal.status == "active").values(status="expired"))
        s.query(Level).filter(Level.asset_id == a.id, Level.timeframe == "1D").delete()
        for z in res["zones"]:
            s.add(Level(asset_id=a.id, timeframe="1D", kind=z["kind"], price_low=z["low"], price_high=z["high"],
                        touches=z["touches"], strength=z["strength"], detected_at=now))
        for c in res["signals"]:
            s.add(Signal(asset_id=a.id, created_at=now, bar_date=date.fromisoformat(c["bar_date"]),
                         **{k: c[k] for k in CARD_FIELDS}))
        snap = s.get(Snapshot, a.id)
        data = snapshot_of(res, a.id in favs)
        if snap is None:
            s.add(Snapshot(asset_id=a.id, updated_at=now, data=data))
        else:
            snap.updated_at, snap.data = now, data
        summary.append(dict(symbol=a.symbol, name=a.name, signals=len(res["signals"]),
                            best_score=max((c["score"] for c in res["signals"]), default=None)))
    s.commit()
    return sorted(summary, key=lambda x: x.get("best_score") or -1, reverse=True)


def scan_one(s: Session, a: Asset) -> dict:
    """Analyse et enregistre un seul produit (après un ajout)."""
    res = analyze_asset(s, a)
    if res.get("error"):
        return res
    now = datetime.now()
    s.execute(update(Signal).where(Signal.asset_id == a.id, Signal.status == "active").values(status="expired"))
    for c in res["signals"]:
        s.add(Signal(asset_id=a.id, created_at=now, bar_date=date.fromisoformat(c["bar_date"]),
                     **{k: c[k] for k in CARD_FIELDS}))
    snap = s.get(Snapshot, a.id)
    data = snapshot_of(res, a.id in favorite_ids(s))
    if snap is None:
        s.add(Snapshot(asset_id=a.id, updated_at=now, data=data))
    else:
        snap.updated_at, snap.data = now, data
    s.commit()
    return res


def recommendations(s: Session) -> dict:
    """Ce qu'un trader regarderait ce soir : signaux, setups en approche, leaders et retardataires."""
    snaps = [sn.data for sn in s.scalars(select(Snapshot).join(Asset).where(Asset.active))]

    watch = []
    for sn in snaps:
        for w in sn["watch"]:
            watch.append(dict(symbol=sn["symbol"], name=sn["name"], category=sn["category"],
                              favorite=sn["favorite"], weekly_score=sn["weekly_score"], **w))
    kind_rank = {"pullback": 0, "breakout": 1, "oversold": 2}
    watch.sort(key=lambda w: (not w["favorite"], kind_rank[w["kind"]], -abs(w["weekly_score"])))

    def momentum(sn):
        p = sn["perf"]
        vals = [v for v in (p.get("m3"), p.get("m6")) if v is not None]
        return sum(vals) / len(vals) if vals else None

    groups: dict[str, dict] = {}
    labels = {"stock_us": "Actions US", "stock_eu": "Actions Europe", "forex": "Forex",
              "commodity": "Matières premières", "crypto": "Crypto"}
    for cls, label in labels.items():
        pool = [(momentum(sn), sn) for sn in snaps if sn["asset_class"] == cls and momentum(sn) is not None]
        leaders = [dict(symbol=sn["symbol"], name=sn["name"], momentum=round(m, 2), perf=sn["perf"],
                        weekly_trend=sn["weekly_trend"], rsi14=sn["rsi14"])
                   for m, sn in sorted(pool, key=lambda t: t[0], reverse=True)
                   if sn["weekly_score"] >= 2 and sn["above_sma200"]][:5]
        laggards = [dict(symbol=sn["symbol"], name=sn["name"], momentum=round(m, 2), perf=sn["perf"],
                         weekly_trend=sn["weekly_trend"], rsi14=sn["rsi14"])
                    for m, sn in sorted(pool, key=lambda t: t[0])
                    if sn["weekly_score"] <= -2 and sn["above_sma200"] is False][:5]
        groups[cls] = dict(label=label, leaders=leaders, laggards=laggards)

    upcoming = []
    for sn in snaps:
        for e in sn.get("events", []):
            if date.fromisoformat(e["date"]) <= date.today() + timedelta(days=14):
                upcoming.append(dict(symbol=sn["symbol"], name=sn["name"], **e))
    upcoming.sort(key=lambda e: e["date"])
    return dict(watch=watch[:30], momentum=groups, upcoming_events=upcoming, scanned=len(snaps))
