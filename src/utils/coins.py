"""
coins.py
Source unique de vérité pour la liste des cryptos supportées.
Importé par data_loader.py et market_data.py.

Format : {"ticker": "BTC-USD", "symbol": "BTC", "name": "Bitcoin"}
Le champ "ticker" est le format Yahoo Finance.
"""

COINS = [
    {"ticker": "BTC-USD",   "symbol": "BTC",   "name": "Bitcoin"},
    {"ticker": "ETH-USD",   "symbol": "ETH",   "name": "Ethereum"},
    {"ticker": "BNB-USD",   "symbol": "BNB",   "name": "BNB"},
    {"ticker": "SOL-USD",   "symbol": "SOL",   "name": "Solana"},
    {"ticker": "XRP-USD",   "symbol": "XRP",   "name": "XRP"},
    {"ticker": "ADA-USD",   "symbol": "ADA",   "name": "Cardano"},
    {"ticker": "AVAX-USD",  "symbol": "AVAX",  "name": "Avalanche"},
    {"ticker": "DOGE-USD",  "symbol": "DOGE",  "name": "Dogecoin"},
    {"ticker": "DOT-USD",   "symbol": "DOT",   "name": "Polkadot"},
    {"ticker": "LINK-USD",  "symbol": "LINK",  "name": "Chainlink"},
    {"ticker": "LTC-USD",   "symbol": "LTC",   "name": "Litecoin"},
    {"ticker": "UNI-USD",   "symbol": "UNI",   "name": "Uniswap"},
    {"ticker": "ATOM-USD",  "symbol": "ATOM",  "name": "Cosmos"},
    {"ticker": "XLM-USD",   "symbol": "XLM",   "name": "Stellar"},
    {"ticker": "NEAR-USD",  "symbol": "NEAR",  "name": "NEAR Protocol"},
    {"ticker": "OP-USD",    "symbol": "OP",    "name": "Optimism"},
    {"ticker": "FIL-USD",   "symbol": "FIL",   "name": "Filecoin"},
    {"ticker": "VET-USD",   "symbol": "VET",   "name": "VeChain"},
    {"ticker": "ALGO-USD",  "symbol": "ALGO",  "name": "Algorand"},
    {"ticker": "EOS-USD",   "symbol": "EOS",   "name": "EOS"},
    {"ticker": "MATIC-USD", "symbol": "MATIC", "name": "Polygon"},
    {"ticker": "ICP-USD",   "symbol": "ICP",   "name": "Internet Computer"},
    {"ticker": "APT-USD",   "symbol": "APT",   "name": "Aptos"},
    {"ticker": "ARB-USD",   "symbol": "ARB",   "name": "Arbitrum"},
    {"ticker": "SAND-USD",  "symbol": "SAND",  "name": "The Sandbox"},
    {"ticker": "MANA-USD",  "symbol": "MANA",  "name": "Decentraland"},
    {"ticker": "AXS-USD",   "symbol": "AXS",   "name": "Axie Infinity"},
    {"ticker": "THETA-USD", "symbol": "THETA", "name": "Theta Network"},
    {"ticker": "TRX-USD",   "symbol": "TRX",   "name": "TRON"},
    {"ticker": "SHIB-USD",  "symbol": "SHIB",  "name": "Shiba Inu"},
    {"ticker": "TON-USD",   "symbol": "TON",   "name": "Toncoin"},
    {"ticker": "SUI-USD",   "symbol": "SUI",   "name": "Sui"},
    {"ticker": "INJ-USD",   "symbol": "INJ",   "name": "Injective"},
    {"ticker": "RUNE-USD",  "symbol": "RUNE",  "name": "THORChain"},
    {"ticker": "FTM-USD",   "symbol": "FTM",   "name": "Fantom"},
    {"ticker": "HBAR-USD",  "symbol": "HBAR",  "name": "Hedera"},
    {"ticker": "GRT-USD",   "symbol": "GRT",   "name": "The Graph"},
    {"ticker": "AAVE-USD",  "symbol": "AAVE",  "name": "Aave"},
    {"ticker": "MKR-USD",   "symbol": "MKR",   "name": "Maker"},
    {"ticker": "SNX-USD",   "symbol": "SNX",   "name": "Synthetix"},
    {"ticker": "CRV-USD",   "symbol": "CRV",   "name": "Curve DAO"},
    {"ticker": "LDO-USD",   "symbol": "LDO",   "name": "Lido DAO"},
    {"ticker": "EGLD-USD",  "symbol": "EGLD",  "name": "MultiversX"},
    {"ticker": "FLOW-USD",  "symbol": "FLOW",  "name": "Flow"},
    {"ticker": "CHZ-USD",   "symbol": "CHZ",   "name": "Chiliz"},
    {"ticker": "GALA-USD",  "symbol": "GALA",  "name": "Gala"},
    {"ticker": "ENJ-USD",   "symbol": "ENJ",   "name": "Enjin Coin"},
    {"ticker": "ZEC-USD",   "symbol": "ZEC",   "name": "Zcash"},
    {"ticker": "XMR-USD",   "symbol": "XMR",   "name": "Monero"},
    {"ticker": "DASH-USD",  "symbol": "DASH",  "name": "Dash"},
]

# ---------------------------------------------------------------------------
# Indices boursiers — tickers Yahoo Finance (pas de format SYMBOL-USD)
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
