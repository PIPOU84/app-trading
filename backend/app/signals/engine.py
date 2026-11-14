"""Moteur de signaux : détecte les setups swing et construit les fiches de trade.

Trois setups (achat et vente) :
- pullback      : repli sur une moyenne mobile ou un support, dans le sens de la tendance
- breakout_retest : cassure d'une zone puis retour tester cette zone par l'autre côté
- divergence    : nouveau creux (sommet) sur un support (résistance) non confirmé par le RSI
"""
import math
from datetime import date, timedelta

import pandas as pd

from ..analysis.indicators import ema
from ..analysis.levels import swing_points
from ..config import (ENTRY_ZONE_HALF_WIDTH_ATR, MIN_RR, STOP_MAX_DISTANCE_ATR,
                      STOP_MIN_DISTANCE_ATR, STOP_STRUCTURE_BUFFER_ATR)

SETUP_LABELS = {
    "pullback": "Pullback dans la tendance",
    "breakout_retest": "Cassure + retest",
    "divergence": "Retournement sur divergence RSI",
}
SCORE_MAX = {"tendance": 30, "setup": 30, "rr": 15, "macro": 15, "momentum": 10}


def price_decimals(asset_class: str, symbol: str, price: float) -> int:
    if asset_class == "forex":
        return 3 if "JPY" in symbol else 5
    if price < 1:
        return 5
    if price < 10:
        return 4
    return 2


# ---------------------------------------------------------------- détection

def _pullback(d: pd.DataFrame, zones: list[dict], wt: dict, atr: float, side: int) -> dict | None:
    last, prev = d.iloc[-1], d.iloc[-2]
    c = last.close
    if side == 1:
        if not (wt["direction"] >= 0 and c > last.sma200 and last.sma50 > last.sma200):
            return None
        levels = [("la MM20", last.sma20, 2), ("la MM50", last.sma50, 3)] + [
            (f"le support {z['low']:.5g}–{z['high']:.5g}", z["high"], min(6, 2 * z["touches"]))
            for z in zones if z["kind"] == "support"]
        low3 = d["low"].tail(3).min()
        touched = [lv for lv in levels if lv[1] < c and low3 <= lv[1] + 0.5 * atr and c - lv[1] <= 1.5 * atr]
        rsi_ok = 35 <= last.rsi14 <= 62 and (last.rsi14 > prev.rsi14 or c > last.open)
        if not (touched and rsi_ok):
            return None
        name, lvl, st = max(touched, key=lambda t: t[1])
        structure = d["low"].tail(10).min()
    else:
        if not (wt["direction"] <= 0 and c < last.sma200 and last.sma50 < last.sma200):
            return None
        levels = [("la MM20", last.sma20, 2), ("la MM50", last.sma50, 3)] + [
            (f"la résistance {z['low']:.5g}–{z['high']:.5g}", z["low"], min(6, 2 * z["touches"]))
            for z in zones if z["kind"] == "resistance"]
        high3 = d["high"].tail(3).max()
        touched = [lv for lv in levels if lv[1] > c and high3 >= lv[1] - 0.5 * atr and lv[1] - c <= 1.5 * atr]
        rsi_ok = 38 <= last.rsi14 <= 65 and (last.rsi14 < prev.rsi14 or c < last.open)
        if not (touched and rsi_ok):
            return None
        name, lvl, st = min(touched, key=lambda t: t[1])
        structure = d["high"].tail(10).max()
    return dict(direction=side, setup="pullback", anchor=float(lvl), structure=float(structure),
                level_desc=name, level_strength=st)


def _breakout_retest(d: pd.DataFrame, zones: list[dict], atr: float, side: int) -> dict | None:
    c = d["close"].iloc[-1]
    window, before = d.iloc[-15:-1], d.iloc[-25:-15]
    best = None
    for z in zones:
        if side == 1:
            if c <= z["high"]:
                continue
            broke = (window["close"] > z["high"]).any() and before["close"].max() < z["high"]
            retest = d["low"].tail(3).min() <= z["high"] + 0.3 * atr and c - z["high"] <= 1.5 * atr
            anchor, structure = z["high"], min(d["low"].tail(5).min(), z["low"])
        else:
            if c >= z["low"]:
                continue
            broke = (window["close"] < z["low"]).any() and before["close"].min() > z["low"]
            retest = d["high"].tail(3).max() >= z["low"] - 0.3 * atr and z["low"] - c <= 1.5 * atr
            anchor, structure = z["low"], max(d["high"].tail(5).max(), z["high"])
        if broke and retest and (best is None or z["strength"] > best[0]["strength"]):
            best = (z, anchor, structure)
    if best is None:
        return None
    z, anchor, structure = best
    return dict(direction=side, setup="breakout_retest", anchor=float(anchor), structure=float(structure),
                level_desc=f"la zone {z['low']:.5g}–{z['high']:.5g}", level_strength=min(6, 2 * z["touches"]))


def _divergence(d: pd.DataFrame, zones: list[dict], atr: float, side: int) -> dict | None:
    sub = d.tail(60)
    sw = swing_points(sub, 3, 2)
    kind = "low" if side == 1 else "high"
    pts = sw[sw["kind"] == kind]
    if len(pts) < 2:
        return None
    p1, p2 = pts.iloc[-2], pts.iloc[-1]
    if p2.pos < len(sub) - 8 or p2.pos - p1.pos < 5:
        return None
    r1, r2 = sub["rsi14"].iloc[int(p1.pos)], sub["rsi14"].iloc[int(p2.pos)]
    last = sub.iloc[-1]
    if side == 1:
        ok = p2.price <= p1.price + 0.3 * atr and r2 > r1 + 3 and r2 < 45 \
            and last.close > p2.price + 0.5 * atr and last.close > last.open
        near = [z for z in zones if z["low"] - 0.3 * atr <= p2.price <= z["high"] + 0.3 * atr]
    else:
        ok = p2.price >= p1.price - 0.3 * atr and r2 < r1 - 3 and r2 > 55 \
            and last.close < p2.price - 0.5 * atr and last.close < last.open
        near = [z for z in zones if z["low"] - 0.3 * atr <= p2.price <= z["high"] + 0.3 * atr]
    if not (ok and near):
        return None
    z = max(near, key=lambda z: z["strength"])
    return dict(direction=side, setup="divergence", anchor=float(last.close), structure=float(p2.price),
                level_desc=f"{'le support' if side == 1 else 'la résistance'} {z['low']:.5g}–{z['high']:.5g}",
                level_strength=min(6, 2 * z["touches"]), rsi_points=(float(r1), float(r2)))


def detect_setups(d: pd.DataFrame, zones: list[dict], wt: dict, atr: float) -> list[dict]:
    out = []
    for side in (1, -1):
        for fn in (lambda: _pullback(d, zones, wt, atr, side),
                   lambda: _breakout_retest(d, zones, atr, side),
                   lambda: _divergence(d, zones, atr, side)):
            c = fn()
            if c:
                out.append(c)
    return out


def detect_watch(d: pd.DataFrame, zones: list[dict], wt: dict, atr: float) -> list[dict]:
    """Setups « en approche » : pas encore de signal, mais un niveau clé est proche.

    C'est la liste qu'un trader prépare le soir : où placer une alerte pour ne pas rater le setup.
    """
    last = d.iloc[-1]
    c, out = float(last.close), []
    if pd.isna(last.sma200) or not atr:
        return out
    for side in (1, -1):
        trend_ok = wt["direction"] * side > 0 and (c - last.sma200) * side > 0
        if not trend_ok:
            continue
        word = "Zone d'achat" if side == 1 else "Zone de vente"
        # 1) Repli en cours vers un support / la MM50 (rebond vers une résistance pour la vente)
        levels = [("de la MM50", float(last.sma50))] + [
            (f"{'du support' if side == 1 else 'de la résistance'} {z['low']:.5g}–{z['high']:.5g}",
             z["high"] if side == 1 else z["low"])
            for z in zones if z["kind"] == ("support" if side == 1 else "resistance") and z["touches"] >= 2]
        near = [(n, lv, (c - lv) * side / atr) for n, lv in levels if 0.5 < (c - lv) * side / atr <= 2.0]
        if near:
            n, lv, dist = min(near, key=lambda t: t[2])
            out.append(dict(direction="long" if side == 1 else "short", level=lv, kind="pullback",
                            message=f"Tendance {('haussière' if side == 1 else 'baissière')} : le prix est à "
                                    f"{dist:.1f} ATR {n} ({lv:.5g}). {word} potentielle : "
                                    f"place une alerte et attends une réaction du prix."))
        # 2) Teste une résistance (un support) solide : une cassure créerait un setup cassure + retest
        tests = [z for z in zones if z["touches"] >= 2 and
                 (0 <= (z["low"] - c) / atr <= 0.6 if side == 1 else 0 <= (c - z["high"]) / atr <= 0.6)]
        if tests:
            z = max(tests, key=lambda z: z["strength"])
            lv = z["high"] if side == 1 else z["low"]
            out.append(dict(direction="long" if side == 1 else "short", level=lv, kind="breakout",
                            message=f"Teste {'la résistance' if side == 1 else 'le support'} {z['low']:.5g}–"
                                    f"{z['high']:.5g} ({z['touches']} contacts) : une clôture "
                                    f"{'au-dessus' if side == 1 else 'en dessous'} ouvrirait un setup "
                                    "cassure + retest."))
        # 3) Excès dans le sens contraire de la tendance
        if (side == 1 and last.rsi14 < 35) or (side == -1 and last.rsi14 > 65):
            out.append(dict(direction="long" if side == 1 else "short", level=c, kind="oversold",
                            message=f"{'Survente' if side == 1 else 'Surachat'} (RSI {last.rsi14:.0f}) dans une "
                                    f"tendance {('haussière' if side == 1 else 'baissière')} : surveille une "
                                    "bougie de retournement."))
    return out


# ---------------------------------------------------------------- fiche de trade

def _targets(entry: float, risk: float, zones: list[dict], atr: float, side: int) -> list[float]:
    if side == 1:
        edges = sorted(z["low"] for z in zones if z["low"] > entry + 0.5 * atr)
    else:
        edges = sorted((z["high"] for z in zones if z["high"] < entry - 0.5 * atr), reverse=True)
    tp1 = edges[0] if edges else entry + side * 2 * risk
    nxt = [e for e in edges if (e - tp1) * side > 0.5 * atr]
    tp2 = nxt[0] if nxt else entry + side * max(abs(tp1 - entry) + risk, 3 * risk)
    nxt = [e for e in edges if (e - tp2) * side > 0.5 * atr]
    tp3 = nxt[0] if nxt else tp2 + side * 1.5 * risk
    return [tp1, tp2, tp3]


def build_card(*, asset_class: str, symbol: str, name: str, d: pd.DataFrame, h4: pd.DataFrame | None,
               cand: dict, zones: list[dict], atr: float, wt: dict, macro_bias: float,
               macro_why: list[str], events: list[tuple[date, str]] | None = None,
               today: date | None = None) -> tuple[dict | None, str | None]:
    """Renvoie (fiche, None) ou (None, raison du rejet)."""
    side = cand["direction"]
    dir_word = "achat" if side == 1 else "vente"
    last, prev = d.iloc[-1], d.iloc[-2]
    c = float(last.close)
    half = ENTRY_ZONE_HALF_WIDTH_ATR * atr
    anchor = cand["anchor"]
    e_low, e_high = anchor - half, anchor + half

    # Entrée et type d'ordre
    if e_low <= c <= e_high:
        entry, order = c, "Au marché ou ordre limite dans la zone"
    elif (c > e_high) == (side == 1):
        entry, order = anchor, "Ordre limite dans la zone (attendre le repli)" if side == 1 else \
            "Ordre limite dans la zone (attendre le rebond)"
    else:
        entry = e_low if side == 1 else e_high
        order = "Ordre stop : n'entrer que si le prix revient dans la zone"

    # Stop : derrière la structure + marge, et au moins à STOP_MIN_DISTANCE_ATR de l'entrée
    struct_stop = cand["structure"] - side * STOP_STRUCTURE_BUFFER_ATR * atr
    min_stop = entry - side * STOP_MIN_DISTANCE_ATR * atr
    stop = min(struct_stop, min_stop) if side == 1 else max(struct_stop, min_stop)
    risk = abs(entry - stop)
    if risk > STOP_MAX_DISTANCE_ATR * atr:
        return None, (f"{SETUP_LABELS[cand['setup']]} ({dir_word}) rejeté : structure trop loin, "
                      f"stop à {risk / atr:.1f} ATR (max {STOP_MAX_DISTANCE_ATR}).")

    tp1, tp2, tp3 = _targets(entry, risk, zones, atr, side)
    tp1_from_zone = abs(abs(tp1 - entry) - 2 * risk) > 1e-9
    rr1, rr2 = abs(tp1 - entry) / risk, abs(tp2 - entry) / risk
    if rr1 < MIN_RR:
        return None, (f"{SETUP_LABELS[cand['setup']]} ({dir_word}) rejeté : obstacle à {tp1:.5g} trop proche, "
                      f"R:R de {rr1:.1f} sous le minimum de {MIN_RR:g}.")

    # ---- Score de confluence
    aligned = wt["score"] * side
    s_trend = max(0, min(30, 12 + 6 * aligned))

    candle_ok = (c > last.open and (c - last.low) >= 0.5 * (last.high - last.low)) if side == 1 else \
                (c < last.open and (last.high - c) >= 0.5 * (last.high - last.low))
    h4_ok = False
    if h4 is not None and len(h4) >= 30:
        h4_ema = ema(h4["close"], 20)
        h4_ok = bool((h4["close"].iloc[-1] - h4_ema.iloc[-1]) * side > 0)
    base = {"pullback": 16, "breakout_retest": 18, "divergence": 14}[cand["setup"]]
    s_setup = min(30, base + cand["level_strength"] + (3 if candle_ok else 0) + (3 if h4_ok else 0))

    s_rr = int(round(min(15, 8 + (rr1 - 2) * 7)))
    s_macro = int(round(7.5 + 7.5 * macro_bias * side))

    s_mom = 0
    if not pd.isna(last.macd_hist) and not pd.isna(prev.macd_hist):
        s_mom += 4 if (last.macd_hist - prev.macd_hist) * side > 0 else 0
        s_mom += 2 if (last.macd - last.macd_signal) * side > 0 else 0
    rsi_v = float(last.rsi14)
    s_mom += 2 if (40 <= rsi_v <= 65 if side == 1 else 35 <= rsi_v <= 60) else 0
    if not pd.isna(last.adx) and last.adx >= 20 and (last.plus_di - last.minus_di) * side > 0:
        s_mom += 2

    breakdown = {"tendance": int(s_trend), "setup": int(s_setup), "rr": s_rr, "macro": s_macro, "momentum": s_mom}
    score = sum(breakdown.values())
    confidence = "Élevée" if score >= 75 else "Moyenne" if score >= 60 else "Faible"

    # ---- Horizon (estimation grossière : 0,3 à 0,5 ATR de progression nette par séance)
    dist_atr = abs(tp2 - entry) / atr
    lo, hi = max(1, math.ceil(dist_atr / 0.5)), max(2, math.ceil(dist_atr / 0.3))
    horizon = f"≈ {lo}–{hi} séances (~{max(1, round(lo / 5))}–{max(1, round(hi / 5))} semaines)"
    horizon_days = hi if asset_class == "crypto" else math.ceil(hi * 7 / 5)

    # ---- Alertes
    today = today or date.today()
    warnings = []
    for ev_date, title in events or []:
        if today <= ev_date <= today + timedelta(days=horizon_days):
            warnings.append(f"{title} le {ev_date.strftime('%d/%m/%Y')} pendant la durée prévue du trade : "
                            "risque de gap. Réduis la taille ou attends la publication.")
    if aligned < 0:
        warnings.append("Trade contre la tendance hebdomadaire : taille réduite conseillée.")
    if asset_class == "crypto":
        warnings.append("Marché ouvert 24 h/24 et 7 j/7 : le stop peut être touché le week-end.")
    if asset_class.startswith("stock") and side == -1:
        warnings.append("Vente à découvert sur action : via CFD ou SRD selon ton courtier.")
    bar_day = pd.Timestamp(d.index[-1]).date()
    if (today - bar_day).days > 4:
        warnings.append(f"Dernière bougie du {bar_day.strftime('%d/%m/%Y')} : mets les données à jour.")

    dec = price_decimals(asset_class, symbol, c)
    r = lambda x: round(float(x), dec)  # noqa: E731

    # ---- Invalidation
    inval = [f"Clôture journalière {'sous' if side == 1 else 'au-dessus de'} {r(cand['structure'])} "
             f"({'dernier creux' if side == 1 else 'dernier sommet'}) : le scénario ne tient plus."]
    if cand["setup"] == "breakout_retest":
        inval.append(f"Retour durable {'sous' if side == 1 else 'au-dessus de'} {cand['level_desc']} : cassure ratée.")
    if wt.get("ma30"):
        inval.append(f"Clôture hebdomadaire {'sous' if side == 1 else 'au-dessus de'} la MM30 semaines "
                     f"({r(wt['ma30'])}) : la tendance de fond change.")

    # ---- Justification
    trend_word = "haussière" if side == 1 else "baissière"
    if cand["setup"] == "pullback":
        why = (f"Le prix revient tester {cand['level_desc']} ({r(anchor)}) dans une tendance {trend_word} et "
               f"commence à réagir (RSI {rsi_v:.0f}). On {'achète un repli' if side == 1 else 'vend un rebond'} "
               "plutôt que de courir après le prix.")
    elif cand["setup"] == "breakout_retest":
        why = (f"{cand['level_desc'].capitalize()} a été cassée puis retestée par "
               f"{'le dessus' if side == 1 else 'le dessous'} : "
               f"{'l’ancienne résistance sert de support' if side == 1 else 'l’ancien support sert de résistance'} "
               "(inversion de rôle). "
               "Entrer sur le retest donne un meilleur prix et un stop plus serré qu'en pleine cassure.")
    else:
        r1, r2 = cand.get("rsi_points", (0, 0))
        why = (f"Le prix marque un nouveau {'creux' if side == 1 else 'sommet'} sur {cand['level_desc']} mais le RSI "
               f"ne confirme pas ({r1:.0f} puis {r2:.0f}) : la pression {'vendeuse' if side == 1 else 'acheteuse'} "
               "s'essouffle. Setup de retournement : on attend la bougie de confirmation, ce qui est le cas ici.")
    rationale = (f"{name} : tendance hebdomadaire {wt['label']}. {why} "
                 f"Le stop ({(math.floor if side == 1 else math.ceil)(stop * 10 ** dec) / 10 ** dec}) est placé {'sous le creux' if side == 1 else 'au-dessus du sommet'} récent "
                 f"avec une marge, à {risk / atr:.1f} ATR de l'entrée, pour ne pas être sorti par le bruit normal. "
                 f"Premier objectif {r(tp1)} (R:R {rr1:.1f}), "
                 + ("juste avant le prochain obstacle. " if tp1_from_zone else
                    "fixé à 2 fois le risque car aucune zone majeure ne bloque le chemin. ")
                 + (" ".join(macro_why) + ". " if macro_why else "")
                 + "Plan : sécuriser 1/3 à TP1 et remonter le stop au point d'entrée, 1/3 à TP2, "
                 "laisser courir le dernier tiers avec un stop suiveur sur la MM20 journalière.")

    card = dict(
        direction="long" if side == 1 else "short", setup_type=cand["setup"], setup_label=SETUP_LABELS[cand["setup"]],
        entry_low=r(e_low), entry_high=r(e_high), entry_ref=r(entry), order_type=order,
        # stop arrondi vers l'extérieur : jamais plus près de l'entrée que prévu
        stop=(math.floor if side == 1 else math.ceil)(stop * 10 ** dec) / 10 ** dec,
        tp1=r(tp1), tp2=r(tp2), tp3=r(tp3), rr_tp1=round(rr1, 2), rr_tp2=round(rr2, 2),
        trailing="Après TP1 : stop au point d'entrée, puis stop suiveur sur la MM20 journalière",
        score=score, score_breakdown=breakdown, score_max=SCORE_MAX, confidence=confidence,
        horizon=horizon, horizon_days=horizon_days, h4_confirmation=h4_ok,
        invalidation=inval, warnings=warnings, rationale=rationale, bar_date=bar_day.isoformat(),
        last_close=r(c), atr=round(float(atr), dec),
    )
    return card, None
