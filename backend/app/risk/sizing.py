"""Calcul de la taille de position : combien acheter pour ne risquer que X % du capital."""
import math

from ..config import MAX_RISK_PCT

FOREX_STANDARD_LOT = 100_000


def _floor_step(x: float, step: float) -> float:
    n = math.floor(x / step + 1e-9)
    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return round(n * step, decimals)


def size_position(*, asset_class: str, unit_label: str, qty_step: float, contract_size: float | None,
                  micro_contract_size: float | None, entry: float, stop: float, capital: float,
                  risk_pct: float, account_currency: str, quote_currency: str,
                  quote_per_account: float, quote_factor: float = 1.0) -> dict:
    """quote_per_account : nombre d'unités de la devise de cotation pour 1 unité de la devise du compte.

    Logique : risque en euros = capital x % ; converti dans la devise de l'actif ; divisé par
    la perte par unité si le stop est touché (|entrée - stop|) ; arrondi vers le bas au pas autorisé.
    """
    if entry <= 0 or stop <= 0 or entry == stop:
        raise ValueError("Entrée et stop doivent être positifs et différents.")
    if capital <= 0:
        raise ValueError("Le capital doit être positif.")
    warnings: list[str] = []
    if risk_pct > MAX_RISK_PCT:
        warnings.append(f"Risque ramené à {MAX_RISK_PCT} % (plafond de sécurité).")
        risk_pct = MAX_RISK_PCT

    risk_account = capital * risk_pct / 100
    per_unit = abs(entry - stop) * quote_factor  # perte par unité, en devise de cotation
    raw_units = risk_account * quote_per_account / per_unit
    units = _floor_step(raw_units, qty_step)
    real_risk = units * per_unit / quote_per_account
    value = units * entry * quote_factor / quote_per_account
    leverage = value / capital

    out = dict(direction="long" if entry > stop else "short", units=units, unit_label=unit_label,
               risk_target=round(risk_account, 2), risk_real=round(real_risk, 2), risk_pct=risk_pct,
               position_value=round(value, 2), leverage=round(leverage, 2),
               account_currency=account_currency, quote_currency=quote_currency,
               stop_distance=abs(entry - stop), stop_distance_pct=round(abs(entry - stop) / entry * 100, 2))

    if asset_class == "forex":
        lots = units / FOREX_STANDARD_LOT
        out["lots"] = round(lots, 2)
        out["detail"] = f"{lots:.2f} lot standard, soit {units / 1_000:.0f} micro-lots"
    elif asset_class == "commodity" and contract_size:
        std = math.floor(units / contract_size + 1e-9)
        micro = math.floor(units / micro_contract_size + 1e-9) if micro_contract_size else 0
        out.update(contracts=std, micro_contracts=micro)
        out["detail"] = (f"{units:g} {unit_label} = {std} contrat(s) standard ({contract_size:g}) "
                         f"ou {micro} micro-contrat(s) ({micro_contract_size:g})")
        if micro == 0:
            warnings.append("Position trop petite pour un micro-contrat future : passe par un CFD ou un ETF.")
    elif asset_class.startswith("stock") and out["direction"] == "short":
        warnings.append("Vente à découvert sur action : possible via CFD ou SRD selon ton courtier.")

    if units == 0:
        warnings.append("Capital trop faible pour ce stop : impossible de respecter ton risque. Passe ton tour.")
    if leverage > 1:
        warnings.append(f"La position vaut {leverage:.1f}x ton capital : effet de levier nécessaire (CFD, marge). "
                        "Le stop limite la perte prévue, mais un gap d'ouverture peut la dépasser.")
    if leverage > 5:
        warnings.append("Levier supérieur à 5 : très risqué. Élargis moins ton stop ou réduis le risque.")
    out["warnings"] = warnings
    return out
