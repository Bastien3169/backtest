"""
src/utils/flux_binance.py
Qui est pressé : acheteurs ou vendeurs au prix du marché ? (données Binance)

Ce que ça mesure
----------------
Chaque transaction a un acheteur ET un vendeur : compter « les acheteurs
contre les vendeurs » donne toujours 50/50. Ce qui se mesure, c'est qui a
TRAVERSÉ le carnet d'ordres en acceptant le prix du marché (l'agresseur) :
    achat agressif = volume des achats au marché / volume total × 100
50 % = équilibre ; 60 % = les acheteurs sont nettement plus pressés.

Trois mesures sur 24 h glissantes :
    achat_spot_24h  spot Binance     — argent réel, sans levier (colonne affichée)
    achat_perp_24h  futures Binance  — plus bruité (levier, liquidations)
    ls_comptes      % de COMPTES nets longs sur les futures Binance (pas des
                    volumes : 1 000 petits longs pèsent plus qu'une baleine
                    short). Humeur du public, souvent lue à l'envers.
Les deux dernières sont surtout enregistrées dans le journal pour vérifier
plus tard si elles prédisent quelque chose (Binance ne garde que 30 jours
d'historique du ratio long/short : impossible de le reconstruire après coup).

Source : API publique Binance, sans clé. Les bougies (/klines) contiennent
déjà le volume acheté au marché (champ « taker buy quote asset volume »).
Un actif absent de Binance donne une case vide, jamais une erreur.
"""

from concurrent.futures import ThreadPoolExecutor

import requests

SPOT_URL = "https://api.binance.com"
PERP_URL = "https://fapi.binance.com"
TIMEOUT  = 10
WORKERS  = 8        # requêtes en parallèle : ~200 actifs × 3 appels en ~15-30 s

# Index des champs d'une bougie Binance (identiques en spot et en futures)
_K_VOL_QUOTE   = 7     # volume total en USDT
_K_TAKER_QUOTE = 10    # dont achats au marché, en USDT


def _symboles(base_url: str, chemin: str) -> set[str]:
    """Liste des paires cotées (appel léger : un prix par paire)."""
    try:
        r = requests.get(base_url + chemin, timeout=TIMEOUT)
        r.raise_for_status()
        return {x["symbol"] for x in r.json()}
    except Exception as e:
        print(f"[flux] liste des paires Binance indisponible ({base_url}) : {e}")
        return set()


def _bases(symbol: str, hl_name: str) -> list[str]:
    """Noms possibles de l'actif chez Binance. Hyperliquid préfixe d'un « k » les
    actifs cotés par 1 000 (kPEPE = 1 000 PEPE)."""
    bases = [symbol.upper()]
    if hl_name and hl_name.startswith("k") and hl_name[1:].isupper():
        bases.append(hl_name[1:])
    if hl_name:
        bases.append(hl_name.upper())
    return list(dict.fromkeys(bases))


def _resoudre(bases: list[str], cotees: set[str], prefixes: tuple[str, ...]) -> str | None:
    for b in bases:
        for p in prefixes:
            if f"{p}{b}USDT" in cotees:
                return f"{p}{b}USDT"
    return None


def _achat_agressif(base_url: str, chemin: str, paire: str) -> float | None:
    """% du volume 24 h fait par des achats au marché (24 bougies d'1 h)."""
    try:
        r = requests.get(base_url + chemin,
                         params={"symbol": paire, "interval": "1h", "limit": 24},
                         timeout=TIMEOUT)
        r.raise_for_status()
        bougies = r.json()
        total = sum(float(b[_K_VOL_QUOTE]) for b in bougies)
        achats = sum(float(b[_K_TAKER_QUOTE]) for b in bougies)
        return round(achats / total * 100, 1) if total > 0 else None
    except Exception:
        return None


def _comptes_longs(paire: str) -> float | None:
    """% des comptes Binance futures nets longs sur cette paire (dernier jour)."""
    try:
        r = requests.get(PERP_URL + "/futures/data/globalLongShortAccountRatio",
                         params={"symbol": paire, "period": "1d", "limit": 1},
                         timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
        return round(float(d[-1]["longAccount"]) * 100, 1) if d else None
    except Exception:
        return None


def flux(coins: list[dict]) -> dict[str, dict]:
    """{hl_name: {achat_spot_24h, achat_perp_24h, ls_comptes}} pour chaque actif.

    `coins` : liste de dicts avec au moins « symbol » et « hl_name ».
    Ne lève jamais d'exception : en cas de panne Binance, tout est vide.
    """
    spot_cotees = _symboles(SPOT_URL, "/api/v3/ticker/price")
    perp_cotees = _symboles(PERP_URL, "/fapi/v1/ticker/price")
    if not spot_cotees and not perp_cotees:
        return {}

    def _un(coin):
        bases = _bases(coin["symbol"], coin.get("hl_name") or "")
        spot = _resoudre(bases, spot_cotees, ("",))
        # Futures : les petits prix sont cotés par 1 000 ou 1 000 000 (1000PEPEUSDT)
        perp = _resoudre(bases, perp_cotees, ("", "1000", "1000000"))
        return coin.get("hl_name") or coin["symbol"], {
            "achat_spot_24h": _achat_agressif(SPOT_URL, "/api/v3/klines", spot) if spot else None,
            "achat_perp_24h": _achat_agressif(PERP_URL, "/fapi/v1/klines", perp) if perp else None,
            "ls_comptes":     _comptes_longs(perp) if perp else None,
        }

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        resultats = dict(pool.map(_un, coins))
    n = sum(1 for v in resultats.values() if v["achat_spot_24h"] is not None)
    print(f"[flux] Binance : achat agressif spot pour {n}/{len(coins)} actifs")
    return resultats
