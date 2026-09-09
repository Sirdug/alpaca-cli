"""alpaca — command-line interface for the Alpaca Trading and Market Data APIs."""

import functools
import sys
from typing import Optional

import click

from . import __version__
from .client import AlpacaClient, APIError
from .config import (
    CONFIG_PATH,
    ConfigError,
    load_config,
    resolve_credentials,
    save_config,
)
from .marketdata import SOURCES, available_sources, bars as marketdata_bars, quote as marketdata_quote
from .symbols import is_crypto, normalize_symbol, symbol_path
from .trading import build_order, positive_amount
from .output import (
    money,
    num,
    price,
    print_json,
    print_kv,
    print_table,
    signed_money,
    signed_pct,
    ts,
)

TIMEFRAMES = ["1Min", "5Min", "15Min", "30Min", "1Hour", "1Day", "1Week", "1Month"]


def output_options(fn):
    """Add --json and --query to a command."""

    @click.option("--json", "-j", "as_json", is_flag=True, help="Output raw JSON.")
    @click.option("--query", "-q", default=None, help="JMESPath filter (implies --json).")
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper


def get_client(ctx: click.Context) -> AlpacaClient:
    if "client" not in ctx.obj:
        creds = resolve_credentials(ctx.obj.get("profile"))
        ctx.obj["creds"] = creds
        ctx.obj["client"] = AlpacaClient(creds)
    return ctx.obj["client"]


@click.group()
@click.version_option(__version__, prog_name="alpaca")
@click.option("--profile", "-p", default=None, help="Use a named profile from the config file.")
@click.pass_context
def main(ctx, profile):
    """Trade stocks and crypto, and pull market data from your terminal.

    Paper trading is the default. Run 'alpaca setup' once to save your API
    keys, then try 'alpaca account', 'alpaca quote AAPL', or
    'alpaca buy AAPL 1 --dry-run'.
    """
    ctx.obj = {"profile": profile}


def run(ctx, fn):
    """Call fn(client) with friendly error reporting."""
    try:
        return fn(get_client(ctx))
    except ConfigError as e:
        raise click.ClickException(str(e))
    except APIError as e:
        raise click.ClickException(e.message or f"HTTP {e.status}")
    except ValueError as e:
        raise click.ClickException(str(e))


# ---------------------------------------------------------------- setup


@main.command()
@click.option("--profile", "-p", default="default", help="Profile name to create or update.")
def setup(profile):
    """Save your Alpaca API keys (interactive)."""
    click.echo("Get your API keys from https://app.alpaca.markets (paper keys recommended).")
    api_key = click.prompt("API key ID").strip()
    secret_key = click.prompt("Secret key", hide_input=True).strip()
    live = click.confirm("Use LIVE trading for this profile? (paper is recommended)", default=False)

    config = load_config()
    config.setdefault("profiles", {})[profile] = {
        "api_key": api_key,
        "secret_key": secret_key,
        "mode": "live" if live else "paper",
    }
    config.setdefault("default_profile", profile)
    save_config(config)
    click.echo(f"Saved profile '{profile}' ({'LIVE' if live else 'paper'}) to {CONFIG_PATH}")
    click.echo("Try: alpaca doctor")


@main.group()
def profile():
    """Manage saved profiles."""


@profile.command("list")
def profile_list():
    """List saved profiles."""
    config = load_config()
    default = config.get("default_profile")
    rows = [
        {"name": name, "mode": p.get("mode", "paper"), "default": "*" if name == default else ""}
        for name, p in sorted(config.get("profiles", {}).items())
    ]
    print_table(
        [
            ("NAME", lambda r: r["name"]),
            ("MODE", lambda r: r["mode"]),
            ("DEFAULT", lambda r: r["default"]),
        ],
        rows,
    )


@profile.command("use")
@click.argument("name")
def profile_use(name):
    """Set the default profile."""
    config = load_config()
    if name not in config.get("profiles", {}):
        raise click.ClickException(f"Profile '{name}' not found.")
    config["default_profile"] = name
    save_config(config)
    click.echo(f"Default profile is now '{name}'.")


@profile.command("remove")
@click.argument("name")
def profile_remove(name):
    """Delete a saved profile."""
    config = load_config()
    if name not in config.get("profiles", {}):
        raise click.ClickException(f"Profile '{name}' not found.")
    if not click.confirm(f"Delete profile '{name}'?"):
        raise click.Abort()
    del config["profiles"][name]
    if config.get("default_profile") == name:
        config["default_profile"] = next(iter(config["profiles"]), "default")
    save_config(config)
    click.echo(f"Removed profile '{name}'.")


@main.command()
@click.pass_context
def doctor(ctx):
    """Check configuration and connectivity."""
    ok = True
    try:
        creds = resolve_credentials(ctx.obj.get("profile"))
        mode = "paper" if creds.paper else click.style("LIVE", fg="red", bold=True)
        click.echo(f"✓ Credentials found ({creds.source}, {mode})")
    except ConfigError as e:
        click.echo(f"✗ {e}")
        sys.exit(1)

    client = AlpacaClient(creds)
    try:
        acct = client.get("/v2/account")
        click.echo(f"✓ Trading API reachable (account {acct.get('account_number', '?')}, "
                   f"status {acct.get('status', '?')})")
    except APIError as e:
        click.echo(f"✗ Trading API: {e.message}")
        ok = False
    try:
        client.get("/v2/stocks/AAPL/trades/latest", data_api=True)
        click.echo("✓ Market Data API reachable")
    except APIError as e:
        click.echo(f"✗ Market Data API: {e.message} "
                   "(free accounts may lack some data subscriptions)")
        ok = False
    try:
        clock = client.get("/v2/clock")
        state = "open" if clock.get("is_open") else "closed"
        click.echo(f"✓ Market is {state} (next open {ts(clock.get('next_open'))})")
    except APIError:
        pass

    click.echo("Data sources:")
    for name, info in available_sources(client).items():
        if info["available"]:
            click.echo(f"  ✓ {name}: {info.get('note', 'ok')}")
        else:
            click.echo(f"  ✗ {name}: {info.get('note', 'unavailable')}")
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- account


@main.command()
@output_options
@click.pass_context
def account(ctx, as_json, query):
    """Show account balances and status."""
    data = run(ctx, lambda c: c.get("/v2/account"))
    if as_json or query:
        return print_json(data, query)
    creds = ctx.obj["creds"]
    print_kv(
        [
            ("Account", data.get("account_number", "-")),
            ("Mode", "paper" if creds.paper else click.style("LIVE", fg="red", bold=True)),
            ("Status", data.get("status", "-")),
            ("Equity", money(data.get("equity"))),
            ("Cash", money(data.get("cash"))),
            ("Buying power", money(data.get("buying_power"))),
            ("Portfolio value", money(data.get("portfolio_value"))),
            ("Day trades (5d)", str(data.get("daytrade_count", "-"))),
        ]
    )


# ---------------------------------------------------------------- orders


def submit_order(ctx, side, symbol, qty, notional, limit, stop, tif, extended, dry_run, yes,
                 as_json, query):
    try:
        order = build_order(side, symbol, qty, notional, limit, stop, tif, extended)
    except ValueError as e:
        raise click.ClickException(str(e))
    symbol, tif = order["symbol"], order["time_in_force"]
    unit = symbol.split("/")[0] if is_crypto(symbol) else "share(s)"
    amount = money(notional) + " worth" if notional is not None else f"{num(qty)} {unit}"
    detail = "market"
    if stop is not None and limit is not None:
        detail = f"stop {price(stop, symbol)} then limit {price(limit, symbol)}"
    elif limit is not None:
        detail = f"limit {price(limit, symbol)}"
    elif stop is not None:
        detail = f"stop {price(stop, symbol)}"
    summary = f"{side.upper()} {amount} of {symbol} ({detail}, {tif})"

    try:
        creds_paper = resolve_credentials(ctx.obj.get("profile")).paper
    except ConfigError as e:
        raise click.ClickException(str(e))
    banner = "" if creds_paper else click.style(" [LIVE ACCOUNT — REAL MONEY]", fg="red", bold=True)

    if dry_run:
        if as_json or query:
            return print_json({"dry_run": True, "paper": creds_paper, "order": order}, query)
        click.echo(f"DRY RUN — would submit: {summary}{banner}")
        return
    if not yes:
        click.confirm(f"Submit: {summary}{banner}?", abort=True)
    data = run(ctx, lambda c: c.post("/v2/orders", json=order))
    if as_json or query:
        return print_json(data, query)
    click.echo(
        f"Order {data.get('status', 'submitted')}: {summary}\n"
        f"id: {data.get('id')}"
    )


def order_flags(fn):
    fn = click.option("--notional", "-n", type=str, default=None, metavar="AMOUNT",
                      help="Dollar amount instead of share/coin quantity.")(fn)
    fn = click.option("--limit", "-l", type=str, default=None, metavar="PRICE", help="Limit price.")(fn)
    fn = click.option("--stop", "-s", type=str, default=None, metavar="PRICE", help="Stop price (crypto also needs --limit).")(fn)
    fn = click.option("--tif", type=click.Choice(["day", "gtc", "ioc", "fok", "opg", "cls"]),
                      default=None, help="Time in force (default: day for stocks, gtc for crypto).")(fn)
    fn = click.option("--extended", is_flag=True, help="Allow extended-hours execution.")(fn)
    fn = click.option("--dry-run", is_flag=True, help="Show the order without submitting.")(fn)
    fn = click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")(fn)
    return fn


@main.command()
@click.argument("symbol")
@click.argument("qty", type=str, required=False)
@order_flags
@output_options
@click.pass_context
def buy(ctx, symbol, qty, **kwargs):
    """Buy stocks or crypto: alpaca buy AAPL 5 / alpaca buy BTC/USD --notional 100."""
    submit_order(ctx, "buy", symbol, qty, kwargs["notional"], kwargs["limit"], kwargs["stop"],
                 kwargs["tif"], kwargs["extended"], kwargs["dry_run"], kwargs["yes"],
                 kwargs["as_json"], kwargs["query"])


@main.command()
@click.argument("symbol")
@click.argument("qty", type=str, required=False)
@order_flags
@output_options
@click.pass_context
def sell(ctx, symbol, qty, **kwargs):
    """Sell stocks or crypto: alpaca sell AAPL 5 / alpaca sell BTC/USD 0.001."""
    submit_order(ctx, "sell", symbol, qty, kwargs["notional"], kwargs["limit"], kwargs["stop"],
                 kwargs["tif"], kwargs["extended"], kwargs["dry_run"], kwargs["yes"],
                 kwargs["as_json"], kwargs["query"])


@main.group()
def order():
    """List, inspect, and cancel orders."""


ORDER_COLUMNS = [
    ("ID", lambda o: o.get("id", "")[:8]),
    ("SYMBOL", lambda o: o.get("symbol", "-")),
    ("SIDE", lambda o: o.get("side", "-")),
    ("QTY", lambda o: num(o.get("qty") or o.get("notional"))),
    ("TYPE", lambda o: o.get("type", "-")),
    ("LIMIT", lambda o: price(o.get("limit_price"), o.get("symbol", "-"))),
    ("STOP", lambda o: price(o.get("stop_price"), o.get("symbol", "-"))),
    ("STATUS", lambda o: o.get("status", "-")),
    ("FILLED", lambda o: num(o.get("filled_qty"))),
    ("SUBMITTED", lambda o: ts(o.get("submitted_at"))),
]


@order.command("list")
@click.option("--status", type=click.Choice(["open", "closed", "all"]), default="open",
              show_default=True)
@click.option("--limit", type=int, default=50, show_default=True)
@output_options
@click.pass_context
def order_list(ctx, status, limit, as_json, query):
    """List orders (open by default)."""
    data = run(ctx, lambda c: c.get("/v2/orders", params={"status": status, "limit": limit}))
    if as_json or query:
        return print_json(data, query)
    print_table(ORDER_COLUMNS, data)


@order.command("get")
@click.argument("order_id")
@output_options
@click.pass_context
def order_get(ctx, order_id, as_json, query):
    """Show one order. A short ID prefix from 'order list' works."""
    data = run(ctx, lambda c: _find_order(c, order_id))
    if as_json or query:
        return print_json(data, query)
    pairs = [(k.upper().replace("_", " "), str(v)) for k, v in data.items() if v is not None]
    print_kv(pairs)


def _find_order(client, order_id):
    if len(order_id) >= 32:
        return client.get(f"/v2/orders/{order_id}")
    matches = [
        o for o in client.get("/v2/orders", params={"status": "all", "limit": 500})
        if o.get("id", "").startswith(order_id)
    ]
    if len(matches) == 1:
        return matches[0]
    raise APIError(404, f"{'Multiple' if matches else 'No'} orders match id prefix '{order_id}'.")


@order.command("cancel")
@click.argument("order_id")
@click.pass_context
def order_cancel(ctx, order_id):
    """Cancel an open order by ID (short prefix ok)."""
    def do(c):
        oid = _find_order(c, order_id)["id"] if len(order_id) < 32 else order_id
        c.delete(f"/v2/orders/{oid}")
        return oid
    oid = run(ctx, do)
    click.echo(f"Canceled order {oid}.")


@order.command("cancel-all")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def order_cancel_all(ctx, yes):
    """Cancel all open orders."""
    if not yes:
        click.confirm("Cancel ALL open orders?", abort=True)
    data = run(ctx, lambda c: c.delete("/v2/orders"))
    click.echo(f"Canceled {len(data or [])} order(s).")


# ---------------------------------------------------------------- positions


@main.command()
@output_options
@click.pass_context
def positions(ctx, as_json, query):
    """List open positions with P/L."""
    data = run(ctx, lambda c: c.get("/v2/positions"))
    if as_json or query:
        return print_json(data, query)
    print_table(
        [
            ("SYMBOL", lambda p: p.get("symbol", "-")),
            ("QTY", lambda p: num(p.get("qty"))),
            ("ENTRY", lambda p: price(p.get("avg_entry_price"), p.get("symbol", "-"))),
            ("PRICE", lambda p: price(p.get("current_price"), p.get("symbol", "-"))),
            ("VALUE", lambda p: money(p.get("market_value"))),
            ("P/L", lambda p: signed_money(p.get("unrealized_pl"))),
            ("P/L %", lambda p: signed_pct(p.get("unrealized_plpc"))),
            ("TODAY", lambda p: signed_pct(p.get("change_today"))),
        ],
        data,
    )


@main.command()
@click.argument("symbol", required=False)
@click.option("--all", "close_all", is_flag=True, help="Close every open position.")
@click.option("--qty", type=str, default=None, help="Close only this many shares or coins.")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def close(ctx, symbol, close_all, qty, yes):
    """Close a position: alpaca close AAPL  (or --all)."""
    if close_all:
        if not yes:
            click.confirm("Close ALL open positions?", abort=True)
        data = run(ctx, lambda c: c.delete("/v2/positions"))
        click.echo(f"Submitted close orders for {len(data or [])} position(s).")
        return
    if not symbol:
        raise click.ClickException("Give a symbol (alpaca close AAPL) or use --all.")
    try:
        symbol = normalize_symbol(symbol)
        if qty is not None:
            qty = positive_amount(qty, "Quantity")
    except ValueError as e:
        raise click.ClickException(str(e))
    unit = symbol.split("/")[0] if is_crypto(symbol) else "share(s)"
    what = f"{qty} {unit} of {symbol}" if qty else f"position in {symbol}"
    if not yes:
        click.confirm(f"Close {what}?", abort=True)
    params = {"qty": str(qty)} if qty else None
    data = run(ctx, lambda c: c.delete(f"/v2/positions/{symbol_path(symbol)}", params=params))
    click.echo(f"Close order submitted for {what} (order id {data.get('id')}).")


# ---------------------------------------------------------------- market data


@main.command()
@click.argument("symbols", nargs=-1, required=True)
@click.option("--source", type=click.Choice(SOURCES), default="auto", show_default=True,
              help="Market data source (auto = best available).")
@output_options
@click.pass_context
def quote(ctx, symbols, source, as_json, query):
    """Latest quote and trade: alpaca quote AAPL BTC/USD ETH/USD."""
    data = run(ctx, lambda c: marketdata_quote(list(symbols), source=source, client=c))
    if as_json or query:
        return print_json(data, query)
    rows = list(data["quotes"].values())
    for r in rows:
        r["_time"] = ts(r.get("last_time") or r.get("quote_time"))
        if r.get("stale"):
            r["_time"] += click.style(" [stale]", fg="red", dim=True)
        ls, qs = r.get("last_source"), r.get("quote_source")
        r["_src"] = ls if ls == qs else "/".join(x for x in (ls, qs) if x)
    print_table(
        [
            ("SYMBOL", lambda r: r["symbol"]),
            ("LAST", lambda r: price(r.get("last"), r["symbol"])),
            ("BID", lambda r: price(r.get("bid"), r["symbol"])),
            ("ASK", lambda r: price(r.get("ask"), r["symbol"])),
            ("BIDSZ", lambda r: num(r.get("bid_size"))),
            ("ASKSZ", lambda r: num(r.get("ask_size"))),
            ("TIME", lambda r: r["_time"]),
            ("SRC", lambda r: r["_src"]),
        ],
        rows,
    )


@main.command()
@click.argument("symbol")
@click.option("--timeframe", "-t", type=click.Choice(TIMEFRAMES), default="1Day",
              show_default=True)
@click.option("--limit", type=click.IntRange(min=1), default=10, show_default=True, help="Number of bars.")
@click.option("--start", default=None, help="Start date/time (e.g. 2026-07-01).")
@click.option("--end", default=None, help="End date/time.")
@click.option("--source", type=click.Choice(SOURCES), default="auto", show_default=True,
              help="Market data source (auto = best available).")
@output_options
@click.pass_context
def bars(ctx, symbol, timeframe, limit, start, end, source, as_json, query):
    """Historical OHLCV bars: alpaca bars BTC/USD -t 1Hour."""
    data = run(ctx, lambda c: marketdata_bars(
        symbol, timeframe=timeframe, limit=limit, start=start, end=end,
        source=source, client=c))
    if as_json or query:
        return print_json(data, query)
    rows = data.get("bars") or []
    click.echo(click.style(f"{symbol} {timeframe} bars ({data.get('source', '?')})", bold=True))
    print_table(
        [
            ("TIME", lambda b: ts(b.get("time"))),
            ("OPEN", lambda b: price(b.get("open"), symbol)),
            ("HIGH", lambda b: price(b.get("high"), symbol)),
            ("LOW", lambda b: price(b.get("low"), symbol)),
            ("CLOSE", lambda b: price(b.get("close"), symbol)),
            ("VOLUME", lambda b: num(b.get("volume"))),
        ],
        rows,
    )


@main.command()
@click.option("--symbols", "-s", default=None, help="Comma-separated symbols to filter.")
@click.option("--limit", type=int, default=10, show_default=True)
@output_options
@click.pass_context
def news(ctx, symbols, limit, as_json, query):
    """Latest market news headlines."""
    params = {"limit": limit}
    if symbols:
        params["symbols"] = symbols.upper()
    data = run(ctx, lambda c: c.get("/v1beta1/news", data_api=True, params=params))
    if as_json or query:
        return print_json(data, query)
    for item in data.get("news", []):
        syms = ",".join(item.get("symbols", []))
        click.echo(f"{click.style(ts(item.get('created_at')), dim=True)}  "
                   f"[{syms}] {click.style(item.get('headline', ''), bold=True)}")
        if item.get("url"):
            click.echo(f"    {item['url']}")


# ---------------------------------------------------------------- misc


@main.command()
@click.argument("symbol")
@output_options
@click.pass_context
def asset(ctx, symbol, as_json, query):
    """Show asset details (tradable, fractionable, shortable...)."""
    data = run(ctx, lambda c: c.get(f"/v2/assets/{symbol_path(symbol)}"))
    if as_json or query:
        return print_json(data, query)
    print_kv([(k.upper().replace("_", " "), str(v)) for k, v in data.items()])


@main.command()
@click.option("--class", "asset_class", type=click.Choice(["us_equity", "crypto"]), default=None,
              help="Filter assets by class; use crypto to discover available pairs.")
@click.option("--status", type=click.Choice(["active", "inactive"]), default="active", show_default=True)
@output_options
@click.pass_context
def assets(ctx, asset_class, status, as_json, query):
    """List available assets: alpaca assets --class crypto."""
    params = {"status": status}
    if asset_class:
        params["asset_class"] = asset_class
    data = run(ctx, lambda c: c.get("/v2/assets", params=params))
    if as_json or query:
        return print_json(data, query)
    print_table([
        ("SYMBOL", lambda a: a.get("symbol", "-")),
        ("CLASS", lambda a: a.get("class", "-")),
        ("TRADABLE", lambda a: str(a.get("tradable", False))),
        ("MIN QTY", lambda a: num(a.get("min_order_size"))),
        ("QTY STEP", lambda a: num(a.get("min_trade_increment"))),
        ("PRICE STEP", lambda a: num(a.get("price_increment"))),
    ], data)


@main.command()
@output_options
@click.pass_context
def clock(ctx, as_json, query):
    """Is the stock market open? Crypto trades 24/7."""
    data = run(ctx, lambda c: c.get("/v2/clock"))
    if as_json or query:
        return print_json(data, query)
    state = click.style("OPEN", fg="green", bold=True) if data.get("is_open") else click.style(
        "CLOSED", fg="red", bold=True)
    print_kv(
        [
            ("Market", state),
            ("Now", ts(data.get("timestamp"))),
            ("Next open", ts(data.get("next_open"))),
            ("Next close", ts(data.get("next_close"))),
        ]
    )


@main.command()
@click.option("--start", default=None, help="Start date (YYYY-MM-DD).")
@click.option("--end", default=None, help="End date (YYYY-MM-DD).")
@output_options
@click.pass_context
def calendar(ctx, start, end, as_json, query):
    """Stock market calendar (defaults to around today). Crypto trades 24/7."""
    params = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    data = run(ctx, lambda c: c.get("/v2/calendar", params=params or None))
    if not (start or end):
        data = data[:10]
    if as_json or query:
        return print_json(data, query)
    print_table(
        [
            ("DATE", lambda d: d.get("date", "-")),
            ("OPEN", lambda d: d.get("open", "-")),
            ("CLOSE", lambda d: d.get("close", "-")),
        ],
        data,
    )


# ---------------------------------------------------------------- watchlists


@main.group()
def watchlist():
    """Manage watchlists."""


@watchlist.command("list")
@output_options
@click.pass_context
def watchlist_list(ctx, as_json, query):
    """List watchlists."""
    data = run(ctx, lambda c: c.get("/v2/watchlists"))
    if as_json or query:
        return print_json(data, query)
    print_table(
        [
            ("NAME", lambda w: w.get("name", "-")),
            ("ID", lambda w: w.get("id", "")[:8]),
            ("UPDATED", lambda w: ts(w.get("updated_at"))),
        ],
        data,
    )


def _find_watchlist(client, name):
    for w in client.get("/v2/watchlists"):
        if w.get("name", "").lower() == name.lower() or w.get("id", "").startswith(name):
            return w
    raise APIError(404, f"No watchlist named '{name}'.")


@watchlist.command("show")
@click.argument("name")
@output_options
@click.pass_context
def watchlist_show(ctx, name, as_json, query):
    """Show a watchlist's symbols with current prices."""
    def do(c):
        w = c.get(f"/v2/watchlists/{_find_watchlist(c, name)['id']}")
        symbols = [a["symbol"] for a in w.get("assets", [])]
        quotes = {}
        if symbols and not (as_json or query):
            quotes = marketdata_quote(symbols, source="alpaca", client=c)["quotes"]
        return w, quotes
    w, quotes = run(ctx, do)
    if as_json or query:
        return print_json(w, query)
    click.echo(click.style(w.get("name", name), bold=True))
    rows = [
        {"symbol": a["symbol"], "name": a.get("name", "-"),
         "last": price(quotes.get(normalize_symbol(a["symbol"]), {}).get("last"), a["symbol"])}
        for a in w.get("assets", [])
    ]
    print_table(
        [
            ("SYMBOL", lambda r: r["symbol"]),
            ("LAST", lambda r: r["last"]),
            ("NAME", lambda r: r["name"][:50]),
        ],
        rows,
    )


@watchlist.command("create")
@click.argument("name")
@click.argument("symbols", nargs=-1)
@click.pass_context
def watchlist_create(ctx, name, symbols):
    """Create a watchlist: alpaca watchlist create tech AAPL MSFT."""
    run(ctx, lambda c: c.post("/v2/watchlists", json={"name": name, "symbols": [normalize_symbol(s) for s in symbols]}))
    click.echo(f"Created watchlist '{name}' with {len(symbols)} symbol(s).")


@watchlist.command("add")
@click.argument("name")
@click.argument("symbols", nargs=-1, required=True)
@click.pass_context
def watchlist_add(ctx, name, symbols):
    """Add symbols to a watchlist."""
    def do(c):
        normalized = [normalize_symbol(s) for s in symbols]
        wid = _find_watchlist(c, name)["id"]
        for s in normalized:
            c.post(f"/v2/watchlists/{wid}", json={"symbol": s})
    run(ctx, do)
    click.echo(f"Added {', '.join(s.upper() for s in symbols)} to '{name}'.")


@watchlist.command("remove")
@click.argument("name")
@click.argument("symbols", nargs=-1, required=True)
@click.pass_context
def watchlist_remove(ctx, name, symbols):
    """Remove symbols from a watchlist."""
    def do(c):
        paths = [symbol_path(s) for s in symbols]
        wid = _find_watchlist(c, name)["id"]
        for s in paths:
            c.delete(f"/v2/watchlists/{wid}/{s}")
    run(ctx, do)
    click.echo(f"Removed {', '.join(s.upper() for s in symbols)} from '{name}'.")


@watchlist.command("delete")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def watchlist_delete(ctx, name, yes):
    """Delete a watchlist."""
    if not yes:
        click.confirm(f"Delete watchlist '{name}'?", abort=True)
    def do(c):
        c.delete(f"/v2/watchlists/{_find_watchlist(c, name)['id']}")
    run(ctx, do)
    click.echo(f"Deleted watchlist '{name}'.")


if __name__ == "__main__":
    main()
