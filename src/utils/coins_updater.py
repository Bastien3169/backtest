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

Piège n° 2 (nov. 2026) : un ticker qui EXISTE n'est pas forcément le BON.
« ARB-USD », « JUP-USD », « UNI33433-USD » ont des bougies chez Yahoo… d'un
autre token (UNI à 0,00005 $ au lieu de 5 $). Chaque candidat est donc
comparé au prix Hyperliquid : seul celui qui cote à un facteur 2 près est
retenu (voir strategies.meme_actif).
"""

import os
import re
import requests
import yfinance as yf

from src.utils.strategies import meme_actif, prix_unitaire_hl

COINS_FILE = os.path.join(os.path.dirname(__file__), "coins.py")

HL_INFO_URL = "https://api.hyperliquid.xyz/info"

COINGECKO_MARKETS_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=250&page=1&sparkline=false"
)

# La résolution des tickers Yahoo passe par yfinance (yf.Lookup / yf.Search) :
# les endpoints de recherche de Yahoo exigent un cookie de session et un
# « crumb » que yfinance gère seul. Un appel HTTP direct se fait refuser.

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


def fetch_hl_prices() -> dict[str, float]:
    """{nom HL: prix mark} pour tout l'univers — sert à valider les tickers Yahoo.
    Dictionnaire vide si HL ne répond pas (la validation est alors sautée)."""
    try:
        resp = requests.post(HL_INFO_URL, headers={"Content-Type": "application/json"},
                             json={"type": "metaAndAssetCtxs"}, timeout=15)
        resp.raise_for_status()
        meta, ctxs = resp.json()[:2]
        prix = {}
        for actif, ctx in zip(meta.get("universe", []), ctxs):
            try:
                prix[actif["name"]] = float(ctx.get("markPx") or ctx.get("oraclePx"))
            except (TypeError, ValueError, KeyError):
                continue
        return prix
    except Exception as e:
        print(f"Prix Hyperliquid indisponibles ({e}) — tickers non vérifiés.")
        return {}


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


def dernier_prix_yahoo(ticker: str) -> float | None:
    """Dernière clôture si yfinance renvoie au moins 7 bougies sur un mois, sinon None."""
    try:
        df = yf.Ticker(ticker).history(period="1mo", interval="1d")
        return float(df["Close"].dropna().iloc[-1]) if len(df) >= 7 else None
    except Exception:
        return None


def test_yfinance_ticker(ticker: str) -> bool:
    """True si yfinance renvoie au moins quelques bougies pour ce ticker."""
    return dernier_prix_yahoo(ticker) is not None


def _candidat_valide(symbole: str, ticker: str) -> bool:
    """Le ticker Yahoo correspond-il bien à ce symbole ?

    Yahoo suffixe d'un identifiant numérique les symboles crypto en collision :
    SUI → SUI20947-USD, UNI → UNI7083-USD, APT → APT21794-USD. On accepte donc
    le symbole nu ou le symbole suivi de chiffres, et rien d'autre —
    « HYPERION-USD » ne doit pas passer pour « HYPE ».
    """
    ticker = (ticker or "").upper()
    if not ticker.endswith("-USD"):
        return False
    base = ticker[:-4]
    return base == symbole or (base.startswith(symbole) and base[len(symbole):].isdigit())


def _yahoo_lookup(symbole: str, requete: str) -> list[str]:
    """Résolution via l'API lookup de Yahoo, à travers yfinance.

    IMPORTANT : passer par yfinance et pas par un requests.get direct. Yahoo
    exige désormais un cookie de session et un « crumb » sur ses endpoints de
    recherche ; yfinance les gère, un appel HTTP nu se fait refuser en masse.
    C'est ce qui faisait échouer la résolution de SUI, APT, UNI, POL, TAO,
    IMX... — des actifs pourtant tous présents chez Yahoo.
    """
    try:
        df = yf.Lookup(requete).get_cryptocurrency(count=50)
    except Exception as e:
        print(f"Lookup Yahoo indisponible pour {symbole} ({e})")
        return []

    if df is None or len(df) == 0:
        return []
    # TOUS les candidats : le premier n'est pas forcément le bon token
    return [t.upper() for t in df.index.astype(str) if _candidat_valide(symbole, t)]


def _yahoo_search(symbole: str, requete: str) -> list[str]:
    """Repli : l'endpoint de recherche, toujours via la session yfinance."""
    try:
        quotes = yf.Search(requete, max_results=25, news_count=0).quotes
    except Exception as e:
        print(f"Search Yahoo indisponible pour {symbole} ({e})")
        return []

    return [q["symbol"].upper() for q in quotes or []
            if q.get("quoteType") == "CRYPTOCURRENCY" and _candidat_valide(symbole, q.get("symbol", ""))]


def resolve_yahoo_ticker(hl_name: str, nom_lisible: str = "",
                         prix_hl: float | None = None) -> tuple[str | None, str]:
    """Ticker Yahoo utilisable pour cet actif HL.

    On RASSEMBLE tous les candidats avant d'en tester un seul. Une première
    version s'arrêtait au premier ticker trouvé : GALA-USD existe chez Yahoo
    mais est mort, ce qui empêchait de découvrir GALA7080-USD, le vivant.

    On interroge aussi Yahoo avec le NOM du token, pas seulement son symbole :
    « POL » ou « S » ramènent des dizaines de résultats sans intérêt, alors que
    « Polygon Ecosystem Token » ou « Sonic » tombent juste. Le filtre
    `_candidat_valide` reste appliqué, donc chercher par nom ne peut pas faire
    entrer un ticker qui ne correspond pas au symbole.

    Avec `prix_hl`, un candidat n'est retenu que s'il cote le même actif
    qu'Hyperliquid (facteur 2 près) ; parmi plusieurs, le plus proche gagne.
    Le ticker direct n'est plus accepté d'office : « ARB-USD » existe, mais
    c'est un autre token.

    Returns:
        (ticker, motif) — ticker None si rien trouvé, motif expliquant pourquoi
        pour que la page de mise à jour affiche autre chose qu'une liste muette.
    """
    symbole = _base_symbol(hl_name)

    direct = f"{symbole}-USD"
    if prix_hl is None:
        # Sans prix HL, impossible de vérifier : ancien comportement
        if test_yfinance_ticker(direct):
            return direct, "direct (non vérifié)"
    else:
        px = dernier_prix_yahoo(direct)
        if px is not None and meme_actif(px, prix_hl, hl_name):
            return direct, "direct"

    requetes = [symbole]
    if nom_lisible and nom_lisible.upper() != symbole:
        requetes.append(nom_lisible)

    candidats = []
    for requete in requetes:
        for resolveur in (_yahoo_lookup, _yahoo_search):
            for trouve in resolveur(symbole, requete):
                if trouve not in candidats:
                    candidats.append(trouve)

    if prix_hl is None:
        for candidat in candidats:
            if candidat != direct and test_yfinance_ticker(candidat):
                return candidat, "résolu (non vérifié)"
    else:
        cotes = {}
        for candidat in dict.fromkeys(candidats + [direct]):
            px = dernier_prix_yahoo(candidat)
            if px is not None:
                cotes[candidat] = px
        bons = [t for t, px in cotes.items() if meme_actif(px, prix_hl, hl_name)]
        if bons:
            # Le plus proche du prix HL (en rapport, dans un sens comme dans l'autre)
            from math import log
            ref = prix_unitaire_hl(prix_hl, hl_name)
            meilleur = min(bons, key=lambda t: abs(log(cotes[t] / ref)) if ref else 0)
            return meilleur, ("direct" if meilleur == direct else "résolu, prix vérifié")
        if cotes:
            detail = ", ".join(f"{t} = {px:.6g} $" for t, px in cotes.items())
            return None, f"aucun ticker au prix Hyperliquid ({prix_hl:.6g} $) : {detail}"

    if candidats:
        # Coté chez Yahoo, mais sans historique exploitable : trop récent ou
        # trop peu suivi pour servir de base à un backtest.
        return None, "historique trop court (" + ", ".join(candidats) + ")"

    return None, "aucun ticker Yahoo"


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
    prix_hl = fetch_hl_prices()
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

        ticker, motif = resolve_yahoo_ticker(hl_name, noms.get(symbole, ""), prix_hl.get(hl_name))
        if not ticker:
            skipped.append(hl_name + " (" + motif + ")")
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
