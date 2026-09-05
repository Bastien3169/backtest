"""
market_data.py
Données de marché pour le tableau de screening.

Deux sources, deux rôles :
    yfinance     → l'historique des prix (mêmes bougies que le backtest, donc
                   un actif affiché ici est un actif backtestable)
    Hyperliquid  → les métadonnées de tradabilité (funding, open interest,
                   levier max, volume du marché où les ordres partent vraiment)

Hyperliquid ne sert PAS de source de prix ici : la cohérence
screening ≡ backtest ≡ optimisation passe par yfinance.
"""

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import importlib.util
import os

_COINS_PATH = os.path.join(os.path.dirname(__file__), "coins.py")

# Profondeur téléchargée. 90 jours couvrent la perf 30 j, la position dans le
# range et laissent de la marge pour une perf sur N jours calculée à la volée
# côté page, sans relancer le chargement.
JOURS_HISTORIQUE = 90

# Fenêtre des métriques de risque. Fixée à 30 jours : allonger l'historique ne
# doit PAS changer en douce le sens de la corrélation, du bêta et de
# l'amplitude, qui ont toujours été calculés sur un mois.
FENETRE_RISQUE = 30

HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def _load_coins_fresh() -> list[dict]:
    spec   = importlib.util.spec_from_file_location("coins_fresh", _COINS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.COINS


def get_screening_coins() -> list[dict]:
    return [
        {
            "ticker":  c["ticker"],
            "symbol":  c["symbol"],
            "name":    c["name"],
            "hl_name": c.get("hl_name") or c["symbol"],
        }
        for c in _load_coins_fresh()
    ]


# ---------------------------------------------------------------------------
# Chargement des bougies
# ---------------------------------------------------------------------------

def _fetch_ohlcv(ticker: str, days: int = JOURS_HISTORIQUE) -> pd.DataFrame | None:
    """Bougies journalières : OHLC ET volumes, en une seule requête.

    Le volume vient d'ici et plus de fast_info : c'est un vrai volume échangé,
    et ça supprime un appel réseau par actif.
    """
    try:
        df = yf.Ticker(ticker).history(period=f"{days}d", interval="1d")
        if df.empty:
            return None
        df.index = df.index.tz_localize(None) if df.index.tzinfo is None else df.index.tz_convert(None)
        return df
    except Exception:
        return None


def _fetch_closes(ticker: str, days: int = JOURS_HISTORIQUE) -> pd.Series | None:
    """Clôtures seules — pour la série de référence BTC."""
    df = _fetch_ohlcv(ticker, days)
    return None if df is None else df["Close"]


def _serie_morte(closes: pd.Series, volumes: pd.Series | None) -> bool:
    """Une série figée ou sans volume n'est pas une donnée, c'est un artefact.

    Cas typique : un ticker Yahoo délisté ou remplacé continue de renvoyer une
    valeur, toujours la même. Le tableau affichait alors 0,00 % de perf et un
    volume à zéro comme s'il s'agissait d'un vrai calme plat.
    """
    derniers = closes.tail(7).dropna()
    if len(derniers) < 2:
        return True
    if float(derniers.max()) == float(derniers.min()):
        return True
    if volumes is not None:
        vol = volumes.tail(7).dropna()
        if len(vol) and float(vol.sum()) <= 0:
            return True
    return False


# ---------------------------------------------------------------------------
# Métriques de tendance
# ---------------------------------------------------------------------------

def perf_sur(closes: pd.Series, jours: int) -> float | None:
    """Variation en % sur N jours de bougies. None si l'historique manque.

    Exposée pour que la page puisse recalculer une perf sur N jours au choix
    sans relancer tout le chargement.
    """
    serie = closes.dropna()
    if len(serie) < jours + 1:
        return None
    return round((serie.iloc[-1] - serie.iloc[-(jours + 1)]) / serie.iloc[-(jours + 1)] * 100, 2)


def _position_range(closes: pd.Series, jours: int = FENETRE_RISQUE) -> float | None:
    """Où se situe le prix entre le plus bas et le plus haut de la fenêtre.

    0 = sur le plus bas de la période, 100 = sur le plus haut.
    Une perf 7 j excellente avec une position à 40 signale un mouvement qui a
    déjà rendu la moitié du terrain : c'est ce que la perf seule ne dit pas.
    """
    serie = closes.tail(jours).dropna()
    if len(serie) < 5:
        return None
    bas, haut = float(serie.min()), float(serie.max())
    if haut == bas:
        return None
    return round((float(serie.iloc[-1]) - bas) / (haut - bas) * 100, 1)


def _amplitude_mediane(df: pd.DataFrame, jours: int = FENETRE_RISQUE) -> float | None:
    """Amplitude quotidienne médiane en % : (haut − bas) / clôture.

    C'est le plancher de stop loss exploitable sur cet actif. Un SL plus serré
    que cette valeur se fait toucher par le bruit ordinaire de la journée, sans
    que la thèse de trade soit invalidée.
    """
    recent = df.tail(jours)
    if len(recent) < 5 or not {"High", "Low", "Close"} <= set(recent.columns):
        return None
    amplitude = (recent["High"] - recent["Low"]) / recent["Close"] * 100
    amplitude = amplitude.replace([np.inf, -np.inf], np.nan).dropna()
    if amplitude.empty:
        return None
    return round(float(amplitude.median()), 2)


def _rendements(serie: pd.Series, jours: int = FENETRE_RISQUE) -> pd.Series:
    return serie.tail(jours + 1).pct_change().dropna()


def _correlation_btc(closes: pd.Series, btc_closes: pd.Series) -> float | None:
    """Corrélation des rendements journaliers avec BTC, ramenée sur [0, 100]."""
    try:
        aligned = pd.concat([_rendements(closes), _rendements(btc_closes)], axis=1).dropna()
        if len(aligned) < 5:
            return None
        corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
        if pd.isna(corr):
            return None
        return round((corr + 1) / 2 * 100, 1)
    except Exception:
        return None


def _beta_vs_btc(closes: pd.Series, btc_closes: pd.Series) -> float | None:
    """Bêta réel : cov(alt, btc) / var(btc). BTC +1 % → alt +bêta %.

    Renvoyé tel quel, plus converti en score sur 5 : « 1,84 » est directement
    exploitable pour dimensionner une position, « 3 étoiles » ne l'est pas.
    """
    try:
        aligned = pd.concat([_rendements(closes), _rendements(btc_closes)], axis=1).dropna()
        aligned.columns = ["alt", "btc"]
        if len(aligned) < 5:
            return None
        var_btc = aligned["btc"].var()
        if not var_btc:
            return None
        return round(float(aligned["alt"].cov(aligned["btc"]) / var_btc), 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Contexte Hyperliquid — tradabilité réelle
# ---------------------------------------------------------------------------

def fetch_hl_context() -> dict:
    """Funding, open interest, levier max et volume 24 h pour TOUT l'univers HL.

    Un seul appel `metaAndAssetCtxs` : la réponse est [meta, [contextes]], les
    deux listes étant dans le même ordre que l'univers.

    Un échec n'est jamais bloquant — les colonnes HL disparaissent, le reste du
    tableau fonctionne.
    """
    try:
        resp = requests.post(
            HL_INFO_URL,
            headers={"Content-Type": "application/json"},
            json={"type": "metaAndAssetCtxs"},
            timeout=15,
        )
        resp.raise_for_status()
        donnees = resp.json()
    except Exception as e:
        print(f"Contexte Hyperliquid indisponible : {e}")
        return {}

    try:
        univers   = donnees[0].get("universe", [])
        contextes = donnees[1]
    except (IndexError, KeyError, TypeError, AttributeError) as e:
        print(f"Réponse metaAndAssetCtxs inattendue : {e}")
        return {}

    def _f(source, cle):
        try:
            return float(source.get(cle))
        except (TypeError, ValueError, AttributeError):
            return None

    sortie = {}
    for actif, ctx in zip(univers, contextes):
        nom = actif.get("name")
        if not nom or not isinstance(ctx, dict):
            continue

        prix    = _f(ctx, "markPx") or _f(ctx, "oraclePx")
        oi_base = _f(ctx, "openInterest")
        funding = _f(ctx, "funding")          # taux HORAIRE

        sortie[nom] = {
            # Le funding est prélevé toutes les heures. Annualisé, il devient
            # comparable au gain visé : 0,01 %/h = 87,6 %/an, ce qui dévore un
            # long bien avant que la thèse ait le temps de se réaliser.
            "funding_annuel": round(funding * 24 * 365 * 100, 1) if funding is not None else None,
            "open_interest":  round(oi_base * prix) if (oi_base is not None and prix) else None,
            "volume_hl_24h":  _f(ctx, "dayNtlVlm"),
            "levier_max":     actif.get("maxLeverage"),
        }
    return sortie


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

def load_screening_data(progress_cb=None) -> pd.DataFrame:
    """Charge tout et retourne un DataFrame prêt à afficher.

    Relit coins.py à chaque appel pour refléter les mises à jour de la liste.
    """
    # BTC-USD et non BTC-EUR : tous les alts sont cotés en -USD. Comparer des
    # rendements en dollars à des rendements en euros injectait le mouvement
    # EUR/USD dans la corrélation ET dans le bêta.
    btc_closes = _fetch_closes("BTC-USD")
    if btc_closes is None:
        return pd.DataFrame()

    if progress_cb:
        progress_cb(0.02, "Lecture du contexte Hyperliquid...")
    contexte_hl = fetch_hl_context()

    rows    = []
    ecartes = []
    coins   = get_screening_coins()
    total   = len(coins)

    for idx, coin in enumerate(coins):
        if progress_cb:
            progress_cb((idx + 1) / total, f"Chargement {coin['symbol']}...")

        ohlcv = _fetch_ohlcv(coin["ticker"])
        if ohlcv is None:
            ecartes.append(coin["symbol"] + " (aucune donnée)")
            continue

        closes  = ohlcv["Close"]
        volumes = ohlcv["Volume"] if "Volume" in ohlcv.columns else None

        if _serie_morte(closes, volumes):
            ecartes.append(coin["symbol"] + " (série figée)")
            continue

        vol_24h = float(volumes.iloc[-1]) if volumes is not None and len(volumes) else None
        vol_moy = float(volumes.tail(FENETRE_RISQUE).mean()) if volumes is not None else None
        vol_rel = round(vol_24h / vol_moy, 2) if (vol_24h and vol_moy) else None

        hl = contexte_hl.get(coin["hl_name"], {})

        rows.append({
            "symbol":         coin["symbol"],
            "name":           coin["name"],
            "ticker":         coin["ticker"],
            "hl_name":        coin["hl_name"],
            "perf_24h":       perf_sur(closes, 1),
            "perf_7d":        perf_sur(closes, 7),
            "perf_30d":       perf_sur(closes, 30),
            "position_range": _position_range(closes),
            "amplitude_med":  _amplitude_mediane(ohlcv),
            "corr_btc":       _correlation_btc(closes, btc_closes),
            "beta":           _beta_vs_btc(closes, btc_closes),
            "volume_24h":     vol_24h,
            "volume_rel":     vol_rel,
            "funding_annuel": hl.get("funding_annuel"),
            "open_interest":  hl.get("open_interest"),
            "volume_hl_24h":  hl.get("volume_hl_24h"),
            "levier_max":     hl.get("levier_max"),
            # Série complète : permet à la page de tracer la sparkline et de
            # recalculer une perf sur N jours sans relancer le chargement.
            "closes":         [float(v) for v in closes.dropna().tolist()],
        })

    df = pd.DataFrame(rows)
    # Transportés avec le tableau pour que la page puisse dire ce qu'elle a
    # écarté, sans changer la signature de la fonction.
    df.attrs["ecartes"]  = ecartes
    df.attrs["hl_ok"]    = bool(contexte_hl)
    df.attrs["fenetre"]  = FENETRE_RISQUE
    return df
