"""Réglages globaux de l'application."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_URL = f"sqlite:///{DATA_DIR / 'trading.db'}"

# Paramètres de compte par défaut (modifiables dans l'écran Réglages)
DEFAULT_SETTINGS = {
    "capital": 10_000.0,
    "account_currency": "EUR",
    "risk_pct": 1.0,          # risque par trade, en % du capital
    "max_open_risk_pct": 6.0,  # risque total ouvert maximum
}
MAX_RISK_PCT = 2.0            # plafond dur du risque par trade
SUPPORTED_ACCOUNT_CCY = ("EUR", "USD")

# Historique téléchargé
DAILY_PERIOD = os.environ.get("DAILY_PERIOD", "10y")  # 3y suffit pour le rapport du soir (plus rapide)
HOURLY_PERIOD = "730d"        # limite Yahoo pour l'horaire, regroupé ensuite en H4

# Moteur de signaux (logique de trader swing)
ATR_PERIOD = 14
MIN_RR = 2.0                       # TP1 doit rapporter au moins 2x le risque
STOP_STRUCTURE_BUFFER_ATR = 0.5    # marge derrière le creux / sommet
STOP_MIN_DISTANCE_ATR = 1.5        # le stop est au moins à 1,5 ATR de l'entrée
STOP_MAX_DISTANCE_ATR = 4.0        # au-delà, la structure est trop loin : setup rejeté
ENTRY_ZONE_HALF_WIDTH_ATR = 0.25   # zone d'entrée = niveau +/- 0,25 ATR

# Scan automatique quotidien (heure de Paris)
SCAN_HOUR = 23
SCAN_MINUTE = 0
