"""
coins_updater.py
Construit la liste des cryptos supportées.

Source de vérité : l'univers Hyperliquid (`POST /info {"type":"meta"}`).
Un actif n'est retenu que s'il est À LA FOIS tradable sur HL et historisé sur
Yahoo Finance — c'est exactement l'intersection dont l'app a besoin :
    - HL     → passer les ordres          (champ "hl_name")
    - yfinance → backtester et screener   (champ "ticker")

Pourquoi pas le top 100 CoinGecko : cet univers ne correspond ni à ce qui est
tradable, ni à ce qui est backtestable. Il proposait des coins absents de HL et
cachait des coins listés sur HL. CoinGecko ne sert plus qu'à récupérer les noms
lisibles ("Hyperliquid" plutôt que "HYPE"), et son échec n'est pas bloquant.

Piège Yahoo : quand un symbole est déjà pris, Yahoo suffixe le ticker crypto
d'un identifiant numérique. Hyperliquid n'est pas "HYPE-USD" mais
"HYPE32196-USD". Construire le ticker en f"{symbol}-USD" fait donc disparaître
silencieusement tous les coins en collision. On résout désormais via l'endpoint
de recherche Yahoo quand la forme simple échoue.
"""

import os
import re
import requests
import yfinance as yf

COINS_FILE = os.path.join(os.path.dirname(__file__), "coins.py")

HL_INFO_URL = "https://api.hyperliquid.xyz/info"

COINGECKO_MARKETS_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=250&page=1&sparkline=false"
)

YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
# Yahoo renvoie 403 sans User-Agent navigateur.
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"}

# Indices boursiers — hors HL, conservés tels quels pour le backtest.
INDICES = [
    {"ticker": "^GSPC",     "symbol": "SP500",   "name": "S&P 500"},
    {"ticker": "^IXIC",     "symbol": "NASDAQ",  "name": "Nasdaq Composite"},
    {"ticker": "^STOXX50E", "symbol": "STOXX50", "name": "Euro Stoxx 50"},
    {"ticker": "^FCHI",     "symbol": "CAC40",   "name": "CAC 40"},
    {"ticker": "^GDAXI",    "symbol": "DAX",     "name": "DAX 40"},
    {"ticker": "^DJI",      "symbol": "DOW",     "name": "Dow Jones"},
    {"ticker": "^FTSE",     "symbol": "FTSE100", "name": "FTSE 100"},
    {"ticker": "^N225",     "symbol": "NIKKEI",  "name": "Nikkei 225"},
]


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def fetch_hl_universe() -> list[str]:
    """Noms des perps listés sur Hyperliquid, dans l'ordre de la meta."""
    resp = requests.post(
        HL_INFO_URL,
        headers={"Content-Type": "application/json"},
        json={"type": "meta"},
        timeout=15,
    )
    resp.raise_for_status()
    universe = resp.json().get("universe", [])
    noms = []
    for actif in universe:
        nom = actif.get("name")
        # isDelisted apparaît sur les marchés retirés — on les saute.
        if nom and not actif.get("isDelisted"):
            noms.append(nom)
    return noms


def fetch_coingecko_names() -> dict[str, str]:
    """{SYMBOLE: nom lisible} — best effort, un échec n'est pas bloquant."""
    try:
        resp = requests.get(COINGECKO_MARKETS_URL, timeout=15)
        resp.raise_for_status()
        return {c["symbol"].upper(): c["name"] for c in resp.json()}
    except Exception as e:
        print(f"CoinGecko indisponible ({e}) — noms lisibles ignorés.")
        return {}


# ---------------------------------------------------------------------------
# Résolution du ticker Yahoo
# ---------------------------------------------------------------------------

def _base_symbol(hl_name: str) -> str:
    """Ramène un nom HL au symbole du jeton sous-jacent.

    HL préfixe les jetons à très petit prix par un multiplicateur :
    "kPEPE" = 1 000 PEPE, "kBONK", "1000FLOKI"... Le sous-jacent Yahoo est PEPE.
    """
    nom = re.sub(r"^(k|1000+)", "", hl_name) if re.match(r"^(k|1000+)[A-Z]", hl_name) else hl_name
    return nom.upper()


def test_yfinance_ticker(ticker: str) -> bool:
    """True si yfinance renvoie au moins quelques bougies pour ce ticker."""
    try:
        df = yf.Ticker(ticker).history(period="1mo", interval="1d")
        return len(df) >= 7
    except Exception:
        return False


def _yahoo_search_crypto(symbole: str) -> str | None:
    """Cherche chez Yahoo le ticker crypto correspondant à un symbole.

    Attrape les tickers suffixés type "HYPE32196-USD" que la forme
    f"{symbole}-USD" ne peut pas deviner.
    """
    try:
        resp = requests.get(
            YAHOO_SEARCH_URL,
            params={"q": symbole, "quotesCount": 15, "newsCount": 0},
            headers=_UA,
            timeout=15,
        )
        resp.raise_for_status()
        quotes = resp.json().get("quotes", [])
    except Exception as e:
        print(f"Recherche Yahoo échouée pour {symbole} ({e})")
        return None

    for q in quotes:
        sym = (q.get("symbol") or "").upper()
        if q.get("quoteType") != "CRYPTOCURRENCY" or not sym.endswith("-USD"):
            continue
        base = sym[:-4]                       # "HYPE32196"
        # Le symbole cherché doit être le préfixe, le reste uniquement des
        # chiffres : HYPE32196 ✔ / HYPERION ✘
        if base == symbole or (base.startswith(symbole) and base[len(symbole):].isdigit()):
            return sym
    return None


def resolve_yahoo_ticker(hl_name: str) -> str | None:
    """Ticker Yahoo utilisable pour cet actif HL, ou None."""
    symbole = _base_symbol(hl_name)

    direct = f"{symbole}-USD"
    if test_yfinance_ticker(direct):
        return direct

    trouve = _yahoo_search_crypto(symbole)
    if trouve and test_yfinance_ticker(trouve):
        return trouve

    return None


# ---------------------------------------------------------------------------
# Mise à jour
# ---------------------------------------------------------------------------

def update_coins(progress_cb=None) -> tuple[list[dict], list[str]]:
    """Reconstruit coins.py à partir de l'univers Hyperliquid.

    Returns:
        (available, skipped) : actifs retenus, et noms HL sans historique Yahoo
    """
    univers = fetch_hl_universe()
    noms    = fetch_coingecko_names()
    total   = len(univers)

    available = []
    skipped   = []
    vus       = set()      # évite les doublons kPEPE / PEPE

    for idx, hl_name in enumerate(univers):
        if progress_cb:
            progress_cb((idx + 1) / total, f"Test {hl_name} ({idx+1}/{total})...")

        symbole = _base_symbol(hl_name)
        if symbole in vus:
            continue

        ticker = resolve_yahoo_ticker(hl_name)
        if not ticker:
            skipped.append(hl_name)
            continue

        vus.add(symbole)
        available.append({
            "ticker":  ticker,                       # yfinance : backtest / screening
            "symbol":  symbole,                      # affichage
            "hl_name": hl_name,                      # Hyperliquid : passage d'ordres
            "name":    noms.get(symbole, hl_name),
        })

    _write_coins_file(available)
    return available, skipped


def _echappe(txt: str) -> str:
    return str(txt).replace("\\", "\\\\").replace('"', '\\"')


def _write_coins_file(coins: list[dict]):
    """Réécrit coins.py — cryptos ET indices.

    L'ancienne version n'écrivait que COINS : chaque mise à jour effaçait
    INDICES et ALL_ASSETS du fichier, et les indices disparaissaient de l'app
    sans le moindre message d'erreur.
    """
    lignes = [
        '"""',
        'coins.py',
        'Source unique de vérité pour la liste des actifs supportés.',
        'Généré automatiquement par coins_updater.py — ne pas éditer à la main.',
        '',
        'Champs :',
        '    ticker  : format Yahoo Finance, pour l\'historique (backtest, screening)',
        '    symbol  : symbole affiché',
        '    hl_name : nom de l\'actif sur Hyperliquid, pour passer les ordres',
        '    name    : nom lisible',
        '',
        'ticker et hl_name diffèrent quand Yahoo suffixe un symbole en collision',
        '(Hyperliquid = "HYPE32196-USD" chez Yahoo, "HYPE" chez Hyperliquid).',
        '"""',
        '',
        'COINS = [',
    ]
    for c in coins:
        lignes.append(
            '    {{"ticker": "{t}", "symbol": "{s}", "hl_name": "{h}", "name": "{n}"}},'.format(
                t=_echappe(c["ticker"]),
                s=_echappe(c["symbol"]),
                h=_echappe(c["hl_name"]),
                n=_echappe(c["name"]),
            )
        )
    lignes += [
        ']',
        '',
        '# ---------------------------------------------------------------------------',
        '# Indices boursiers — tickers Yahoo Finance, non tradables sur Hyperliquid',
        '# ---------------------------------------------------------------------------',
        'INDICES = [',
    ]
    for i in INDICES:
        lignes.append(
            '    {{"ticker": "{t}", "symbol": "{s}", "hl_name": None, "name": "{n}"}},'.format(
                t=_echappe(i["ticker"]), s=_echappe(i["symbol"]), n=_echappe(i["name"]),
            )
        )
    lignes += [
        ']',
        '',
        '# Liste complète = cryptos + indices',
        'ALL_ASSETS = COINS + INDICES',
        '',
    ]

    with open(COINS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lignes))
