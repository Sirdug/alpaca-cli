"""Order construction shared by the CLI and MCP, with no network side effects."""

from decimal import Decimal, InvalidOperation
from typing import Optional

from .symbols import is_crypto, normalize_symbol


def positive_amount(value, name: str) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a positive, finite number.") from None
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{name} must be a positive, finite number.")
    return format(amount, "f")


def build_order(side: str, symbol: str, qty=None, notional=None, limit=None,
                stop=None, tif: Optional[str] = None, extended: bool = False) -> dict:
    symbol = normalize_symbol(symbol)
    crypto = is_crypto(symbol)
    if side not in ("buy", "sell"):
        raise ValueError("Side must be buy or sell.")
    if (qty is None) == (notional is None):
        raise ValueError("Give either a quantity or --notional, but not both.")
    tif = tif if tif is not None else ("gtc" if crypto else "day")
    if tif not in ("day", "gtc", "ioc", "fok", "opg", "cls"):
        raise ValueError("Invalid time in force.")
    if crypto:
        if tif not in ("gtc", "ioc"):
            raise ValueError("Crypto orders require --tif gtc or --tif ioc (default: gtc).")
        if stop is not None and limit is None:
            raise ValueError("Crypto supports stop-limit orders; provide both --stop and --limit.")
        if extended:
            raise ValueError("Crypto trades 24/7; --extended is only for stocks.")

    order = {"symbol": symbol, "side": side, "time_in_force": tif}
    field, value = ("qty", qty) if qty is not None else ("notional", notional)
    order[field] = positive_amount(value, field)
    if limit is not None:
        order["limit_price"] = positive_amount(limit, "Limit price")
    if stop is not None:
        order["stop_price"] = positive_amount(stop, "Stop price")
    order["type"] = ("stop_limit" if limit is not None else "stop") if stop is not None else (
        "limit" if limit is not None else "market")
    if extended:
        order["extended_hours"] = True
    return order
