"""
src/utils/radar.py
Signaux « radar » ajoutés au tableau de Screening.

Ce module ne télécharge rien lui-même : il reçoit
    - le tableau du screening (prix Yahoo, bêta, amplitude, compression...)
    - la photo Hyperliquid instantanée   (hl_snapshots.fetch_hl_live)
    - l'historique des photos            (hl_snapshots.load_history)
et calcule les variations d'OI, leur z-score, le volume HL relatif, puis
classe chaque actif dans un ÉTAT lisible.

Pas de score pondéré : les poids seraient inventés. Les indicateurs n'ont pas
le même rôle (déclencheur / qualité / frein), on les combine en règles
explicites que l'on pourra backtester une fois l'historique constitué.
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Réglages — tous les seuils sont ici, et nulle part ailleurs
# ---------------------------------------------------------------------------
HORIZONS_H = (4, 24)             # variations d'OI calculées (1 h retiré : bruit pour un bot journalier)

Z_FENETRE_JOURS = 14             # distribution de référence du z-score
Z_MIN_POINTS    = 5 * 24         # ≈ 5 jours de photos horaires avant d'afficher un z-score
Z_SEUIL         = 2.0            # |z| ≥ 2 → mouvement inhabituel POUR CET ACTIF

OI_SEUIL_PROVISOIRE = 10.0       # % sur 24 h, utilisé tant que le z-score n'existe pas

VOL_HL_MIN_JOURS = 3             # historique minimum pour le volume HL relatif

# Prix : comparé à l'amplitude quotidienne médiane de l'actif (colonne Amplit. j.)
# Un actif qui fait 8 % par jour d'ordinaire n'est pas « en hausse » à +3 %.
PRIX_FORT   = 0.5                # |Δ prix 24 h| ≥ 0,5 × amplitude → mouvement net
PRIX_STABLE = 0.25               # |Δ prix 24 h| ≤ 0,25 × amplitude → prix stable
AMPLITUDE_DEFAUT = 4.0           # % si l'amplitude est inconnue

COMPRESSION_SEUIL = 0.8          # amplitude 5 j / amplitude 30 j ≤ 0,8 → range qui se resserre
VOL_REL_DEMARRAGE = 1.5          # volume ≥ 1,5 × la normale pour valider un démarrage
FUNDING_SURCHAUFFE = 50.0        # %/an : au-delà, la foule est massivement longue

# Ordre = priorité d'affichage ET de classement (un seul état par actif)
ETATS = {
    "surchauffe":   "🔴 Surchauffe",
    "squeeze":      "🟠 Squeeze",
    "demarrage":    "🔵 Démarrage",
    "accumulation": "🟢 Accumulation",
    "shorts":       "🟣 Shorts en force",
    "purge":        "⚫ Purge",
    "attente":      "⏳ Historique",
    "calme":        "· Calme",
}
ORDRE_ETATS = {libelle: i for i, libelle in enumerate(ETATS.values())}


# ---------------------------------------------------------------------------
# Variations d'OI
# ---------------------------------------------------------------------------

def _valeur_il_y_a(history: pd.DataFrame, coins, maintenant: pd.Timestamp,
                   heures: float, colonne: str = "oi") -> pd.Series:
    """Valeur de `colonne` sur la photo la plus proche de (maintenant − heures).

    Tolérance : 40 % de l'horizon, et au moins 35 min pour qu'un horizon court trouve
    toujours une photo malgré une cadence horaire (9 h 36 pour 24 h). Au-delà,
    il n'y a pas de photo assez proche → None plutôt qu'un chiffre faux.
    """
    if history.empty:
        return pd.Series(np.nan, index=coins)
    cible = pd.DataFrame({"coin": list(coins),
                          "ts": maintenant - pd.Timedelta(hours=heures)}).sort_values("ts")
    hist = history[["ts", "coin", colonne]].dropna().sort_values("ts")
    fusion = pd.merge_asof(
        cible, hist, on="ts", by="coin", direction="nearest",
        tolerance=pd.Timedelta(minutes=max(35, heures * 60 * 0.4)),
    )
    return fusion.set_index("coin")[colonne].reindex(coins)


def _zscore_oi(history: pd.DataFrame, coins, oi_chg: pd.Series,
               maintenant: pd.Timestamp, heures: int = 24) -> pd.Series:
    """Où se situe la variation d'OI actuelle sur `heures` dans la distribution
    habituelle des variations sur la même durée de CET actif, sur les
    Z_FENETRE_JOURS derniers jours.

    z = (variation actuelle − variation moyenne) / écart-type
    En clair : combien de fois plus que d'habitude.
    z = +2 : une hausse d'OI qu'on ne voit qu'environ 1 fois sur 40 sur cet actif.
    """
    z = pd.Series(np.nan, index=coins)
    if history.empty:
        return z
    hist = history[["ts", "coin", "oi"]].dropna()
    hist = hist[hist["ts"] >= maintenant - pd.Timedelta(days=Z_FENETRE_JOURS + 1)]
    hist = hist.sort_values("ts")
    if hist.empty:
        return z

    # Pour chaque photo, la photo ~`heures` plus tôt
    avant = hist.rename(columns={"oi": "oi_avant"}).copy()
    avant["ts"] = avant["ts"] + pd.Timedelta(hours=heures)
    paires = pd.merge_asof(hist, avant.sort_values("ts"), on="ts", by="coin",
                           direction="nearest",
                           tolerance=pd.Timedelta(minutes=min(45, max(20, heures * 60 * 0.4))))
    paires = paires.dropna(subset=["oi_avant"])
    paires = paires[paires["oi_avant"] > 0]
    paires["chg"] = (paires["oi"] / paires["oi_avant"] - 1) * 100

    stats = paires.groupby("coin")["chg"].agg(["mean", "std", "count"])
    stats = stats[(stats["count"] >= Z_MIN_POINTS) & (stats["std"] > 0)]
    stats = stats.reindex(coins)
    return ((oi_chg - stats["mean"]) / stats["std"]).round(2)


def historique_disponible(history: pd.DataFrame) -> dict:
    """Résumé de l'historique pour l'afficher sur la page."""
    if history is None or history.empty:
        return {"photos": 0, "jours": 0.0, "debut": None}
    ts = history["ts"].drop_duplicates()
    return {
        "photos": int(len(ts)),
        "jours":  round((ts.max() - ts.min()).total_seconds() / 86400, 1),
        "debut":  ts.min(),
    }


# ---------------------------------------------------------------------------
# Calcul principal
# ---------------------------------------------------------------------------

def compute_radar(df: pd.DataFrame, live: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes radar au tableau du screening et renvoie une copie.

    Met aussi à jour funding / OI / volume HL avec les valeurs instantanées,
    plus fraîches que celles du chargement Yahoo (qui peut dater d'une heure).
    """
    df = df.copy()
    coins = df["hl_name"].tolist()

    colonnes_radar = ["px_chg_24h", "oi_chg_4h", "oi_z_4h",
                      "oi_chg_24h", "oi_z",
                      "vol_hl_rel", "au_plafond", "etat"]
    if live is None or live.empty:
        for c in colonnes_radar:
            df[c] = None
        df["etat"] = ETATS["attente"]
        df.attrs["radar_ok"] = False
        return df

    maintenant = pd.Timestamp(live.attrs.get("ts") or pd.Timestamp.utcnow().tz_localize(None))
    l = live.reindex(coins)

    # Valeurs fraîches
    df["funding_annuel"] = (l["funding"] * 24 * 365 * 100).round(1).values
    df["open_interest"]  = (l["oi"] * l["mark_px"]).round().values
    df["volume_hl_24h"]  = l["day_ntl_vlm"].values
    df["au_plafond"]     = l["au_plafond"].values
    df["px_chg_24h"]     = ((l["mark_px"] / l["prev_day_px"] - 1) * 100).round(2).values

    # Variations d'OI en unités de l'actif
    oi_now = l["oi"]
    for h in HORIZONS_H:
        avant = _valeur_il_y_a(history, coins, maintenant, h, "oi")
        chg = ((oi_now / avant.replace(0, np.nan)) - 1) * 100
        df[f"oi_chg_{h}h"] = chg.round(2).values

    # z sur chaque horizon ; celui de 24 h (« oi_z ») est celui des états
    par_coin = df.set_index("hl_name")
    for h in HORIZONS_H:
        cle = "oi_z" if h == 24 else f"oi_z_{h}h"
        df[cle] = _zscore_oi(history, coins, par_coin[f"oi_chg_{h}h"], maintenant, h).values

    # Volume HL relatif : volume glissant 24 h actuel / sa moyenne sur 14 jours.
    # Glissant = sans le biais de la bougie Yahoo du jour, encore incomplète.
    infos = historique_disponible(history)
    if infos["jours"] >= VOL_HL_MIN_JOURS:
        recent = history[history["ts"] >= maintenant - pd.Timedelta(days=14)]
        moy = recent.groupby("coin")["day_ntl_vlm"].mean().reindex(coins)
        df["vol_hl_rel"] = (l["day_ntl_vlm"] / moy.replace(0, np.nan)).round(2).values
    else:
        df["vol_hl_rel"] = None

    df["etat"] = df.apply(_classer, axis=1)
    df.attrs["radar_ok"]    = True
    df.attrs["radar_ts"]    = maintenant
    df.attrs["historique"]  = infos
    df.attrs["z_actif"]     = bool(df["oi_z"].notna().any())
    df.attrs["plafond_ok"]  = bool(l["au_plafond"].notna().any())
    return df


# ---------------------------------------------------------------------------
# Classement en états
# ---------------------------------------------------------------------------

def _nombre(v):
    try:
        v = float(v)
        return None if np.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _classer(r) -> str:
    funding = _nombre(r.get("funding_annuel"))
    if r.get("au_plafond") is True or (funding is not None and funding >= FUNDING_SURCHAUFFE):
        return ETATS["surchauffe"]

    p   = _nombre(r.get("px_chg_24h"))
    oi  = _nombre(r.get("oi_chg_24h"))
    z   = _nombre(r.get("oi_z"))
    amp = _nombre(r.get("amplitude_med")) or AMPLITUDE_DEFAUT

    if p is None or oi is None:
        return ETATS["attente"]

    # OI qui bouge « vraiment » : relatif à l'actif dès que le z-score existe
    if z is not None:
        oi_hausse, oi_baisse = z >= Z_SEUIL, z <= -Z_SEUIL
    else:
        oi_hausse, oi_baisse = oi >= OI_SEUIL_PROVISOIRE, oi <= -OI_SEUIL_PROVISOIRE

    prix_hausse = p >= PRIX_FORT * amp
    prix_baisse = p <= -PRIX_FORT * amp
    prix_stable = abs(p) <= PRIX_STABLE * amp

    if prix_hausse and oi_baisse:
        return ETATS["squeeze"]

    if prix_hausse and oi_hausse:
        vol   = _nombre(r.get("vol_hl_rel"))
        if vol is None:
            vol = _nombre(r.get("volume_rel"))
        alpha = _nombre(r.get("alpha_7d"))
        if (vol is None or vol >= VOL_REL_DEMARRAGE) and (alpha is None or alpha > 0):
            return ETATS["demarrage"]

    if prix_stable and oi_hausse:
        comp = _nombre(r.get("compression"))
        if comp is None or comp <= COMPRESSION_SEUIL:
            return ETATS["accumulation"]

    if prix_baisse and oi_hausse:
        return ETATS["shorts"]
    if prix_baisse and oi_baisse:
        return ETATS["purge"]
    return ETATS["calme"]


# ---------------------------------------------------------------------------
# Score de momentum ajusté à la volatilité
# ---------------------------------------------------------------------------

def ajouter_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Score N j = perf N j ÷ mouvement normal sur N jours.

    Mouvement normal sur N jours ≈ ATR × √N, et non ATR × N : les jours de
    hausse et de baisse se compensent en partie, la volatilité s'additionne
    comme une marche au hasard.

    Lecture : +1 = l'actif a fait un mouvement « normal » pour lui sur la
    période ; +2 = deux fois plus ; 0,5 = la moitié. Rend comparables un
    +8 % sur BTC et un +20 % sur un petit perp très volatil.
    """
    df = df.copy()

    def _col(nom):          # colonne absente (tableau chargé avant une mise à jour) → vide
        return pd.to_numeric(df[nom], errors="coerce") if nom in df else pd.Series(np.nan, index=df.index)

    atr = _col("atr_pct").replace(0, np.nan)
    for n in (7, 30):
        perf = _col(f"perf_{n}d")
        df[f"score_{n}d"] = (perf / (atr * np.sqrt(n))).round(2)
    return df


# ---------------------------------------------------------------------------
# Météo du marché
# ---------------------------------------------------------------------------
METEO_PORTEUR   = "☀️ Vent porteur"
METEO_NEUTRE    = "⛅ Neutre"
METEO_CONTRAIRE = "🌧 Vent contraire"
LARGEUR_HAUTE, LARGEUR_BASSE = 60.0, 40.0     # % d'actifs au-dessus de leur moyenne 30 j


def _au_dessus_moyenne_30j(closes) -> bool | None:
    try:
        serie = pd.Series(closes, dtype=float).dropna()
    except Exception:
        return None
    if len(serie) < 30:
        return None
    return bool(serie.iloc[-1] > serie.tail(30).mean())


def meteo_marche(df: pd.DataFrame) -> dict:
    """Résumé de l'état du marché entier, à lire AVANT les signaux individuels.

    - BTC au-dessus ou en dessous de sa moyenne 30 j : la marée de fond.
    - Largeur : % d'actifs au-dessus de leur propre moyenne 30 j. Un marché
      où 70 % des actifs montent porte les signaux haussiers ; à 25 %, un
      🔵 isolé nage à contre-courant.
    - Décompte des états haussiers (🔵 🟢) et baissiers (🟣 ⚫).
    """
    m = {"btc_dessus": None, "btc_perf_7d": None, "largeur": None,
         "haussiers": 0, "baissiers": 0, "verdict": METEO_NEUTRE}
    if df is None or df.empty or "closes" not in df:
        return m

    btc = df[df["symbol"] == "BTC"]
    if not btc.empty:
        m["btc_dessus"]  = _au_dessus_moyenne_30j(btc.iloc[0]["closes"])
        m["btc_perf_7d"] = btc.iloc[0].get("perf_7d")

    dessus = df["closes"].apply(_au_dessus_moyenne_30j).dropna()
    if len(dessus):
        m["largeur"] = round(float(dessus.mean()) * 100, 1)

    if "etat" in df:
        m["haussiers"] = int(df["etat"].isin([ETATS["demarrage"], ETATS["accumulation"]]).sum())
        m["baissiers"] = int(df["etat"].isin([ETATS["shorts"], ETATS["purge"]]).sum())

    if m["btc_dessus"] is True and (m["largeur"] or 0) >= LARGEUR_HAUTE:
        m["verdict"] = METEO_PORTEUR
    elif m["btc_dessus"] is False and m["largeur"] is not None and m["largeur"] <= LARGEUR_BASSE:
        m["verdict"] = METEO_CONTRAIRE
    return m
