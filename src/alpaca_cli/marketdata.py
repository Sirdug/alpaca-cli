"""Multi-source market data layer.

Providers, in priority order:

1. Finnhub (free key; real-time last price)
2. Alpaca ``delayed_sip`` (free; full-market consolidated bid/ask, ~15 min delay)
3. Yahoo Finance chart API (free, no key; near-real-time last price)
4. Alpaca ``iex`` (free; real-time but IEX-only, ~2.5% of volume)

``quote()``/``bars()`` pick the best available source automatically (or a
forced one) and report which source each field came from plus staleness, so
callers can tell how fresh the data really is.

Explicit crypto pairs use Alpaca's US crypto feed, independently of stock
providers, including when a quote request mixes stocks and crypto.
"""

import re
import time as _time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from .client import AlpacaClient, APIError
from .config import get_finnhub_key
from .symbols import is_crypto, normalize_symbol

FINNHUB_BASE = "https://finnhub.io/api/v1"
YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

STALE_TOLERANCE = 5 * 60
SOURCE_DELAY = {"finnhub": 0, "yahoo": 0, "delayed_sip": 15 * 60, "sip": 15 * 60, "iex": 0}
CRYPTO_SOURCE = "alpaca_crypto"
CRYPTO_BASE = "/v1beta3/crypto/us"

SOURCES = ["auto", "finnhub", "alpaca", "yahoo", "iex"]

TIMEFRAME_TO_FINNHUB = {
    "1Min": "1", "5Min": "5", "15Min": "15", "30Min": "30",
    "1Hour": "60", "1Day": "D", "1Week": "W", "1Month": "M",
}
TIMEFRAME_TO_YAHOO = {
    "1Min": "1m", "5Min": "5m", "15Min": "15m", "30Min": "30m",
    "1Hour": "60m", "1Day": "1d", "1Week": "1wk", "1Month": "1mo",
}
BAR_SECONDS = {
    "1Min": 60, "5Min": 300, "15Min": 900, "30Min": 1800,
    "1Hour": 3600, "1Day": 86400, "1Week": 604800, "1Month": 2592000,
}

_sessions: Dict[str, requests.Session] = {}
_failure_cache: Dict[str, float] = {}  # source name -> timestamp of last failure
FAILURE_TTL = 120  # seconds


def _failed_recently(source: str) -> bool:
    last = _failure_cache.get(source)
    return bool(last) and _time.time() - last < FAILURE_TTL


def _mark_failed(source: str) -> None:
    _failure_cache[source] = _time.time()


def _session(name: str) -> requests.Session:
    if name not in _sessions:
        s = requests.Session()
        s.headers.update(UA)
        _sessions[name] = s
    return _sessions[name]


def _iso(ts: Any) -> Optional[str]:
    if ts is None or ts == "":
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, OSError):
        return None


def _age_seconds(ts_str: Optional[str]) -> Optional[float]:
    if not ts_str:
        return None
    try:
        return _time.time() - _parse_ts(ts_str)
    except (ValueError, TypeError):
        return None


def _is_stale(ts_str: Optional[str], source: str) -> bool:
    age = _age_seconds(ts_str)
    if age is None:
        return False
    return age > SOURCE_DELAY.get(source, 0) + STALE_TOLERANCE


def _alpaca(client: AlpacaClient) -> AlpacaClient:
    return client


# ---------------------------------------------------------------- quotes


def _finnhub_quote_rows(symbols: List[str]) -> Tuple[Dict[str, dict], str]:
    key = get_finnhub_key()
    if not key:
        raise APIError(401, "No Finnhub API key configured (FINNHUB_API_KEY).")
    rows: Dict[str, dict] = {}
    for sym in symbols:
        try:
            r = _session("finnhub").get(
                f"{FINNHUB_BASE}/quote", params={"symbol": sym, "token": key}, timeout=15
            )
        except requests.RequestException as e:
            raise APIError(0, f"Finnhub unreachable: {e}")
        if r.status_code == 429:
            raise APIError(429, "Finnhub rate limit exceeded")
        if r.status_code >= 400:
            raise APIError(r.status_code, f"Finnhub: {r.text[:200]}")
        d = r.json()
        rows[sym] = {
            "symbol": sym,
            "last": d.get("c"),
            "bid": None,
            "ask": None,
            "bid_size": None,
            "ask_size": None,
            "last_time": _iso(d.get("t")),
            "quote_time": None,
        }
    return rows, "finnhub"


def _yahoo_quote_rows(symbols: List[str]) -> Tuple[Dict[str, dict], str]:
    rows: Dict[str, dict] = {}
    for sym in symbols:
        try:
            r = _session("yahoo").get(
                f"{YAHOO_BASE}/{sym}",
                params={"interval": "1m", "range": "1d", "includePrePost": "true"},
                timeout=15,
            )
        except requests.RequestException as e:
            raise APIError(0, f"Yahoo unreachable: {e}")
        if r.status_code >= 400:
            raise APIError(r.status_code, f"Yahoo: HTTP {r.status_code}")
        d = r.json()
        res = (d.get("chart") or {}).get("result")
        if not res:
            raise APIError(404, f"Yahoo: no data for {sym}")
        meta = res[0].get("meta", {})
        last = meta.get("regularMarketPrice")
        rows[sym] = {
            "symbol": sym,
            "last": last,
            "bid": None,
            "ask": None,
            "bid_size": None,
            "ask_size": None,
            "last_time": _iso(meta.get("regularMarketTime")),
            "quote_time": None,
        }
    return rows, "yahoo"


def _alpaca_quote_rows_impl(symbols: List[str], feed: str, client: AlpacaClient) -> Tuple[Dict[str, dict], str]:
    joined = ",".join(s.upper() for s in symbols)
    q = client.get(
        "/v2/stocks/quotes/latest", data_api=True,
        params={"symbols": joined, "feed": feed},
    ).get("quotes", {})
    t = client.get(
        "/v2/stocks/trades/latest", data_api=True,
        params={"symbols": joined, "feed": feed},
    ).get("trades", {})
    rows: Dict[str, dict] = {}
    for s in symbols:
        s = s.upper()
        qq, tt = q.get(s, {}), t.get(s, {})
        rows[s] = {
            "symbol": s,
            "last": tt.get("p"),
            "bid": qq.get("bp"),
            "ask": qq.get("ap"),
            "bid_size": qq.get("bs"),
            "ask_size": qq.get("as"),
            "last_time": tt.get("t"),
            "quote_time": qq.get("t"),
        }
    return rows, feed


def _crypto_client(client: Optional[AlpacaClient], source: str) -> AlpacaClient:
    if source not in ("auto", "alpaca"):
        raise APIError(400, "Crypto data requires --source auto or --source alpaca.")
    if client is None:
        raise APIError(401, "An Alpaca client is required for crypto data.")
    return client


def _crypto_quote(symbols: List[str], client: AlpacaClient) -> Dict[str, Any]:
    params = {"symbols": ",".join(symbols)}
    quotes = client.get(f"{CRYPTO_BASE}/latest/quotes", data_api=True, params=params).get("quotes") or {}
    trades = client.get(f"{CRYPTO_BASE}/latest/trades", data_api=True, params=params).get("trades") or {}
    rows = {}
    for symbol in symbols:
        q, t = quotes.get(symbol) or {}, trades.get(symbol) or {}
        if not q and not t:
            raise APIError(404, f"No crypto data for {symbol}. Use 'alpaca assets --class crypto' to list pairs.")
        rows[symbol] = {
            "symbol": symbol, "last": t.get("p"), "bid": q.get("bp"), "ask": q.get("ap"),
            "bid_size": q.get("bs"), "ask_size": q.get("as"),
            "last_time": t.get("t"), "quote_time": q.get("t"),
            "last_source": CRYPTO_SOURCE if t else None,
            "quote_source": CRYPTO_SOURCE if q else None,
        }
    return _finalize_quotes(rows, CRYPTO_SOURCE)


def quote(symbols: List[str], source: str = "auto", client: Optional[AlpacaClient] = None) -> Dict[str, Any]:
    """Latest quotes for symbols. Returns {"quotes": {SYM: row}, "source": "..."}."""
    symbols = list(dict.fromkeys(normalize_symbol(s) for s in symbols))
    if not symbols:
        raise APIError(400, "Give at least one symbol.")
    crypto = [s for s in symbols if is_crypto(s)]
    if crypto:
        result = _crypto_quote(crypto, _crypto_client(client, source))
        stocks = [s for s in symbols if not is_crypto(s)]
        if stocks:
            stock_result = quote(stocks, source=source, client=client)
            result["quotes"].update(stock_result["quotes"])
            result["source"] = stock_result["source"] + "+" + CRYPTO_SOURCE
        result["quotes"] = {s: result["quotes"][s] for s in symbols}
        return result
    if source == "auto":
        return _quote_auto(symbols, client)
    if source == "finnhub":
        rows, src = _finnhub_quote_rows(symbols)
    elif source == "yahoo":
        rows, src = _yahoo_quote_rows(symbols)
    elif source == "iex":
        rows, src = _alpaca_quote_rows_impl(symbols, "iex", client)
    elif source == "alpaca":
        try:
            rows, src = _alpaca_quote_rows_impl(symbols, "delayed_sip", client)
        except APIError:
            rows, src = _alpaca_quote_rows_impl(symbols, "iex", client)
    else:
        raise ValueError(f"Unknown source '{source}' (use one of {SOURCES}).")
    for row in rows.values():
        row["last_source"] = src
        row["quote_source"] = src
    return _finalize_quotes(rows, src)


def _quote_auto(symbols: List[str], client: Optional[AlpacaClient]) -> Dict[str, Any]:
    errors: List[str] = []
    last_rows: Dict[str, dict] = {}
    last_src: Optional[str] = None

    if get_finnhub_key() and not _failed_recently("finnhub"):
        try:
            last_rows, last_src = _finnhub_quote_rows(symbols)
        except APIError as e:
            _mark_failed("finnhub")
            errors.append(f"finnhub: {e.message}")
    if not last_rows and not _failed_recently("yahoo"):
        try:
            last_rows, last_src = _yahoo_quote_rows(symbols)
        except APIError as e:
            _mark_failed("yahoo")
            errors.append(f"yahoo: {e.message}")

    bid_rows: Dict[str, dict] = {}
    bid_src: Optional[str] = None
    for feed in ("delayed_sip", "iex"):
        if bid_rows:
            break
        try:
            bid_rows, bid_src = _alpaca_quote_rows_impl(symbols, feed, client)
        except APIError as e:
            _mark_failed(feed)
            errors.append(f"{feed}: {e.message}")

    if not last_rows and not bid_rows:
        raise APIError(0, "All market data sources failed: " + "; ".join(errors))

    merged: Dict[str, dict] = {}
    for s in symbols:
        lr, br = last_rows.get(s, {}), bid_rows.get(s, {})
        merged[s] = {
            "symbol": s,
            "last": lr.get("last") if lr else br.get("last"),
            "bid": br.get("bid"),
            "ask": br.get("ask"),
            "bid_size": br.get("bid_size"),
            "ask_size": br.get("ask_size"),
            "last_time": lr.get("last_time") if lr else br.get("last_time"),
            "quote_time": br.get("quote_time"),
            "last_source": last_src or bid_src,
            "quote_source": bid_src,
        }
    overall = "+".join(x for x in (last_src, bid_src) if x)
    return _finalize_quotes(merged, overall)


def _finalize_quotes(rows: Dict[str, dict], overall: str) -> Dict[str, Any]:
    for row in rows.values():
        row.setdefault("last_source", None)
        row.setdefault("quote_source", None)
        row["stale"] = _is_stale(row.get("last_time"), row["last_source"]) or _is_stale(
            row.get("quote_time"), row["quote_source"]
        )
    return {"quotes": rows, "source": overall}


# ---------------------------------------------------------------- bars


def _crypto_bars(client: AlpacaClient, symbol: str, timeframe: str, limit: int,
                 start: Optional[str], end: Optional[str]) -> List[dict]:
    if timeframe not in BAR_SECONDS:
        raise APIError(400, "Unsupported timeframe. Use " + ", ".join(BAR_SECONDS) + ".")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise APIError(400, "Number of bars must be a positive integer.")
    end_ts = _parse_ts(end) if end else _time.time()
    # Crypto trades every day. Leave room for sparse bars and incomplete periods.
    start_ts = _parse_ts(start) if start else end_ts - BAR_SECONDS[timeframe] * max(limit * 2, 10)
    if start_ts >= end_ts:
        raise APIError(400, "Start must be earlier than end.")
    params = {"symbols": symbol, "timeframe": timeframe, "sort": "desc",
              "start": _iso(start_ts), "end": _iso(end_ts)}
    raw = []
    seen_tokens = set()
    while len(raw) < limit:
        params["limit"] = min(limit - len(raw), 10000)
        data = client.get(f"{CRYPTO_BASE}/bars", data_api=True, params=dict(params))
        raw.extend(((data.get("bars") or {}).get(symbol) or [])[:limit - len(raw)])
        token = data.get("next_page_token")
        if not token:
            break
        if token in seen_tokens:
            raise APIError(502, "Crypto bars returned a repeated page token.")
        seen_tokens.add(token)
        params["page_token"] = token
    return [
        {"time": b.get("t"), "open": b.get("o"), "high": b.get("h"),
         "low": b.get("l"), "close": b.get("c"), "volume": b.get("v")}
        for b in reversed(raw)
    ]


def _parse_ts(s: str) -> float:
    # Python 3.9 needs microsecond precision; keep the timezone when trimming
    # Alpaca's nanosecond timestamps, and pad shorter fractions if necessary.
    s = re.sub(r"\.(\d+)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), s)
    parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _alpaca_bars_impl(client: AlpacaClient, symbol: str, timeframe: str,
                      limit: int, start: Optional[str], end: Optional[str],
                      feed: str) -> List[dict]:
    params: Dict[str, Any] = {"timeframe": timeframe, "limit": limit, "sort": "desc", "feed": feed}
    now = _time.time()
    cutoff = now - 15 * 60
    span = BAR_SECONDS.get(timeframe, 86400) * max(limit, 1) * 2
    min_window = {"1Min": 7 * 86400, "5Min": 7 * 86400, "15Min": 7 * 86400,
                  "30Min": 7 * 86400, "1Hour": 7 * 86400,
                  "1Day": 365 * 86400, "1Week": 2 * 365 * 86400,
                  "1Month": 5 * 365 * 86400}.get(timeframe, 7 * 86400)
    window = max(span, min_window)
    if feed == "sip":
        end_ts = min(_parse_ts(end), cutoff) if end else cutoff
        start_ts = _parse_ts(start) if start and _parse_ts(start) < end_ts else end_ts - window
    else:
        end_ts = _parse_ts(end) if end else now
        start_ts = _parse_ts(start) if start else end_ts - window
    params["start"] = _iso(start_ts)
    params["end"] = _iso(end_ts)
    data = client.get(f"/v2/stocks/{symbol}/bars", data_api=True, params=params)
    bars = data.get("bars") or []
    return [
        {"time": b.get("t"), "open": b.get("o"), "high": b.get("h"),
         "low": b.get("l"), "close": b.get("c"), "volume": b.get("v")}
        for b in reversed(bars)
    ][-limit:]


def _finnhub_bars_impl(symbol: str, timeframe: str, limit: int,
                       start: Optional[str], end: Optional[str]) -> List[dict]:
    key = get_finnhub_key()
    if not key:
        raise APIError(401, "No Finnhub API key configured (FINNHUB_API_KEY).")
    resolution = TIMEFRAME_TO_FINNHUB.get(timeframe)
    if not resolution:
        raise APIError(400, f"Finnhub has no '{timeframe}' bars.")
    span = BAR_SECONDS.get(timeframe, 86400) * limit
    now = _time.time()
    to = _parse_ts(end) if end else now
    fro = _parse_ts(start) if start else to - span
    try:
        r = _session("finnhub").get(
            f"{FINNHUB_BASE}/stock/candle",
            params={"symbol": symbol, "resolution": resolution, "from": fro, "to": to,
                    "token": key},
            timeout=15,
        )
    except requests.RequestException as e:
        raise APIError(0, f"Finnhub unreachable: {e}")
    if r.status_code == 429:
        raise APIError(429, "Finnhub rate limit exceeded")
    if r.status_code >= 400:
        raise APIError(r.status_code, f"Finnhub: {r.text[:200]}")
    d = r.json()
    if d.get("s") != "ok":
        return []
    rows = [
        {"time": _iso(t), "open": o, "high": h, "low": l, "close": c, "volume": v}
        for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])
    ]
    return rows[-limit:]


def _yahoo_bars_impl(symbol: str, timeframe: str, limit: int) -> List[dict]:
    interval = TIMEFRAME_TO_YAHOO.get(timeframe)
    if not interval:
        raise APIError(400, f"Yahoo has no '{timeframe}' bars.")
    seconds = BAR_SECONDS.get(timeframe, 86400)
    need_days = max(int(limit * seconds * 2 / 86400) + 1, 1)
    caps = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "60m": 730}
    cap = caps.get(interval, 730)
    range_ = f"{min(need_days, cap)}d"
    try:
        r = _session("yahoo").get(
            f"{YAHOO_BASE}/{symbol}",
            params={"interval": interval, "range": range_, "includePrePost": "true"},
            timeout=15,
        )
    except requests.RequestException as e:
        raise APIError(0, f"Yahoo unreachable: {e}")
    if r.status_code >= 400:
        raise APIError(r.status_code, f"Yahoo: HTTP {r.status_code}")
    d = r.json()
    res = (d.get("chart") or {}).get("result")
    if not res:
        raise APIError(404, f"Yahoo: no data for {symbol}")
    ts = res[0].get("timestamp") or []
    q = ((res[0].get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    for i, t in enumerate(ts):
        close = (q.get("close") or [None] * len(ts))[i]
        if close is None:
            continue
        rows.append({
            "time": _iso(t),
            "open": (q.get("open") or [None] * len(ts))[i],
            "high": (q.get("high") or [None] * len(ts))[i],
            "low": (q.get("low") or [None] * len(ts))[i],
            "close": close,
            "volume": (q.get("volume") or [None] * len(ts))[i],
        })
    return rows[-limit:]


def bars(symbol: str, timeframe: str = "1Day", limit: int = 10,
         start: Optional[str] = None, end: Optional[str] = None,
         source: str = "auto", client: Optional[AlpacaClient] = None) -> Dict[str, Any]:
    """Historical OHLCV bars, oldest first. Returns {"bars": [...], "source": "..."}."""
    symbol = normalize_symbol(symbol)
    if is_crypto(symbol):
        return {"bars": _crypto_bars(_crypto_client(client, source), symbol, timeframe, limit, start, end),
                "source": CRYPTO_SOURCE}
    errors: List[str] = []
    if source == "auto":
        if get_finnhub_key() and not _failed_recently("finnhub"):
            try:
                return {"bars": _finnhub_bars_impl(symbol, timeframe, limit, start, end),
                        "source": "finnhub"}
            except APIError as e:
                _mark_failed("finnhub")
                errors.append(f"finnhub: {e.message}")
        try:
            return {"bars": _alpaca_bars_impl(client, symbol, timeframe, limit, start, end, "sip"),
                    "source": "delayed_sip"}
        except APIError as e:
            _mark_failed("delayed_sip")
            errors.append(f"delayed_sip: {e.message}")
        if not _failed_recently("yahoo"):
            try:
                return {"bars": _yahoo_bars_impl(symbol, timeframe, limit), "source": "yahoo"}
            except APIError as e:
                _mark_failed("yahoo")
                errors.append(f"yahoo: {e.message}")
        try:
            return {"bars": _alpaca_bars_impl(client, symbol, timeframe, limit, start, end, "iex"),
                    "source": "iex"}
        except APIError as e:
            _mark_failed("iex")
            errors.append(f"iex: {e.message}")
        raise APIError(0, "All market data sources failed: " + "; ".join(errors))

    if source == "finnhub":
        return {"bars": _finnhub_bars_impl(symbol, timeframe, limit, start, end), "source": "finnhub"}
    if source == "yahoo":
        return {"bars": _yahoo_bars_impl(symbol, timeframe, limit), "source": "yahoo"}
    if source == "alpaca":
        try:
            return {"bars": _alpaca_bars_impl(client, symbol, timeframe, limit, start, end, "sip"),
                    "source": "delayed_sip"}
        except APIError:
            return {"bars": _alpaca_bars_impl(client, symbol, timeframe, limit, start, end, "iex"),
                    "source": "iex"}
    if source == "iex":
        return {"bars": _alpaca_bars_impl(client, symbol, timeframe, limit, start, end, "iex"),
                "source": "iex"}
    raise ValueError(f"Unknown source '{source}' (use one of {SOURCES}).")


# ---------------------------------------------------------------- health


def available_sources(client: Optional[AlpacaClient] = None) -> Dict[str, Any]:
    """Probe each data source and report what's reachable."""
    out: Dict[str, Any] = {}

    try:
        _crypto_quote(["BTC/USD"], _crypto_client(client, "auto"))
        out[CRYPTO_SOURCE] = {"available": True, "note": "24/7 crypto quotes and trades (US)"}
    except APIError as e:
        out[CRYPTO_SOURCE] = {"available": False, "note": e.message}

    key = get_finnhub_key()
    if not key:
        out["finnhub"] = {"available": False, "note": "no API key (set FINNHUB_API_KEY)"}
    else:
        try:
            _finnhub_quote_rows(["AAPL"])
            out["finnhub"] = {"available": True, "note": "real-time last price"}
        except APIError as e:
            out["finnhub"] = {"available": False, "note": e.message}

    for feed, label in (("delayed_sip", "full market, ~15 min delay"), ("iex", "IEX only")):
        try:
            _alpaca_quote_rows_impl(["AAPL"], feed, client)
            out[feed] = {"available": True, "note": label}
        except APIError as e:
            out[feed] = {"available": False, "note": e.message}

    try:
        _yahoo_quote_rows(["AAPL"])
        out["yahoo"] = {"available": True, "note": "near-real-time price"}
    except APIError as e:
        out["yahoo"] = {"available": False, "note": e.message}

    return out
