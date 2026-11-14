import numpy as np
import pandas as pd
import pytest

from app.analysis.indicators import add_all, atr, rsi, sma
from app.analysis.levels import find_zones
from app.risk.sizing import size_position
from app.signals.engine import build_card


def ohlc(closes, spread=1.0):
    c = pd.Series(closes, dtype=float, index=pd.date_range("2020-01-01", periods=len(closes), freq="B"))
    return pd.DataFrame({"open": c.shift().fillna(c.iloc[0]), "high": c + spread, "low": c - spread,
                         "close": c, "volume": 1000.0})


# ---------------------------------------------------------------- indicateurs

def test_sma():
    assert sma(pd.Series([1, 2, 3, 4.0]), 2).tolist()[1:] == [1.5, 2.5, 3.5]


def test_rsi_extremes():
    assert rsi(pd.Series(np.arange(1, 60, dtype=float))).iloc[-1] == 100
    assert rsi(pd.Series(np.arange(60, 1, -1, dtype=float))).iloc[-1] == pytest.approx(0)
    assert rsi(pd.Series([5.0] * 40)).iloc[-1] == 50


def test_atr_constant_range():
    df = ohlc([100.0] * 50, spread=2.0)  # range haut-bas = 4
    assert atr(df).iloc[-1] == pytest.approx(4.0)


# ---------------------------------------------------------------- niveaux

def test_zones_in_range_market():
    # marché en range entre ~100 et ~110 : on doit trouver une zone en bas et une en haut
    wave = 105 + 5 * np.sin(np.linspace(0, 12 * np.pi, 240))
    df = ohlc(wave, spread=0.3)
    zones = find_zones(df, atr_value=1.0)
    mids = [z["mid"] for z in zones]
    assert any(abs(m - 100) < 1 for m in mids)
    assert any(abs(m - 110) < 1 for m in mids)


# ---------------------------------------------------------------- taille de position

def test_size_stock_eur_account_usd_quote():
    r = size_position(asset_class="stock_us", unit_label="actions", qty_step=1, contract_size=None,
                      micro_contract_size=None, entry=100, stop=95, capital=10_000, risk_pct=1,
                      account_currency="EUR", quote_currency="USD", quote_per_account=1.1)
    assert r["units"] == 22                   # 100 € = 110 $ / 5 $ = 22 actions
    assert r["risk_real"] <= r["risk_target"]


def test_size_forex_lots():
    r = size_position(asset_class="forex", unit_label="u", qty_step=1000, contract_size=100_000,
                      micro_contract_size=1000, entry=1.10, stop=1.09, capital=10_000, risk_pct=1,
                      account_currency="EUR", quote_currency="USD", quote_per_account=1.1)
    assert r["units"] == 11_000 and r["lots"] == 0.11


def test_size_usdjpy_conversion():
    r = size_position(asset_class="forex", unit_label="u", qty_step=1000, contract_size=100_000,
                      micro_contract_size=1000, entry=150, stop=149, capital=10_000, risk_pct=1,
                      account_currency="EUR", quote_currency="JPY", quote_per_account=165)
    assert r["units"] == 16_000               # 16 500 ¥ de risque / 1 ¥ par unité, arrondi au micro-lot


def test_size_crypto_fraction_and_cap():
    r = size_position(asset_class="crypto", unit_label="BTC", qty_step=0.0001, contract_size=None,
                      micro_contract_size=None, entry=60_000, stop=57_000, capital=10_000, risk_pct=5,
                      account_currency="USD", quote_currency="USD", quote_per_account=1)
    assert r["risk_pct"] == 2                 # plafonné
    assert r["units"] == pytest.approx(0.0666)
    assert any("plafond" in w for w in r["warnings"])


def test_size_commodity_too_small_for_micro():
    r = size_position(asset_class="commodity", unit_label="onces", qty_step=0.01, contract_size=100,
                      micro_contract_size=10, entry=2000, stop=1950, capital=5_000, risk_pct=1,
                      account_currency="USD", quote_currency="USD", quote_per_account=1)
    assert r["units"] == 1.0 and r["micro_contracts"] == 0
    assert any("CFD" in w for w in r["warnings"])


def test_size_grains_quoted_in_cents():
    # blé à 550 cents, stop à 520 cents : perte 0,30 $ par boisseau -> 100 $ / 0,30 = 333 boisseaux
    r = size_position(asset_class="commodity", unit_label="boisseaux", qty_step=1, contract_size=5000,
                      micro_contract_size=1000, entry=550, stop=520, capital=10_000, risk_pct=1,
                      account_currency="USD", quote_currency="USD", quote_per_account=1, quote_factor=0.01)
    assert r["units"] == 333
    assert r["position_value"] == pytest.approx(333 * 5.5)


def test_macro_bias_forex_variants():
    from app.analysis.macro import asset_macro_bias
    strong_dollar_risk_on = dict(risk=1.0, dollar=1.0, yields=0.0, label="risk-on")
    assert asset_macro_bias("forex", "EURUSD", strong_dollar_risk_on)[0] < 0
    assert asset_macro_bias("forex", "USDCHF", strong_dollar_risk_on)[0] > 0
    assert asset_macro_bias("forex", "AUDJPY", strong_dollar_risk_on)[0] > 0   # carry trade
    assert asset_macro_bias("commodity", "XAGUSD", strong_dollar_risk_on)[0] < 0


def test_watch_detects_pullback_approach():
    from app.signals.engine import detect_watch
    d = _uptrend()
    a = float(d["atr14"].iloc[-1])
    c = float(d["close"].iloc[-1])
    zone = dict(low=c - 1.6 * a, high=c - 1.2 * a, mid=c - 1.4 * a, touches=3, strength=4, kind="support")
    items = detect_watch(d, [zone], WT_UP, a)
    assert any(w["kind"] == "pullback" and w["direction"] == "long" for w in items)


# ---------------------------------------------------------------- fiche de trade

def _uptrend():
    rng = np.random.default_rng(1)
    closes = 100 + np.cumsum(0.3 + rng.normal(0, 1, 300))
    return add_all(ohlc(closes))


WT_UP = dict(direction=1, score=3, label="haussière", ma30=None)


def test_card_long_structure():
    d = _uptrend()
    a = float(d["atr14"].iloc[-1])
    c = float(d["close"].iloc[-1])
    cand = dict(direction=1, setup="pullback", anchor=c, structure=c - 2 * a, level_desc="la MM20", level_strength=2)
    card, why = build_card(asset_class="stock_us", symbol="TEST", name="Test", d=d, h4=None, cand=cand,
                           zones=[], atr=a, wt=WT_UP, macro_bias=0.5, macro_why=[])
    assert why is None
    assert card["stop"] < card["entry_ref"] < card["tp1"] < card["tp2"] < card["tp3"]
    assert card["rr_tp1"] >= 2
    assert card["entry_ref"] - card["stop"] >= 1.5 * a - 1e-6        # distance minimale
    assert card["stop"] <= cand["structure"] - 0.5 * a + 1e-6         # derrière la structure
    assert 0 <= card["score"] <= 100


def test_card_rejected_when_resistance_too_close():
    d = _uptrend()
    a = float(d["atr14"].iloc[-1])
    c = float(d["close"].iloc[-1])
    zone = dict(low=c + a, high=c + 1.3 * a, mid=c + 1.15 * a, touches=3, strength=4, kind="resistance")
    cand = dict(direction=1, setup="pullback", anchor=c, structure=c - a, level_desc="la MM20", level_strength=2)
    card, why = build_card(asset_class="stock_us", symbol="TEST", name="Test", d=d, h4=None, cand=cand,
                           zones=[zone], atr=a, wt=WT_UP, macro_bias=0, macro_why=[])
    assert card is None and "R:R" in why


def test_card_short_mirror():
    d = _uptrend()
    a = float(d["atr14"].iloc[-1])
    c = float(d["close"].iloc[-1])
    cand = dict(direction=-1, setup="pullback", anchor=c, structure=c + a, level_desc="la MM20", level_strength=2)
    card, _ = build_card(asset_class="stock_us", symbol="TEST", name="Test", d=d, h4=None, cand=cand,
                         zones=[], atr=a, wt=WT_UP, macro_bias=0.5, macro_why=[])
    assert card["tp3"] < card["tp2"] < card["tp1"] < card["entry_ref"] < card["stop"]
    assert any("contre la tendance" in w for w in card["warnings"])
