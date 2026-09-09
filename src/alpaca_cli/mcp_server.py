"""MCP server exposing the Alpaca CLI as tools for LLM clients.

Runs over stdio. Credentials resolve exactly as in the CLI (env vars first,
then ~/.config/alpaca-cli/config.json), and paper mode is the default.

Safety: buy/sell/close_position require an explicit confirm=True argument;
LLM clients cannot answer interactive prompts.
"""

from typing import List, Optional

from mcp.server.mcpserver import MCPServer

from .client import AlpacaClient, APIError
from .config import ConfigError, resolve_credentials
from .marketdata import available_sources, bars as marketdata_bars, quote as marketdata_quote
from .symbols import symbol_path
from .trading import build_order, positive_amount

mcp = MCPServer("alpaca")


def _client() -> AlpacaClient:
    return AlpacaClient(resolve_credentials())


def _err(e: Exception) -> str:
    if isinstance(e, APIError):
        return f"{e.message} (HTTP {e.status})"
    return str(e)


# ---------------------------------------------------------------- account


@mcp.tool()
def account() -> dict:
    """Show account balances and status (equity, cash, buying power)."""
    return _client().get("/v2/account")


@mcp.tool()
def positions() -> dict:
    """List open positions with unrealized P/L."""
    return {"positions": _client().get("/v2/positions")}


# ---------------------------------------------------------------- orders


@mcp.tool()
def orders(status: str = "open", limit: int = 50) -> dict:
    """List orders. status: open (default), closed, or all."""
    return {"orders": _client().get("/v2/orders", params={"status": status, "limit": limit})}


@mcp.tool()
def order_get(order_id: str) -> dict:
    """Show one order by id (a short id prefix also works)."""
    if len(order_id) >= 32:
        return _client().get(f"/v2/orders/{order_id}")
    matches = [
        o for o in _client().get("/v2/orders", params={"status": "all", "limit": 500})
        if o.get("id", "").startswith(order_id)
    ]
    if len(matches) == 1:
        return matches[0]
    raise APIError(404, f"{'Multiple' if matches else 'No'} orders match id prefix '{order_id}'.")


@mcp.tool()
def order_cancel(order_id: str) -> dict:
    """Cancel an open order by id (short id prefix ok)."""
    oid = order_get(order_id)["id"]
    _client().delete(f"/v2/orders/{oid}")
    return {"canceled": oid}


@mcp.tool()
def order_cancel_all() -> dict:
    """Cancel all open orders."""
    data = _client().delete("/v2/orders")
    return {"canceled": len(data or [])}


# ---------------------------------------------------------------- trading


def _submit(side: str, symbol: str, qty: Optional[float], notional: Optional[float],
            limit: Optional[float], stop: Optional[float], tif: Optional[str], extended: bool) -> dict:
    order = build_order(side, symbol, qty, notional, limit, stop, tif, extended)
    return _client().post("/v2/orders", json=order)


@mcp.tool()
def buy(symbol: str, qty: Optional[float] = None, notional: Optional[float] = None,
        limit: Optional[float] = None, stop: Optional[float] = None,
        tif: Optional[str] = None, extended: bool = False, confirm: bool = False) -> dict:
    """Buy stocks or crypto (paper by default). Use BTC/USD for crypto.
    qty = shares/coins; notional = dollar amount. Default tif: day for stocks,
    gtc for crypto. Crypto allows gtc/ioc, market/limit/stop-limit, no extended hours.
    REQUIRED: pass confirm=True to submit; otherwise this tool refuses the order."""
    if not confirm:
        raise ValueError("Refusing to submit without confirm=True. Pass confirm=True to place this order.")
    try:
        return _submit("buy", symbol, qty, notional, limit, stop, tif, extended)
    except APIError as e:
        raise ValueError(_err(e))


@mcp.tool()
def sell(symbol: str, qty: Optional[float] = None, notional: Optional[float] = None,
         limit: Optional[float] = None, stop: Optional[float] = None,
         tif: Optional[str] = None, extended: bool = False, confirm: bool = False) -> dict:
    """Sell stocks or crypto (paper by default). Use BTC/USD for crypto.
    qty = shares/coins; notional = dollar amount. Default tif: day for stocks,
    gtc for crypto. Crypto allows gtc/ioc, market/limit/stop-limit, no extended hours.
    REQUIRED: pass confirm=True to submit; otherwise this tool refuses the order."""
    if not confirm:
        raise ValueError("Refusing to submit without confirm=True. Pass confirm=True to place this order.")
    try:
        return _submit("sell", symbol, qty, notional, limit, stop, tif, extended)
    except APIError as e:
        raise ValueError(_err(e))


@mcp.tool()
def close_position(symbol: Optional[str] = None, qty: Optional[float] = None,
                   close_all: bool = False, confirm: bool = False) -> dict:
    """Close a position (paper by default). Give symbol (and optional qty), or close_all=True.
    REQUIRED: pass confirm=True to actually submit; confirm=False only validates."""
    if not confirm:
        raise ValueError("Refusing to submit without confirm=True. Pass confirm=True to close.")
    c = _client()
    if close_all:
        data = c.delete("/v2/positions")
        return {"submitted": len(data or [])}
    if not symbol:
        raise ValueError("Give a symbol or pass close_all=True.")
    params = {"qty": positive_amount(qty, "Quantity")} if qty is not None else None
    data = c.delete(f"/v2/positions/{symbol_path(symbol)}", params=params)
    return {"order_id": data.get("id")}


# ---------------------------------------------------------------- market data


@mcp.tool()
def quote(symbols: List[str], source: str = "auto") -> dict:
    """Latest quote and trade for one or more symbols, e.g. quote(["AAPL", "MSFT"]).
    source: auto (best available) | finnhub (real-time price) | alpaca (full-market
    bid/ask, ~15 min delay) | yahoo | iex. Returns per-symbol last, bid, ask, sizes,
    timestamps, per-field source, and a stale flag. Crypto pairs such as BTC/USD
    use Alpaca crypto with source=auto or alpaca; mixed stocks/crypto are supported."""
    return marketdata_quote(symbols, source=source, client=_client())


@mcp.tool()
def bars(symbol: str, timeframe: str = "1Day", limit: int = 10,
         start: Optional[str] = None, end: Optional[str] = None,
         source: str = "auto") -> dict:
    """Historical OHLCV bars (oldest first). timeframe in 1Min,5Min,15Min,30Min,1Hour,
    1Day,1Week,1Month. source: auto | finnhub | alpaca | yahoo | iex.
    Crypto pairs such as BTC/USD use source=auto or alpaca. Dates without a zone use UTC.
    Returns {"bars": [...], "source": "..."}."""
    return marketdata_bars(symbol, timeframe=timeframe, limit=limit, start=start,
                           end=end, source=source, client=_client())


@mcp.tool()
def data_sources() -> dict:
    """Probe market data sources (Alpaca crypto, finnhub, delayed_sip, yahoo, iex)."""
    return {"sources": available_sources(_client())}


@mcp.tool()
def news(symbols: Optional[str] = None, limit: int = 10) -> dict:
    """Latest market news headlines. symbols: comma-separated list to filter."""
    params: dict = {"limit": limit}
    if symbols:
        params["symbols"] = symbols.upper()
    data = _client().get("/v1beta1/news", data_api=True, params=params)
    return {"news": data.get("news", [])}


@mcp.tool()
def asset(symbol: str) -> dict:
    """Show asset details, including crypto minimum quantity and price increments."""
    return _client().get(f"/v2/assets/{symbol_path(symbol)}")


@mcp.tool()
def assets(asset_class: Optional[str] = None, status: str = "active") -> dict:
    """List assets. Use asset_class='crypto' to discover available trading pairs."""
    if asset_class not in (None, "us_equity", "crypto"):
        raise ValueError("asset_class must be us_equity or crypto.")
    if status not in ("active", "inactive"):
        raise ValueError("status must be active or inactive.")
    params = {"status": status}
    if asset_class:
        params["asset_class"] = asset_class
    return {"assets": _client().get("/v2/assets", params=params)}


@mcp.tool()
def clock() -> dict:
    """Is the stock market open? (timestamp, next open/close). Crypto trades 24/7."""
    return _client().get("/v2/clock")


@mcp.tool()
def calendar(start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """Market calendar. start/end as YYYY-MM-DD; defaults to the next ~10 days."""
    params: dict = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    data = _client().get("/v2/calendar", params=params or None)
    if not (start or end):
        data = data[:10]
    return {"days": data}


# ---------------------------------------------------------------- watchlists


@mcp.tool()
def watchlists() -> dict:
    """List watchlists."""
    return {"watchlists": _client().get("/v2/watchlists")}


@mcp.tool()
def watchlist_show(name: str) -> dict:
    """Show a watchlist's symbols and current prices, by name or id prefix."""
    c = _client()
    wid = None
    for w in c.get("/v2/watchlists"):
        if w.get("name", "").lower() == name.lower() or w.get("id", "").startswith(name):
            wid = w["id"]
            break
    if not wid:
        raise ValueError(f"No watchlist named '{name}'.")
    return c.get(f"/v2/watchlists/{wid}")


def main() -> None:
    try:
        resolve_credentials()
    except ConfigError as e:
        raise SystemExit(f"alpaca-mcp: {e}")
    mcp.run()


if __name__ == "__main__":
    main()
