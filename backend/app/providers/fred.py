"""Séries macro de la Réserve fédérale de St. Louis (FRED), sans clé d'API."""
import io
from datetime import date, timedelta

import pandas as pd
import requests

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fetch_series(series_id: str, years: int = 5) -> pd.Series:
    start = (date.today() - timedelta(days=365 * years)).isoformat()
    r = requests.get(FRED_CSV, params={"id": series_id, "cosd": start}, timeout=30,
                     headers={"User-Agent": "app-trading/0.1"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    date_col, value_col = df.columns[0], df.columns[-1]
    s = pd.Series(pd.to_numeric(df[value_col], errors="coerce").values,
                  index=pd.to_datetime(df[date_col]), name=series_id)
    return s.dropna()
