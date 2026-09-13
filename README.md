# Alpaca CLI (unofficial)

A command-line interface for the [Alpaca](https://alpaca.markets/) Trading and
Market Data APIs for Linux, macOS, and Windows 11. Trade stocks and spot crypto, manage positions and orders,
and pull market data from your terminal.

> This is an independent Python implementation inspired by
> [alpacahq/cli](https://github.com/alpacahq/cli). It talks directly to the
> public [Alpaca API](https://docs.alpaca.markets/) using your own API keys.
> **Paper trading is the default**; live trading requires an explicit opt-in
> during `alpaca setup` (or `ALPACA_LIVE_TRADE=true` with env keys).

## Install

### Quick install: macOS and Ubuntu

With Git and Python 3.9+ installed, run:

```bash
git clone https://github.com/Sirdug/alpaca-cli.git
cd alpaca-cli
bash install.sh
export PATH="$HOME/.local/bin:$PATH"
alpaca setup
```

If you already have the repository, run `bash install.sh` from that checkout.
The installer creates a private environment in `~/.local/share/alpaca-cli`
and links `alpaca` into `~/.local/bin`. It does not require sudo or alter your
shell startup files. Add the `export PATH` line to your shell profile to keep
the command available in new terminals.

For the MCP server too, use Python 3.12+ and run `bash install.sh --mcp`.
The MCP client's stdio command is the absolute path to
`~/.local/bin/alpaca-mcp`. Use `--python python3.12` to select a specific Python.
On Ubuntu, install `python3` and `python3-venv` if needed; on macOS, Python can
be installed with `brew install python` if you use Homebrew.

Run `git pull` and rerun the installer with the same options to update. Existing
credentials and profiles are preserved. Custom locations are supported via
`--install-dir "/path/to/environment"` and `--bin-dir "/path/to/bin"`;
unrelated existing environments and commands are not overwritten.

### Quick install: Windows 11 (PowerShell)

With Python 3.9+ installed, download and run the installer:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/Sirdug/alpaca-cli/main/install.ps1" -OutFile install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
& "$env:LOCALAPPDATA\alpaca-cli\Scripts\alpaca.exe" setup
```

The installer installs the CLI directly from `Sirdug/alpaca-cli` on GitHub.
It uses Git's credential manager when Git is installed; otherwise it downloads
a public source archive. Private repositories require Git signed in with access
to the repository. The raw download command above only works for a public
repository; for a private repository, obtain `install.ps1` from your authenticated
checkout or GitHub session and run it with the second command. A standalone copy
of the script is sufficient. The
execution-policy override applies only to this PowerShell process. The script
works in Windows PowerShell 5.1 and PowerShell 7 without administrator access.
It creates a private environment in `%LOCALAPPDATA%\alpaca-cli` and prints the
command to add its `Scripts` directory to your current session's PATH.

Add `-Mcp` to install the MCP server (requires Python 3.12+). Its stdio command
is the absolute path to `%LOCALAPPDATA%\alpaca-cli\Scripts\alpaca-mcp.exe`.
Use `-Python "C:\path\to\python.exe"` to choose Python and
`-InstallDir "C:\path\to\environment"` to choose the installation directory.
The installer automatically tries `py`, then `python`, then `python3`.
Rerun with the same options to download and install updates. Use `-Ref main`
to select a branch, tag, or commit (default: `main`). Developers can use
`-SourceDir "C:\path\to\alpaca-cli"` to install a local checkout instead.
Existing profiles are preserved, and unrelated environments are not overwritten.

### Manual installation

Run these commands from the repository folder. Use Python 3.12 or newer for
the CLI and optional MCP server (the core CLI also supports Python 3.9+).

### Linux and macOS (bash/zsh)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Activate the environment in each new terminal, or run `.venv/bin/alpaca`
directly. On Linux, install your distribution's Python venv package if
`python3 -m venv` reports that venv or ensurepip is missing. Install the CLI
inside the virtual environment, including on systems with externally managed
Python installations.

You can also symlink the command into a user-owned directory on your PATH:

```bash
mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/.venv/bin/alpaca" "$HOME/.local/bin/alpaca"
export PATH="$HOME/.local/bin:$PATH"
```

### Windows 11 (PowerShell)

Install Python if needed, then open PowerShell in the repository folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\alpaca.exe setup
.\.venv\Scripts\alpaca.exe doctor
```

If your Python installation provides `python` instead of `py`, use
`python -m venv .venv` for the first command. These commands work without
activating the environment or changing PowerShell's execution policy.

To use the short `alpaca` command for the rest of the current PowerShell session:

```powershell
$env:Path = "$PWD\.venv\Scripts;$env:Path"
alpaca --help
```

All commands below use the same arguments on Linux, macOS, and Windows. You can
also run `python -m alpaca_cli` using the environment's Python on any platform.

### Optional MCP server

Using the environment's Python, install the extra with
`python -m pip install -e ".[mcp]"`. Set your MCP client's stdio command to the
absolute path of `.venv/bin/alpaca-mcp` on Linux/macOS or
`.venv\Scripts\alpaca-mcp.exe` on Windows. No shell wrapper is needed. The
server reads the same saved profiles and environment variables as the CLI.

## Get started

```bash
alpaca setup     # prompts for your API keys (get them at app.alpaca.markets)
alpaca doctor    # checks config + connectivity
alpaca account   # balances and buying power
```

Keys are stored in `~/.config/alpaca-cli/config.json` on Linux/macOS and
`%USERPROFILE%\.config\alpaca-cli\config.json` on Windows. Existing profiles
remain at the same location. Set `ALPACA_CONFIG_DIR` to override the directory
on any platform. Files use UTF-8, including profiles with non-ASCII names.
On Linux/macOS the file has owner-only read/write permissions (`0600`); on Windows
access follows the directory's inherited NTFS permissions. Keys are stored as
plain text, so use a private directory when overriding the location.
Environment variables `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` override the
config file.

To set environment credentials for the current terminal session:

```bash
# Linux / macOS
export ALPACA_API_KEY="your-key"
export ALPACA_SECRET_KEY="your-secret"
```

```powershell
# Windows PowerShell
$env:ALPACA_API_KEY = "your-key"
$env:ALPACA_SECRET_KEY = "your-secret"
```

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
GitHub Actions runs the suite on Linux (Ubuntu), Windows, and macOS, including MCP tests on
Python 3.12 and core CLI tests on Python 3.9.
