"""
coins.py
Source unique de vérité pour la liste des cryptos supportées.
Importé par data_loader.py et market_data.py.

Format : {"ticker": "BTC-EUR", "symbol": "BTC", "name": "Bitcoin"}
Le champ "ticker" est le format Yahoo Finance.
"""

COINS = [
    {"ticker": "BTC-EUR",   "symbol": "BTC",   "name": "Bitcoin"},
    {"ticker": "ETH-EUR",   "symbol": "ETH",   "name": "Ethereum"},
    {"ticker": "BNB-EUR",   "symbol": "BNB",   "name": "BNB"},
    {"ticker": "SOL-EUR",   "symbol": "SOL",   "name": "Solana"},
    {"ticker": "XRP-EUR",   "symbol": "XRP",   "name": "XRP"},
    {"ticker": "ADA-EUR",   "symbol": "ADA",   "name": "Cardano"},
    {"ticker": "AVAX-EUR",  "symbol": "AVAX",  "name": "Avalanche"},
    {"ticker": "DOGE-EUR",  "symbol": "DOGE",  "name": "Dogecoin"},
    {"ticker": "DOT-EUR",   "symbol": "DOT",   "name": "Polkadot"},
    {"ticker": "LINK-EUR",  "symbol": "LINK",  "name": "Chainlink"},
    {"ticker": "LTC-EUR",   "symbol": "LTC",   "name": "Litecoin"},
    {"ticker": "UNI-EUR",   "symbol": "UNI",   "name": "Uniswap"},
    {"ticker": "ATOM-EUR",  "symbol": "ATOM",  "name": "Cosmos"},
    {"ticker": "XLM-EUR",   "symbol": "XLM",   "name": "Stellar"},
    {"ticker": "NEAR-EUR",  "symbol": "NEAR",  "name": "NEAR Protocol"},
    {"ticker": "OP-EUR",    "symbol": "OP",    "name": "Optimism"},
    {"ticker": "FIL-EUR",   "symbol": "FIL",   "name": "Filecoin"},
    {"ticker": "VET-EUR",   "symbol": "VET",   "name": "VeChain"},
    {"ticker": "ALGO-EUR",  "symbol": "ALGO",  "name": "Algorand"},
    {"ticker": "EOS-EUR",   "symbol": "EOS",   "name": "EOS"},
    {"ticker": "MATIC-EUR", "symbol": "MATIC", "name": "Polygon"},
    {"ticker": "ICP-EUR",   "symbol": "ICP",   "name": "Internet Computer"},
    {"ticker": "APT-EUR",   "symbol": "APT",   "name": "Aptos"},
    {"ticker": "ARB-EUR",   "symbol": "ARB",   "name": "Arbitrum"},
    {"ticker": "SAND-EUR",  "symbol": "SAND",  "name": "The Sandbox"},
    {"ticker": "MANA-EUR",  "symbol": "MANA",  "name": "Decentraland"},
    {"ticker": "AXS-EUR",   "symbol": "AXS",   "name": "Axie Infinity"},
    {"ticker": "THETA-EUR", "symbol": "THETA", "name": "Theta Network"},
    {"ticker": "TRX-EUR",   "symbol": "TRX",   "name": "TRON"},
    {"ticker": "SHIB-EUR",  "symbol": "SHIB",  "name": "Shiba Inu"},
    {"ticker": "TON-EUR",   "symbol": "TON",   "name": "Toncoin"},
    {"ticker": "SUI-EUR",   "symbol": "SUI",   "name": "Sui"},
    {"ticker": "INJ-EUR",   "symbol": "INJ",   "name": "Injective"},
    {"ticker": "RUNE-EUR",  "symbol": "RUNE",  "name": "THORChain"},
    {"ticker": "FTM-EUR",   "symbol": "FTM",   "name": "Fantom"},
    {"ticker": "HBAR-EUR",  "symbol": "HBAR",  "name": "Hedera"},
    {"ticker": "GRT-EUR",   "symbol": "GRT",   "name": "The Graph"},
    {"ticker": "AAVE-EUR",  "symbol": "AAVE",  "name": "Aave"},
    {"ticker": "MKR-EUR",   "symbol": "MKR",   "name": "Maker"},
    {"ticker": "SNX-EUR",   "symbol": "SNX",   "name": "Synthetix"},
    {"ticker": "CRV-EUR",   "symbol": "CRV",   "name": "Curve DAO"},
    {"ticker": "LDO-EUR",   "symbol": "LDO",   "name": "Lido DAO"},
    {"ticker": "EGLD-EUR",  "symbol": "EGLD",  "name": "MultiversX"},
    {"ticker": "FLOW-EUR",  "symbol": "FLOW",  "name": "Flow"},
    {"ticker": "CHZ-EUR",   "symbol": "CHZ",   "name": "Chiliz"},
    {"ticker": "GALA-EUR",  "symbol": "GALA",  "name": "Gala"},
    {"ticker": "ENJ-EUR",   "symbol": "ENJ",   "name": "Enjin Coin"},
    {"ticker": "ZEC-EUR",   "symbol": "ZEC",   "name": "Zcash"},
    {"ticker": "XMR-EUR",   "symbol": "XMR",   "name": "Monero"},
    {"ticker": "DASH-EUR",  "symbol": "DASH",  "name": "Dash"},
]

# ---------------------------------------------------------------------------
# Indices boursiers — tickers Yahoo Finance (pas de format SYMBOL-EUR)
# ---------------------------------------------------------------------------
INDICES = [
    {"ticker": "^GSPC",    "symbol": "SP500",   "name": "S&P 500"},
    {"ticker": "^IXIC",    "symbol": "NASDAQ",  "name": "Nasdaq Composite"},
    {"ticker": "^STOXX50E","symbol": "STOXX50", "name": "Euro Stoxx 50"},
    {"ticker": "^FCHI",    "symbol": "CAC40",   "name": "CAC 40"},
    {"ticker": "^GDAXI",   "symbol": "DAX",     "name": "DAX 40"},
    {"ticker": "^DJI",     "symbol": "DOW",     "name": "Dow Jones"},
    {"ticker": "^FTSE",    "symbol": "FTSE100", "name": "FTSE 100"},
    {"ticker": "^N225",    "symbol": "NIKKEI",  "name": "Nikkei 225"},
]

# Liste complète = cryptos + indices
ALL_ASSETS = COINS + INDICES
