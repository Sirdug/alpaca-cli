# Alpaca CLI (unofficial)

A command-line interface for the [Alpaca](https://alpaca.markets/) Trading and
Market Data APIs, built for macOS. Trade stocks and spot crypto, manage positions and orders,
and pull market data from your terminal.

> This is an independent Python implementation inspired by
> [alpacahq/cli](https://github.com/alpacahq/cli). It talks directly to the
> public [Alpaca API](https://docs.alpaca.markets/) using your own API keys.
> **Paper trading is the default**; live trading requires an explicit opt-in
> during `alpaca setup` (or `ALPACA_LIVE_TRADE=true` with env keys).

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Then either activate the venv (`source .venv/bin/activate`) or symlink the
command somewhere on your PATH:

```bash
ln -sf "$PWD/.venv/bin/alpaca" /usr/local/bin/alpaca
```

## Get started

```bash
alpaca setup     # prompts for your API keys (get them at app.alpaca.markets)
alpaca doctor    # checks config + connectivity
alpaca account   # balances and buying power
```

Keys are stored in `~/.config/alpaca-cli/config.json` (owner-read-only).
Environment variables `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` override the
config file.

## Everyday commands

```bash
alpaca quote AAPL MSFT             # latest price, bid/ask
alpaca bars AAPL -t 1Day           # historical OHLCV bars
alpaca news -s AAPL                # headlines

alpaca buy AAPL 5                  # market buy (asks for confirmation)
alpaca buy AAPL --notional 100     # buy $100 worth (fractional)
alpaca buy AAPL 5 -l 180           # limit order at $180
alpaca sell AAPL 5 --dry-run       # preview without submitting
alpaca buy AAPL 1 -y               # skip confirmation (for scripts)

alpaca positions                   # open positions with colored P/L
alpaca close AAPL                  # close a position
alpaca close --all

alpaca order list                  # open orders
alpaca order cancel 1a2b3c         # short id prefix is fine
alpaca order cancel-all

alpaca watchlist create tech AAPL MSFT NVDA
alpaca watchlist show tech         # symbols + live prices
alpaca clock                       # is the market open?
alpaca calendar
```

## Crypto

Use explicit pairs such as `BTC/USD` and `ETH/USD` in the same commands as stocks.
Lowercase and `BTC-USD` also work. Use the slash form instead of compact `BTCUSD`
or bare coin names so the CLI can distinguish crypto from stock tickers.

```bash
alpaca assets --class crypto                  # available pairs and trading increments
alpaca asset BTC/USD                          # minimum order size and pair details
alpaca quote BTC/USD ETH/USD                  # latest trade, bid, ask, and timestamps
alpaca quote AAPL BTC/USD                     # stocks and crypto together
alpaca bars BTC/USD -t 1Hour --limit 24        # recent hourly prices
alpaca bars ETH/USD --start 2026-08-01 --end 2026-09-01 --limit 31

alpaca buy BTC/USD --notional 25 --dry-run    # preview a $25 market buy
alpaca buy BTC/USD --notional 25             # asks before submitting
alpaca buy ETH/USD 0.01 --limit 2000          # quantity-based limit order
alpaca sell BTC/USD 0.001 --tif ioc           # immediate-or-cancel order
alpaca sell ETH/USD 0.01 --stop 1800 --limit 1790
alpaca close BTC/USD                         # asks before closing the position
alpaca positions                             # includes crypto holdings
```

Crypto orders default to `gtc`; stock orders still default to `day`. Crypto
supports market, limit, and stop-limit orders, with `gtc` or `ioc`. A crypto
`--stop` requires `--limit`, and `--extended` is rejected because crypto trades
24/7. Supply either quantity or notional, not both. Invalid or nonpositive amounts
are rejected before submission. Alpaca enforces account eligibility, available
balance, minimum order sizes, and trading increments. Check `alpaca asset PAIR`
for the current increments. See [Alpaca's crypto trading documentation](https://docs.alpaca.markets/us/docs/crypto-trading).

Crypto quotes and bars use Alpaca's US crypto feed with `--source auto` or
`--source alpaca`; stock-only sources (`iex`, `finnhub`, `yahoo`) are rejected for
crypto. Bars are returned oldest first and follow pagination to collect up to the
requested limit. Dates without an explicit timezone use UTC. Small coin quantities
and prices retain their decimal precision; prices for non-USD pairs show the quote
currency. JSON and JMESPath output work as usual, including order previews:

```bash
alpaca buy BTC/USD --notional 25 --dry-run --json
alpaca assets --class crypto -q '[?tradable].symbol'
```

Watchlist creation, updates, removal, and displayed prices also support crypto
pairs. `alpaca clock` and `alpaca calendar` describe stock-market hours.

The companion `alpaca-mcp` server exposes the same crypto behavior through its
existing `buy`, `sell`, `quote`, `bars`, `asset`, and `close_position` tools, plus
`assets(asset_class="crypto")` for pair discovery. Trading tools still require
`confirm=True`. Restart an already-running MCP server to load the update.

## Differences from the official CLI

- **Safer by default**: paper mode unless you opt in to live; order commands
  confirm before submitting (`-y` skips, `--dry-run` previews). Live-account
  orders show a red `[LIVE ACCOUNT — REAL MONEY]` banner.
- **Simpler ergonomics**: top-level `buy` / `sell` / `positions` / `quote`
  instead of nested subcommands; short order-id prefixes accepted; watchlists
  addressable by name.
- **Readable output**: aligned tables, `$` formatting, green/red P/L.
  Every read command supports `--json` and a JMESPath `--query`/`-q` filter
  for scripting, e.g. `alpaca positions -q '[].symbol'`.

Not (yet) covered: options, crypto transfers, and streaming data.

## Scripting

```bash
alpaca positions --json | jq .
alpaca account -q buying_power
alpaca order list --status all --limit 100 --json
```

## Tests

Run `python -m unittest discover -s tests -v` in the CLI environment. Install the
`mcp` extra (`pip install -e '.[mcp]'`) to include the MCP integration tests. The
suite blocks network requests and uses mock clients; it never places real or paper orders.
