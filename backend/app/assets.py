"""Catalogue des produits suivis et données initiales."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import DEFAULT_SETTINGS
from .models import Asset, Setting, Watchlist, WatchlistItem


def _stock(symbol, provider, name, cls, ccy, category):
    return dict(symbol=symbol, provider_symbol=provider, name=name, asset_class=cls, currency=ccy,
                unit_label="actions", qty_step=1.0, category=category)


def _fx(pair, category="Forex majeures"):
    quote = pair[3:]
    return dict(symbol=pair, provider_symbol=f"{pair}=X", name=f"{pair[:3]}/{quote}", asset_class="forex",
                currency=quote, unit_label="unités de devise de base", contract_size=100_000,
                micro_contract_size=1_000, qty_step=1_000, pip_size=0.01 if quote == "JPY" else 0.0001,
                category=category)


def _cmd(symbol, provider, name, unit, size, micro, step, category, factor=1.0):
    return dict(symbol=symbol, provider_symbol=provider, name=name, asset_class="commodity", currency="USD",
                unit_label=unit, contract_size=size, micro_contract_size=micro, qty_step=step,
                category=category, quote_factor=factor)


def _crypto(sym, name, step):
    return dict(symbol=sym, provider_symbol=f"{sym}-USD", name=name, asset_class="crypto", currency="USD",
                unit_label=sym, qty_step=step, category="Crypto")


# Actifs suivis en détail par défaut (favoris : données H4 téléchargées à chaque mise à jour)
DEFAULT_FAVORITES = ["AAPL", "MSFT", "NVDA", "MC", "ASML", "SAP", "EURUSD", "GBPUSD", "USDJPY",
                     "XAUUSD", "WTI", "BTC", "ETH"]

_US = [("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "Nvidia"), ("AMZN", "Amazon"), ("GOOGL", "Alphabet"),
       ("META", "Meta"), ("TSLA", "Tesla"), ("AVGO", "Broadcom"), ("JPM", "JPMorgan"), ("V", "Visa"),
       ("MA", "Mastercard"), ("UNH", "UnitedHealth"), ("LLY", "Eli Lilly"), ("XOM", "ExxonMobil"),
       ("JNJ", "Johnson & Johnson"), ("PG", "Procter & Gamble"), ("HD", "Home Depot"), ("COST", "Costco"),
       ("NFLX", "Netflix"), ("AMD", "AMD"), ("CRM", "Salesforce"), ("ORCL", "Oracle"), ("KO", "Coca-Cola"),
       ("PEP", "PepsiCo"), ("WMT", "Walmart"), ("BAC", "Bank of America"), ("DIS", "Disney"),
       ("ADBE", "Adobe"), ("QCOM", "Qualcomm"), ("CAT", "Caterpillar"), ("BA", "Boeing"),
       ("GS", "Goldman Sachs")]

_CAC = [("AI", "Air Liquide"), ("AIR", "Airbus"), ("BNP", "BNP Paribas"), ("CS", "AXA"), ("SAN", "Sanofi"),
        ("OR", "L'Oréal"), ("RMS", "Hermès"), ("KER", "Kering"), ("TTE", "TotalEnergies"),
        ("SU", "Schneider Electric"), ("SAF", "Safran"), ("DG", "Vinci"), ("EL", "EssilorLuxottica"),
        ("BN", "Danone"), ("ACA", "Crédit Agricole"), ("GLE", "Société Générale"), ("ENGI", "Engie"),
        ("CAP", "Capgemini"), ("RI", "Pernod Ricard"), ("ORA", "Orange"), ("STMPA", "STMicroelectronics"),
        ("DSY", "Dassault Systèmes"), ("HO", "Thales"), ("LR", "Legrand"), ("SGO", "Saint-Gobain"),
        ("ML", "Michelin"), ("VIE", "Veolia"), ("CA", "Carrefour"), ("RNO", "Renault"), ("PUB", "Publicis"),
        ("ERF", "Eurofins"), ("EN", "Bouygues")]

_EU = [("SIE", "SIE.DE", "Siemens"), ("ALV", "ALV.DE", "Allianz"), ("DTE", "DTE.DE", "Deutsche Telekom"),
       ("BAS", "BAS.DE", "BASF"), ("IFX", "IFX.DE", "Infineon"), ("ADS", "ADS.DE", "Adidas"),
       ("MBG", "MBG.DE", "Mercedes-Benz"), ("ITX", "ITX.MC", "Inditex"), ("SANES", "SAN.MC", "Banco Santander"),
       ("ENEL", "ENEL.MI", "Enel"), ("ISP", "ISP.MI", "Intesa Sanpaolo"), ("RACE", "RACE.MI", "Ferrari")]

_ETF = [("SPY", "SPY", "ETF S&P 500", "USD"), ("QQQ", "QQQ", "ETF Nasdaq 100", "USD"),
        ("IWM", "IWM", "ETF Russell 2000 (petites capi US)", "USD"), ("DIA", "DIA", "ETF Dow Jones", "USD"),
        ("XLE", "XLE", "ETF secteur Énergie US", "USD"), ("XLF", "XLF", "ETF secteur Finance US", "USD"),
        ("XLK", "XLK", "ETF secteur Technologie US", "USD"), ("EEM", "EEM", "ETF Marchés émergents", "USD"),
        ("CW8", "CW8.PA", "Amundi MSCI World (éligible PEA)", "EUR"),
        ("ESE", "ESE.PA", "BNP S&P 500 EUR (éligible PEA)", "EUR")]

CATALOG = (
    [_stock(s, s, n, "stock_us", "USD", "Actions US") for s, n in _US]
    + [_stock("MC", "MC.PA", "LVMH", "stock_eu", "EUR", "CAC 40")]
    + [_stock(s, f"{s}.PA", n, "stock_eu", "EUR", "CAC 40") for s, n in _CAC]
    + [_stock("ASML", "ASML.AS", "ASML", "stock_eu", "EUR", "Actions Europe"),
       _stock("SAP", "SAP.DE", "SAP", "stock_eu", "EUR", "Actions Europe")]
    + [_stock(s, p, n, "stock_eu", "EUR", "Actions Europe") for s, p, n in _EU]
    + [_stock(s, p, n, "stock_us" if c == "USD" else "stock_eu", c, "ETF") for s, p, n, c in _ETF]
    + [_fx(p) for p in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF")]
    + [_fx(p, "Forex croisées") for p in ("EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF")]
    + [
        _cmd("XAUUSD", "GC=F", "Or (future COMEX)", "onces", 100, 10, 0.01, "Métaux"),
        _cmd("XAGUSD", "SI=F", "Argent (future COMEX)", "onces", 5_000, 1_000, 0.1, "Métaux"),
        _cmd("PLAT", "PL=F", "Platine (future NYMEX)", "onces", 50, 10, 0.01, "Métaux"),
        _cmd("COPPER", "HG=F", "Cuivre (future COMEX)", "livres", 25_000, 2_500, 1, "Métaux"),
        _cmd("WTI", "CL=F", "Pétrole WTI (future NYMEX)", "barils", 1_000, 100, 0.1, "Énergie"),
        _cmd("BRENT", "BZ=F", "Pétrole Brent (future ICE)", "barils", 1_000, 100, 0.1, "Énergie"),
        _cmd("NATGAS", "NG=F", "Gaz naturel (future NYMEX)", "MMBtu", 10_000, 1_000, 1, "Énergie"),
        # Céréales : Yahoo cote en cents par boisseau -> facteur 0,01
        _cmd("WHEAT", "ZW=F", "Blé (future CBOT, cents/boisseau)", "boisseaux", 5_000, 1_000, 1, "Agricoles", 0.01),
        _cmd("CORN", "ZC=F", "Maïs (future CBOT, cents/boisseau)", "boisseaux", 5_000, 1_000, 1, "Agricoles", 0.01),
        _cmd("SOY", "ZS=F", "Soja (future CBOT, cents/boisseau)", "boisseaux", 5_000, 1_000, 1, "Agricoles", 0.01),
    ]
    + [_crypto("BTC", "Bitcoin", 0.0001), _crypto("ETH", "Ethereum", 0.001), _crypto("SOL", "Solana", 0.01),
       _crypto("XRP", "XRP", 1), _crypto("BNB", "BNB", 0.001), _crypto("ADA", "Cardano", 1),
       _crypto("DOGE", "Dogecoin", 1)]
)

# Séries macro : (identifiant interne, source, code chez la source)
MACRO_SERIES = [
    ("VIX", "yahoo", "^VIX"),
    ("DXY", "yahoo", "DX-Y.NYB"),
    ("US10Y", "fred", "DGS10"),
    ("US2Y", "fred", "DGS2"),
    ("FED", "fred", "DFF"),
    ("ECB", "fred", "ECBDFR"),
]


def seed_assets(s: Session) -> None:
    existing = {a.symbol: a for a in s.scalars(select(Asset))}
    for spec in CATALOG:
        a = existing.get(spec["symbol"])
        if a is None:
            s.add(Asset(**spec))
        elif a.origin == "catalogue":
            for k, v in spec.items():
                setattr(a, k, v)
    s.flush()
    if s.get(Watchlist, 1) is None:
        s.add(Watchlist(id=1, name="Favoris"))
        s.flush()
        for a in s.scalars(select(Asset).where(Asset.symbol.in_(DEFAULT_FAVORITES))):
            s.add(WatchlistItem(watchlist_id=1, asset_id=a.id))


def seed_settings(s: Session) -> None:
    if s.get(Setting, 1) is None:
        s.add(Setting(id=1, **DEFAULT_SETTINGS))


def favorite_ids(s: Session) -> set[int]:
    return set(s.scalars(select(WatchlistItem.asset_id).where(WatchlistItem.watchlist_id == 1)))
