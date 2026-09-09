"""Consistent stock symbols and explicit crypto BASE/QUOTE pairs."""

import re
from urllib.parse import quote


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    # Accept the familiar BTC-USD spelling without changing BRK-B or asset UUIDs.
    if re.fullmatch(r"[A-Z0-9]+-(USD|USDT|USDC|BTC|ETH)", symbol):
        symbol = symbol.replace("-", "/")
    if not symbol or ("/" in symbol and not re.fullmatch(r"[A-Z0-9]+/[A-Z0-9]+", symbol)):
        raise ValueError("Use a stock symbol or a crypto pair such as BTC/USD.")
    return symbol


def is_crypto(symbol: str) -> bool:
    return "/" in normalize_symbol(symbol)


def symbol_path(symbol: str) -> str:
    """Encode a symbol as one URL path component (including a crypto slash)."""
    return quote(normalize_symbol(symbol), safe="")
