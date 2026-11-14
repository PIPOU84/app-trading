"""Détection des points pivots et des zones de support / résistance."""
import numpy as np
import pandas as pd


def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> pd.DataFrame:
    """Sommets et creux confirmés : plus haut (ou plus bas) que `left` bougies avant et `right` après."""
    w = left + right + 1
    n = len(df)
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    hi_max = df["high"].rolling(w).max().shift(-right).to_numpy()
    lo_min = df["low"].rolling(w).min().shift(-right).to_numpy()
    valid = np.zeros(n, dtype=bool)
    valid[left:max(left, n - right)] = True
    parts = []
    for mask, prices, kind in ((valid & (highs == hi_max), highs, "high"), (valid & (lows == lo_min), lows, "low")):
        pos = np.flatnonzero(mask)
        parts.append(pd.DataFrame({"ts": df.index[pos], "pos": pos, "price": prices[pos].astype(float), "kind": kind}))
    return pd.concat(parts, ignore_index=True).sort_values(["pos", "kind"], ascending=[True, True]).reset_index(drop=True)


def find_zones(df: pd.DataFrame, atr_value: float, lookback: int = 250, left: int = 3, right: int = 3,
               merge_atr: float = 0.6, max_zones: int = 12) -> list[dict]:
    """Regroupe les pivots proches (moins de `merge_atr` ATR d'écart) en zones.

    Une zone touchée plusieurs fois, récemment, et ayant servi à la fois de support et
    de résistance (inversion de rôle) est plus forte.
    """
    d = df.tail(lookback)
    if len(d) < left + right + 5 or not atr_value or atr_value <= 0:
        return []
    pts = swing_points(d, left, right).sort_values("price")
    last_close = float(d["close"].iloc[-1])
    n = len(d)

    clusters: list[list] = []
    for p in pts.itertuples():
        if clusters and p.price - clusters[-1][0].price <= merge_atr * atr_value:
            clusters[-1].append(p)
        else:
            clusters.append([p])

    zones = []
    for cl in clusters:
        prices = [p.price for p in cl]
        kinds = {p.kind for p in cl}
        last_pos = max(p.pos for p in cl)
        touches = len(cl)
        if touches < 2:
            continue
        low, high = min(prices), max(prices)
        if high - low < 0.2 * atr_value:  # zone trop fine : on lui donne un peu d'épaisseur
            mid = (low + high) / 2
            low, high = mid - 0.1 * atr_value, mid + 0.1 * atr_value
        strength = touches + (1.0 if n - last_pos <= 60 else 0.0) + (1.0 if len(kinds) == 2 else 0.0)
        zones.append(dict(low=low, high=high, mid=(low + high) / 2, touches=touches, strength=strength,
                          last_touch=str(cl[-1].ts)[:10], role_reversal=len(kinds) == 2))

    # Plus haut et plus bas de la période : toujours des niveaux majeurs
    for price, ts, label in ((float(d["high"].max()), d["high"].idxmax(), "plus haut"),
                             (float(d["low"].min()), d["low"].idxmin(), "plus bas")):
        if not any(z["low"] - 0.1 * atr_value <= price <= z["high"] + 0.1 * atr_value for z in zones):
            zones.append(dict(low=price - 0.1 * atr_value, high=price + 0.1 * atr_value, mid=price,
                              touches=1, strength=2.0, last_touch=str(ts)[:10], role_reversal=False,
                              note=f"{label} sur {lookback} séances"))

    zones = sorted(zones, key=lambda z: z["strength"], reverse=True)[:max_zones]
    for z in zones:
        z["kind"] = "support" if z["high"] < last_close else "resistance" if z["low"] > last_close else "pivot"
    return sorted(zones, key=lambda z: z["mid"])
