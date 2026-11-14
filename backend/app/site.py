"""Page du soir : génère un site statique (HTML + data.json) consultable sur téléphone sans serveur.

La page est publique (GitHub Pages) : elle ne contient AUCUNE donnée personnelle
(ni capital, ni taille de position), seulement l'analyse de marché du jour.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analysis.indicators import sma
from .analysis.macro import market_regime
from .models import Asset, Level, Signal
from .services.analysis import recommendations
from .services.data import load_prices
from .signals.engine import SETUP_LABELS, price_decimals

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "site_template"
CHART_BARS = 160


def _chart(s: Session, a: Asset) -> dict:
    df = load_prices(s, a.id, "1D", limit=CHART_BARS + 60)
    if df.empty:
        return {}
    df["sma20"], df["sma50"] = sma(df["close"], 20), sma(df["close"], 50)
    df = df.tail(CHART_BARS)
    dec = price_decimals(a.asset_class, a.symbol, float(df["close"].iloc[-1]))
    t = [int(pd.Timestamp(ts).timestamp()) for ts in df.index]
    r = lambda v: round(float(v), dec)  # noqa: E731
    zones = [dict(price=r((z.price_low + z.price_high) / 2), kind=z.kind)
             for z in s.scalars(select(Level).where(Level.asset_id == a.id, Level.timeframe == "1D"))]
    return dict(
        precision=dec,
        candles=[[ti, r(o), r(h), r(lo), r(c)] for ti, o, h, lo, c in
                 zip(t, df["open"], df["high"], df["low"], df["close"])],
        sma20=[[ti, r(v)] for ti, v in zip(t, df["sma20"]) if not pd.isna(v)],
        sma50=[[ti, r(v)] for ti, v in zip(t, df["sma50"]) if not pd.isna(v)],
        zones=zones,
    )


def build_data(s: Session) -> dict:
    r = market_regime(s)
    reco = recommendations(s)
    assets = {a.symbol: a for a in s.scalars(select(Asset))}

    signals = []
    for sig, a in s.execute(select(Signal, Asset).join(Asset).where(Signal.status == "active", Asset.active)
                            .order_by(Signal.score.desc())).all():
        signals.append(dict(
            symbol=a.symbol, name=a.name, category=a.category, direction=sig.direction,
            setup=SETUP_LABELS.get(sig.setup_type, sig.setup_type), score=sig.score,
            breakdown=sig.score_breakdown, confidence=sig.confidence, entry_low=sig.entry_low,
            entry_high=sig.entry_high, entry_ref=sig.entry_ref, order_type=sig.order_type, stop=sig.stop,
            tp1=sig.tp1, tp2=sig.tp2, tp3=sig.tp3, rr_tp1=sig.rr_tp1, rr_tp2=sig.rr_tp2, horizon=sig.horizon,
            h4=sig.h4_confirmation, invalidation=sig.invalidation, warnings=sig.warnings, rationale=sig.rationale,
            chart=_chart(s, a)))

    watch = []
    for w in reco["watch"][:12]:
        a = assets.get(w["symbol"])
        watch.append(dict(w, chart=_chart(s, a) if a else {}))

    return dict(
        generated_at=datetime.now().isoformat(timespec="minutes"),
        regime=dict(label=r["label"], notes=r["notes"]),
        signals=signals, watch=watch, momentum=reco["momentum"],
        events=reco["upcoming_events"], scanned=reco["scanned"],
    )


def build_site(s: Session, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(TEMPLATE_DIR, out)
    shutil.copy(ROOT / "frontend" / "style.css", out / "style.css")
    shutil.copy(ROOT / "frontend" / "icon.svg", out / "icon.svg")
    (out / "data.json").write_text(json.dumps(build_data(s), ensure_ascii=False, separators=(",", ":")),
                                   encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages : servir les fichiers tels quels
    return out
