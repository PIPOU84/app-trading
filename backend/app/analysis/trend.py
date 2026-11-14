"""Lecture de la tendance de fond (hebdomadaire) et de la tendance journalière."""
import pandas as pd

from .indicators import sma


def _label(score: int, maxi: int) -> str:
    if score >= maxi - 1:
        return "haussière"
    if score <= -(maxi - 1):
        return "baissière"
    return "neutre"


def weekly_trend(w: pd.DataFrame) -> dict:
    """Méthode « MM 30 semaines » : prix vs MM30, pente de la MM30, MM10 vs MM30. Score de -3 à +3."""
    if len(w) < 35:
        return dict(direction=0, score=0, label="inconnue", details=["Historique hebdomadaire insuffisant"])
    c = w["close"]
    m10, m30 = sma(c, 10), sma(c, 30)
    last, ma30, ma10 = c.iloc[-1], m30.iloc[-1], m10.iloc[-1]
    slope = m30.iloc[-1] - m30.iloc[-5]
    parts = [
        (1 if last > ma30 else -1, f"Clôture {'au-dessus' if last > ma30 else 'sous'} la MM30 semaines ({ma30:.4g})"),
        (1 if slope > 0 else -1, f"MM30 semaines {'montante' if slope > 0 else 'descendante'}"),
        (1 if ma10 > ma30 else -1, f"MM10 {'au-dessus' if ma10 > ma30 else 'sous'} la MM30"),
    ]
    score = sum(p[0] for p in parts)
    direction = 1 if score >= 2 else -1 if score <= -2 else 0
    return dict(direction=direction, score=score, label=_label(score, 3), ma30=float(ma30),
                details=[p[1] for p in parts])


def daily_trend(d: pd.DataFrame) -> dict:
    """d doit contenir les indicateurs (add_all)."""
    last = d.iloc[-1]
    if pd.isna(last.get("sma200")):
        return dict(direction=0, score=0, label="inconnue", details=["Historique journalier insuffisant"])
    parts = [
        (1 if last.close > last.sma200 else -1, f"Prix {'au-dessus' if last.close > last.sma200 else 'sous'} la MM200"),
        (1 if last.sma50 > last.sma200 else -1, f"MM50 {'au-dessus' if last.sma50 > last.sma200 else 'sous'} la MM200"),
        (1 if last.close > last.sma50 else -1, f"Prix {'au-dessus' if last.close > last.sma50 else 'sous'} la MM50"),
    ]
    score = sum(p[0] for p in parts)
    adx_v = float(last.adx) if not pd.isna(last.adx) else None
    details = [p[1] for p in parts]
    if adx_v is not None:
        details.append(f"ADX {adx_v:.0f} : {'tendance établie' if adx_v >= 20 else 'marché sans tendance nette'}")
    return dict(direction=1 if score >= 2 else -1 if score <= -2 else 0, score=score,
                label=_label(score, 3), adx=adx_v, details=details)
