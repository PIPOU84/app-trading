"""Régime de marché (risk-on / risk-off, dollar, taux) et biais macro par actif."""
import pandas as pd
from sqlalchemy.orm import Session

from ..services.data import load_macro


def _last(ser: pd.Series):
    return float(ser.iloc[-1]) if len(ser) else None


def market_regime(s: Session) -> dict:
    vix, dxy = load_macro(s, "VIX"), load_macro(s, "DXY")
    us10, us2 = load_macro(s, "US10Y"), load_macro(s, "US2Y")
    fed, ecb = load_macro(s, "FED"), load_macro(s, "ECB")
    notes: list[str] = []

    risk = 0.0
    if len(vix) >= 50:
        v, v50 = _last(vix), float(vix.tail(50).mean())
        risk = 1.0 if v < 16 else -1.0 if v > 25 else 0.0
        if v > 1.2 * v50:
            risk -= 0.5
            notes.append(f"VIX en hausse rapide ({v:.1f} vs moyenne 50 j {v50:.1f}) : nervosité")
        notes.append(f"VIX {v:.1f} : " + ("marché serein" if v < 16 else "stress élevé" if v > 25 else "volatilité normale"))
    risk = max(-1.0, min(1.0, risk))

    dollar = 0.0
    if len(dxy) >= 60:
        d, m50 = _last(dxy), dxy.rolling(50).mean()
        slope = float(m50.iloc[-1] - m50.iloc[-10])
        dollar = 1.0 if d > m50.iloc[-1] and slope > 0 else -1.0 if d < m50.iloc[-1] and slope < 0 else 0.0
        notes.append(f"Dollar (DXY {d:.1f}) : " + {1.0: "fort", -1.0: "faible", 0.0: "sans direction"}[dollar])

    yields = 0.0
    spread = None
    if len(us10) >= 25:
        chg = float(us10.iloc[-1] - us10.iloc[-21])
        yields = 1.0 if chg > 0.25 else -1.0 if chg < -0.25 else 0.0
        notes.append(f"Taux US 10 ans {_last(us10):.2f} % ({chg:+.2f} pt sur 1 mois)")
        if len(us2):
            spread = _last(us10) - _last(us2)
            notes.append(f"Courbe 10 ans - 2 ans : {spread:+.2f} pt" + (" (inversée : signal de prudence)" if spread < 0 else ""))
    if len(fed) and len(ecb):
        notes.append(f"Taux directeurs : Fed {_last(fed):.2f} %, BCE {_last(ecb):.2f} % (écart {_last(fed) - _last(ecb):+.2f} pt)")

    label = "risk-on" if risk > 0.25 else "risk-off" if risk < -0.25 else "neutre"
    return dict(label=label, risk=risk, dollar=dollar, yields=yields, spread_10_2=spread,
                vix=_last(vix), dxy=_last(dxy), us10y=_last(us10), us2y=_last(us2),
                fed=_last(fed), ecb=_last(ecb), notes=notes, available=bool(len(vix) or len(dxy) or len(us10)))


SAFE_HAVENS = {"JPY", "CHF"}
PRECIOUS = {"XAUUSD", "XAGUSD", "PLAT"}
GROWTH_COMMODITIES = {"WTI", "BRENT", "COPPER"}


def asset_macro_bias(asset_class: str, symbol: str, r: dict) -> tuple[float, list[str]]:
    """Biais macro de -1 (vent contraire pour un achat) à +1 (vent favorable)."""
    risk, dollar, yields = r["risk"], r["dollar"], r["yields"]
    why: list[str] = []
    if asset_class in ("stock_us", "stock_eu"):
        b = 0.7 * risk - 0.3 * yields
        why.append(f"Actions : sensibles au régime {r['label']}" + (", hausse des taux = frein" if yields > 0 else ""))
    elif asset_class == "crypto":
        b = 0.7 * risk - 0.3 * dollar
        why.append("Crypto : actif très « risk-on », pénalisé par un dollar fort")
    elif asset_class == "forex":
        base, quote = symbol[:3], symbol[3:6]
        if quote == "USD":
            b = -0.8 * dollar + 0.2 * risk
            why.append(f"{base}/USD : évolue à l'inverse du dollar")
        elif base == "USD":
            b = 0.6 * dollar + (0.3 * risk + 0.1 * yields if quote in SAFE_HAVENS else 0.0)
            why.append(f"USD/{quote} : suit la force du dollar"
                       + (" et l'appétit pour le risque (devise refuge en face)" if quote in SAFE_HAVENS else ""))
        else:
            b = 0.5 * risk if quote in SAFE_HAVENS else 0.0
            why.append(f"Paire croisée {base}/{quote} : "
                       + ("monte quand les marchés sont confiants (carry trade)" if quote in SAFE_HAVENS
                          else "peu sensible au dollar, dépend surtout des deux économies"))
    elif symbol in PRECIOUS:
        b = -0.4 * dollar - 0.3 * yields - 0.3 * risk
        why.append("Métal précieux : profite d'un dollar faible, de taux en baisse et des phases de stress")
    elif symbol in GROWTH_COMMODITIES:
        b = 0.6 * risk - 0.4 * dollar
        why.append("Matière première cyclique : suit la croissance (risk-on), pénalisée par un dollar fort")
    elif asset_class == "commodity":
        b = -0.4 * dollar
        why.append("Matière première : surtout liée à l'offre et à la demande (météo, stocks) ; "
                   "un dollar fort pèse sur les prix")
    else:
        b = 0.0
    return max(-1.0, min(1.0, b)), why
