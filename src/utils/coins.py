"""
coins.py
Source unique de vérité pour la liste des actifs supportés.
Généré automatiquement par coins_updater.py — ne pas éditer à la main.

Champs :
    ticker  : format Yahoo Finance, pour l'historique (backtest, screening)
    symbol  : symbole affiché
    hl_name : nom de l'actif sur Hyperliquid, pour passer les ordres
    name    : nom lisible

ticker et hl_name diffèrent quand Yahoo suffixe un symbole déjà pris
(Hyperliquid = "HYPE32196-USD" chez Yahoo, "HYPE" chez Hyperliquid).
"""

COINS = [
    {"ticker": "BTC-USD",       "symbol": "BTC", "hl_name": "BTC", "name": "Bitcoin"},
    {"ticker": "ETH-USD",       "symbol": "ETH", "hl_name": "ETH", "name": "Ethereum"},
    {"ticker": "BNB-USD",       "symbol": "BNB", "hl_name": "BNB", "name": "BNB"},
    {"ticker": "HYPE32196-USD", "symbol": "HYPE", "hl_name": "HYPE", "name": "Hyperliquid"},
    {"ticker": "SOL-USD",       "symbol": "SOL", "hl_name": "SOL", "name": "Solana"},
    {"ticker": "XRP-USD",       "symbol": "XRP", "hl_name": "XRP", "name": "XRP"},
    {"ticker": "ADA-USD",       "symbol": "ADA", "hl_name": "ADA", "name": "Cardano"},
    {"ticker": "AVAX-USD",      "symbol": "AVAX", "hl_name": "AVAX", "name": "Avalanche"},
    {"ticker": "DOGE-USD",      "symbol": "DOGE", "hl_name": "DOGE", "name": "Dogecoin"},
    {"ticker": "DOT-USD",       "symbol": "DOT", "hl_name": "DOT", "name": "Polkadot"},
    {"ticker": "LINK-USD",      "symbol": "LINK", "hl_name": "LINK", "name": "Chainlink"},
    {"ticker": "LTC-USD",       "symbol": "LTC", "hl_name": "LTC", "name": "Litecoin"},
    {"ticker": "UNI-USD",       "symbol": "UNI", "hl_name": "UNI", "name": "Uniswap"},
    {"ticker": "ATOM-USD",      "symbol": "ATOM", "hl_name": "ATOM", "name": "Cosmos"},
    {"ticker": "XLM-USD",       "symbol": "XLM", "hl_name": "XLM", "name": "Stellar"},
    {"ticker": "NEAR-USD",      "symbol": "NEAR", "hl_name": "NEAR", "name": "NEAR Protocol"},
    {"ticker": "OP-USD",        "symbol": "OP", "hl_name": "OP", "name": "Optimism"},
    {"ticker": "FIL-USD",       "symbol": "FIL", "hl_name": "FIL", "name": "Filecoin"},
    {"ticker": "VET-USD",       "symbol": "VET", "hl_name": "VET", "name": "VeChain"},
    {"ticker": "ALGO-USD",      "symbol": "ALGO", "hl_name": "ALGO", "name": "Algorand"},
    {"ticker": "EOS-USD",       "symbol": "EOS", "hl_name": "EOS", "name": "EOS"},
    {"ticker": "MATIC-USD",     "symbol": "MATIC", "hl_name": "MATIC", "name": "Polygon"},
    {"ticker": "ICP-USD",       "symbol": "ICP", "hl_name": "ICP", "name": "Internet Computer"},
    {"ticker": "APT-USD",       "symbol": "APT", "hl_name": "APT", "name": "Aptos"},
    {"ticker": "ARB-USD",       "symbol": "ARB", "hl_name": "ARB", "name": "Arbitrum"},
    {"ticker": "SAND-USD",      "symbol": "SAND", "hl_name": "SAND", "name": "The Sandbox"},
    {"ticker": "MANA-USD",      "symbol": "MANA", "hl_name": "MANA", "name": "Decentraland"},
    {"ticker": "AXS-USD",       "symbol": "AXS", "hl_name": "AXS", "name": "Axie Infinity"},
    {"ticker": "THETA-USD",     "symbol": "THETA", "hl_name": "THETA", "name": "Theta Network"},
    {"ticker": "TRX-USD",       "symbol": "TRX", "hl_name": "TRX", "name": "TRON"},
    {"ticker": "SHIB-USD",      "symbol": "SHIB", "hl_name": "SHIB", "name": "Shiba Inu"},
    {"ticker": "TON-USD",       "symbol": "TON", "hl_name": "TON", "name": "Toncoin"},
    {"ticker": "SUI-USD",       "symbol": "SUI", "hl_name": "SUI", "name": "Sui"},
    {"ticker": "INJ-USD",       "symbol": "INJ", "hl_name": "INJ", "name": "Injective"},
    {"ticker": "RUNE-USD",      "symbol": "RUNE", "hl_name": "RUNE", "name": "THORChain"},
    {"ticker": "FTM-USD",       "symbol": "FTM", "hl_name": "FTM", "name": "Fantom"},
    {"ticker": "HBAR-USD",      "symbol": "HBAR", "hl_name": "HBAR", "name": "Hedera"},
    {"ticker": "GRT-USD",       "symbol": "GRT", "hl_name": "GRT", "name": "The Graph"},
    {"ticker": "AAVE-USD",      "symbol": "AAVE", "hl_name": "AAVE", "name": "Aave"},
    {"ticker": "MKR-USD",       "symbol": "MKR", "hl_name": "MKR", "name": "Maker"},
    {"ticker": "SNX-USD",       "symbol": "SNX", "hl_name": "SNX", "name": "Synthetix"},
    {"ticker": "CRV-USD",       "symbol": "CRV", "hl_name": "CRV", "name": "Curve DAO"},
    {"ticker": "LDO-USD",       "symbol": "LDO", "hl_name": "LDO", "name": "Lido DAO"},
    {"ticker": "EGLD-USD",      "symbol": "EGLD", "hl_name": "EGLD", "name": "MultiversX"},
    {"ticker": "FLOW-USD",      "symbol": "FLOW", "hl_name": "FLOW", "name": "Flow"},
    {"ticker": "CHZ-USD",       "symbol": "CHZ", "hl_name": "CHZ", "name": "Chiliz"},
    {"ticker": "GALA-USD",      "symbol": "GALA", "hl_name": "GALA", "name": "Gala"},
    {"ticker": "ENJ-USD",       "symbol": "ENJ", "hl_name": "ENJ", "name": "Enjin Coin"},
    {"ticker": "ZEC-USD",       "symbol": "ZEC", "hl_name": "ZEC", "name": "Zcash"},
    {"ticker": "XMR-USD",       "symbol": "XMR", "hl_name": "XMR", "name": "Monero"},
    {"ticker": "DASH-USD",      "symbol": "DASH", "hl_name": "DASH", "name": "Dash"},
]

# ---------------------------------------------------------------------------
# Indices boursiers — tickers Yahoo Finance, non tradables sur Hyperliquid
# ---------------------------------------------------------------------------
INDICES = [
    {"ticker": "^GSPC",     "symbol": "SP500", "hl_name": None, "name": "S&P 500"},
    {"ticker": "^IXIC",     "symbol": "NASDAQ", "hl_name": None, "name": "Nasdaq Composite"},
    {"ticker": "^STOXX50E", "symbol": "STOXX50", "hl_name": None, "name": "Euro Stoxx 50"},
    {"ticker": "^FCHI",     "symbol": "CAC40", "hl_name": None, "name": "CAC 40"},
    {"ticker": "^GDAXI",    "symbol": "DAX", "hl_name": None, "name": "DAX 40"},
    {"ticker": "^DJI",      "symbol": "DOW", "hl_name": None, "name": "Dow Jones"},
    {"ticker": "^FTSE",     "symbol": "FTSE100", "hl_name": None, "name": "FTSE 100"},
    {"ticker": "^N225",     "symbol": "NIKKEI", "hl_name": None, "name": "Nikkei 225"},
]

# Liste complète = cryptos + indices
ALL_ASSETS = COINS + INDICES
