# BacktestBot 📈

Application Streamlit de backtest de stratégies crypto.

## Structure

```
backtest_bot/
├── app.py                        # Point d'entrée Streamlit
├── requirements.txt
└── src/
    ├── controllers/
    │   ├── indicators.py         # RSI, MM, MACD, Bollinger
    │   ├── backtest.py           # Moteur de simulation
    │   ├── charts.py             # Graphiques Plotly
    │   └── results.py            # Construction des tableaux
    ├── utils/
    │   └── data_loader.py        # Données OHLCV via CoinGecko
    ├── assets/                   # Ressources statiques (logo, CSS…)
    └── views/                    # Réservé aux futures pages multi-page Streamlit
```

## Installation

```bash
pip install -r requirements.txt
```

## Lancement

```bash
streamlit run app.py
```

## Fonctionnalités

### Paramètres globaux
- Mode capital **partagé** ou **indépendant** par stratégie
- Frais de transaction (défaut 0,1%)
- Paire crypto (top 100 CoinGecko)
- Temporalité : heure / jour / semaine / mois
- Durées d'investissement configurables (ex : `7,30,90`)

### Stratégies (ajout dynamique)
- Nom personnalisé
- Allocation du capital (%)
- Indicateurs :
  - RSI (période + seuil d'achat)
  - Moyennes Mobiles : MM1, MM10, MM20, MM50, MM100, MM200
  - Condition MM : prix au-dessus / en dessous
  - Croisement MM A × MM B (Golden/Death Cross)
  - MACD (croisement ligne signal)
  - Bollinger (touche bande haute / basse)
- Gestion des positions : TP / SL ou mode Hold

### Résultats
- Tableau par stratégie : Plus-value (€), Rendement (%), Drawdown max (%)
- Tableau comparatif multi-stratégies
- Graphiques :
  - Prix + points d'achat/vente
  - Rendement comparatif (bar chart)
  - Equity curves (line chart)
  - Drawdown comparé
