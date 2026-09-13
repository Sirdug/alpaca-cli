"""Offline regression tests. No test may contact a brokerage or submit a real order."""

import json
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner

from alpaca_cli import cli, marketdata
from alpaca_cli.client import APIError
from alpaca_cli.config import Credentials
from alpaca_cli.output import num, price
from alpaca_cli.symbols import normalize_symbol, symbol_path
from alpaca_cli.trading import build_order

try:
    from alpaca_cli import mcp_server
except ModuleNotFoundError as exc:
    if not (exc.name or "").startswith("mcp"):
        raise
    mcp_server = None


class OfflineTest(unittest.TestCase):
    def setUp(self):
        guard = patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden in tests"))
        guard.start()
        self.addCleanup(guard.stop)
        self.client = Mock()


class OrderTests(OfflineTest):
    def test_crypto_defaults_and_exact_decimal_payload(self):
        order = build_order("buy", "btc/usd", qty="0.000012504")
        self.assertEqual(order, {"symbol": "BTC/USD", "side": "buy", "time_in_force": "gtc",
                                 "qty": "0.000012504", "type": "market"})

    def test_crypto_notional_and_order_types(self):
        order = build_order("buy", "ETH/USD", notional="25.25")
        self.assertEqual(order["notional"], "25.25")
        self.assertNotIn("qty", order)
        for side in ("buy", "sell"):
            for tif in ("gtc", "ioc"):
                for kwargs, expected in (({}, "market"), ({"limit": "2500.12"}, "limit"),
                                         ({"limit": "2500.12", "stop": "2490.12"}, "stop_limit")):
                    with self.subTest(side=side, tif=tif, order_type=expected):
                        order = build_order(side, "ETH/USD", qty="0.01", tif=tif, **kwargs)
                        self.assertEqual(order["type"], expected)
                        self.assertEqual(order["time_in_force"], tif)

    def test_crypto_rejects_unsupported_settings(self):
        for kwargs in ({"tif": "day"}, {"tif": "fok"}, {"tif": "opg"}, {"tif": "cls"},
                       {"stop": "2000"}, {"extended": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_order("buy", "BTC/USD", qty=1, **kwargs)

    def test_stock_defaults_and_stop_order_preserved(self):
        self.assertEqual(build_order("buy", "aapl", qty=2)["time_in_force"], "day")
        order = build_order("sell", "AAPL", qty=2, stop=100, tif="gtc", extended=True)
        self.assertEqual(order["type"], "stop")
        self.assertEqual(order["time_in_force"], "gtc")
        self.assertTrue(order["extended_hours"])

    def test_rejects_missing_or_conflicting_amounts(self):
        for kwargs in ({}, {"qty": 1, "notional": 100}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_order("buy", "BTC/USD", **kwargs)

    def test_rejects_invalid_numbers(self):
        for value in (0, -1, "nan", "inf", "-Infinity", "oops"):
            for field in ("qty", "notional", "limit", "stop"):
                kwargs = {field: value}
                if field in ("limit", "stop"):
                    kwargs["qty"] = 1
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    build_order("buy", "AAPL", **kwargs)

    def test_symbol_aliases_and_path_encoding(self):
        self.assertEqual(normalize_symbol(" eth-usd "), "ETH/USD")
        self.assertEqual(symbol_path("BTC/USD"), "BTC%2FUSD")
        self.assertEqual(normalize_symbol("BRK-B"), "BRK-B")
        for symbol in ("", "BTC/", "/USD", "BTC/USD/ETH", "BTC /USD"):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                normalize_symbol(symbol)

    def test_display_keeps_small_quantities_and_prices(self):
        self.assertEqual(num("0.000000001"), "0.000000001")
        self.assertEqual(price("0.000012345", "SHIB/USD"), "$0.000012345")
        self.assertEqual(price("0.03123456", "ETH/BTC"), "0.03123456 BTC")
        self.assertEqual(price("125.123", "AAPL"), "$125.12")


class MarketDataTests(OfflineTest):
    def crypto_responses(self):
        return [{"quotes": {"BTC/USD": {"bp": 100, "ap": 101, "bs": 0.01, "as": 0.02,
                                         "t": "2026-09-07T00:00:00.123456789Z"}}},
                {"trades": {"BTC/USD": {"p": 100.5, "t": "2026-09-07T00:00:00.123456789Z"}}}]

    def test_crypto_quotes_use_crypto_endpoints_and_schema(self):
        self.client.get.side_effect = self.crypto_responses()
        result = marketdata.quote(["btc-usd"], client=self.client)
        row = result["quotes"]["BTC/USD"]
        self.assertEqual(row["last"], 100.5)
        self.assertEqual(row["bid"], 100)
        self.assertEqual(row["ask"], 101)
        self.assertEqual(row["last_source"], "alpaca_crypto")
        self.assertEqual(row["quote_source"], "alpaca_crypto")
        self.assertEqual([c.args[0] for c in self.client.get.call_args_list],
                         ["/v1beta3/crypto/us/latest/quotes", "/v1beta3/crypto/us/latest/trades"])
        for call in self.client.get.call_args_list:
            self.assertTrue(call.kwargs["data_api"])
            self.assertEqual(call.kwargs["params"], {"symbols": "BTC/USD"})

    def test_mixed_quotes_separate_routes_and_preserve_input_order(self):
        self.client.get.side_effect = self.crypto_responses()
        stocks = {"quotes": {"AAPL": {"symbol": "AAPL", "last": 200}}, "source": "iex"}
        with patch.object(marketdata, "_quote_auto", return_value=stocks) as stock_quote:
            result = marketdata.quote(["aapl", "BTC/USD", "AAPL"], client=self.client)
        stock_quote.assert_called_once_with(["AAPL"], self.client)
        self.assertEqual(list(result["quotes"]), ["AAPL", "BTC/USD"])
        self.assertEqual(result["quotes"]["BTC/USD"]["last"], 100.5)
        self.assertEqual(result["source"], "iex+alpaca_crypto")

    def test_explicit_stock_feed_is_unchanged(self):
        self.client.get.side_effect = [{"quotes": {"AAPL": {"bp": 200}}}, {"trades": {"AAPL": {"p": 201}}}]
        result = marketdata.quote(["aapl"], source="iex", client=self.client)
        self.assertEqual(result["quotes"]["AAPL"]["last"], 201)
        self.assertEqual(result["source"], "iex")
        self.assertEqual(self.client.get.call_args_list[0].args[0], "/v2/stocks/quotes/latest")

    def test_crypto_rejects_stock_only_sources_before_fetching(self):
        for source in ("yahoo", "finnhub", "iex"):
            for fn, args in ((marketdata.quote, (["BTC/USD"],)), (marketdata.bars, ("BTC/USD",))):
                with self.subTest(source=source, fn=fn.__name__), self.assertRaisesRegex(APIError, "source"):
                    fn(*args, source=source, client=self.client)
        self.client.get.assert_not_called()

    def test_crypto_missing_client_and_unknown_pair(self):
        with self.assertRaisesRegex(APIError, "client"):
            marketdata.quote(["BTC/USD"])
        self.client.get.side_effect = [{"quotes": {}}, {"trades": {}}]
        with self.assertRaisesRegex(APIError, "No crypto data"):
            marketdata.quote(["NOCOIN/USD"], client=self.client)

    def test_crypto_error_does_not_fall_back_to_stock_data(self):
        self.client.get.side_effect = APIError(403, "Forbidden")
        with patch.object(marketdata, "_quote_auto") as fallback:
            with self.assertRaises(APIError):
                marketdata.quote(["BTC/USD"], client=self.client)
        fallback.assert_not_called()

    def test_nanosecond_timestamp_age_preserves_timezone(self):
        with patch.object(marketdata._time, "time", return_value=1788739201):
            age = marketdata._age_seconds("2026-09-07T00:00:00.123456789Z")
        self.assertAlmostEqual(age, 0.876544, places=5)

    def test_bars_follow_pagination_and_return_oldest_first(self):
        self.client.get.side_effect = [
            {"bars": {"BTC/USD": [{"t": "2026-09-06T02:00:00Z", "c": 102}]}, "next_page_token": "page2"},
            {"bars": {"BTC/USD": [{"t": "2026-09-06T01:00:00Z", "c": 101}]}, "next_page_token": "page3"},
        ]
        result = marketdata.bars("btc/usd", timeframe="1Hour", limit=2,
                                 start="2026-09-06", end="2026-09-07", client=self.client)
        self.assertEqual([b["close"] for b in result["bars"]], [101, 102])
        calls = self.client.get.call_args_list
        self.assertEqual(calls[0].args[0], "/v1beta3/crypto/us/bars")
        self.assertEqual(calls[0].kwargs["params"], {"symbols": "BTC/USD", "timeframe": "1Hour",
                         "sort": "desc", "start": "2026-09-06T00:00:00Z", "end": "2026-09-07T00:00:00Z", "limit": 2})
        self.assertEqual(calls[1].kwargs["params"]["page_token"], "page2")
        self.assertEqual(calls[1].kwargs["params"]["limit"], 1)
        self.assertEqual(result["source"], "alpaca_crypto")

    def test_bars_respect_page_size_cap_and_empty_result(self):
        self.client.get.return_value = {"bars": None, "next_page_token": None}
        result = marketdata.bars("BTC/USD", limit=10001, client=self.client)
        self.assertEqual(result["bars"], [])
        self.assertEqual(self.client.get.call_args.kwargs["params"]["limit"], 10000)

    def test_bars_guard_against_repeated_page_tokens(self):
        self.client.get.return_value = {"bars": {}, "next_page_token": "same"}
        with self.assertRaisesRegex(APIError, "repeated page token"):
            marketdata.bars("BTC/USD", client=self.client)
        self.assertEqual(self.client.get.call_count, 2)

    def test_bars_validate_timeframe_limit_and_dates(self):
        for kwargs in ({"timeframe": "nonsense"}, {"limit": 0}, {"limit": -1},
                       {"start": "2026-09-07", "end": "2026-09-06"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(APIError):
                marketdata.bars("BTC/USD", client=self.client, **kwargs)
        self.client.get.assert_not_called()


class CLITests(OfflineTest):
    def setUp(self):
        super().setUp()
        self.runner = CliRunner()
        for patcher in (patch.object(cli, "resolve_credentials", return_value=Credentials("test", "test", True, "test")),
                        patch.object(cli, "AlpacaClient", return_value=self.client)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def invoke(self, args, **kwargs):
        result = self.runner.invoke(cli.main, args, **kwargs)
        self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
        return result

    def test_dry_run_previews_actual_crypto_order_without_submitting(self):
        result = self.invoke(["buy", "BTC/USD", "--notional", "25", "--dry-run", "--json"])
        data = json.loads(result.output)
        self.assertTrue(data["dry_run"])
        self.assertTrue(data["paper"])
        self.assertEqual(data["order"]["time_in_force"], "gtc")
        self.assertEqual(data["order"]["notional"], "25")
        self.client.post.assert_not_called()
        self.client.get.assert_not_called()

    def test_human_preview_keeps_small_coin_quantity(self):
        result = self.invoke(["sell", "BTC/USD", "0.000000001", "--dry-run"])
        self.assertIn("0.000000001 BTC", result.output)
        self.assertIn("gtc", result.output)
        self.assertNotIn("share(s)", result.output)

    def test_confirmation_declined_submits_nothing(self):
        result = self.runner.invoke(cli.main, ["buy", "BTC/USD", "--notional", "25"], input="n\n")
        self.assertNotEqual(result.exit_code, 0)
        self.client.post.assert_not_called()

    def test_confirmed_crypto_submission_payload_with_mock_client(self):
        self.client.post.return_value = {"id": "test-order", "status": "accepted"}
        self.invoke(["buy", "btc-usd", "0.000012504", "-y"])
        self.client.post.assert_called_once_with("/v2/orders", json={"symbol": "BTC/USD", "side": "buy",
                "time_in_force": "gtc", "qty": "0.000012504", "type": "market"})

    def test_invalid_crypto_orders_never_submit(self):
        for args in (["--tif", "day"], ["--stop", "70000"], ["--extended"]):
            with self.subTest(args=args):
                result = self.runner.invoke(cli.main, ["buy", "BTC/USD", "1", "-y"] + args)
                self.assertNotEqual(result.exit_code, 0)
        self.client.post.assert_not_called()

    def test_stock_preview_keeps_day_default(self):
        data = json.loads(self.invoke(["buy", "AAPL", "1", "--dry-run", "--json"]).output)
        self.assertEqual(data["order"]["time_in_force"], "day")

    def test_asset_lookup_and_discovery(self):
        self.client.get.return_value = {"symbol": "BTC/USD"}
        self.invoke(["asset", "btc-usd", "--json"])
        self.client.get.assert_called_with("/v2/assets/BTC%2FUSD")
        self.client.get.return_value = [{"symbol": "BTC/USD", "class": "crypto"}]
        result = self.invoke(["assets", "--class", "crypto", "-q", "[].symbol"])
        self.assertEqual(json.loads(result.output), ["BTC/USD"])
        self.client.get.assert_called_with("/v2/assets", params={"status": "active", "asset_class": "crypto"})

    def test_close_crypto_uses_encoded_symbol_and_exact_quantity(self):
        self.client.delete.return_value = {"id": "test-close"}
        self.invoke(["close", "BTC/USD", "--qty", "0.000000001", "-y"])
        self.client.delete.assert_called_once_with("/v2/positions/BTC%2FUSD", params={"qty": "0.000000001"})

    def test_watchlist_remove_encodes_pair(self):
        self.client.get.return_value = [{"id": "watch1", "name": "coins"}]
        self.invoke(["watchlist", "remove", "coins", "btc-usd"])
        self.client.delete.assert_called_once_with("/v2/watchlists/watch1/BTC%2FUSD")

    def test_watchlist_display_routes_mixed_symbols(self):
        self.client.get.side_effect = [[{"id": "w1", "name": "mixed"}],
                {"name": "mixed", "assets": [{"symbol": "AAPL"}, {"symbol": "BTC/USD"}]}]
        with patch.object(cli, "marketdata_quote", return_value={"quotes": {
                "AAPL": {"last": 200}, "BTC/USD": {"last": 80000}}}) as quotes:
            result = self.invoke(["watchlist", "show", "mixed"])
        quotes.assert_called_once_with(["AAPL", "BTC/USD"], source="alpaca", client=self.client)
        self.assertIn("$80,000", result.output)

    def test_bad_crypto_bars_source_reports_friendly_error(self):
        result = self.runner.invoke(cli.main, ["bars", "BTC/USD", "--source", "iex"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Crypto data requires", result.output)
        self.client.get.assert_not_called()

    def test_order_list_keeps_small_crypto_limit_prices(self):
        self.client.get.return_value = [{"symbol": "SHIB/USD", "qty": "10", "type": "limit",
                                         "limit_price": "0.000012345"}]
        result = self.invoke(["order", "list"])
        self.assertIn("$0.000012345", result.output)


@unittest.skipIf(mcp_server is None, "Install the mcp extra to test MCP integration")
class MCPTests(OfflineTest):
    def setUp(self):
        super().setUp()
        patcher = patch.object(mcp_server, "_client", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_mcp_confirmation_guard(self):
        for fn in (mcp_server.buy, mcp_server.sell):
            with self.subTest(fn=fn.__name__), self.assertRaisesRegex(ValueError, "confirm=True"):
                fn("BTC/USD", notional=25)
        self.client.post.assert_not_called()

    def test_mcp_crypto_and_stock_defaults(self):
        mcp_server.buy("BTC/USD", notional=25, confirm=True)
        self.assertEqual(self.client.post.call_args.kwargs["json"]["time_in_force"], "gtc")
        mcp_server.buy("AAPL", qty=1, confirm=True)
        self.assertEqual(self.client.post.call_args.kwargs["json"]["time_in_force"], "day")

    def test_mcp_crypto_validation_before_submission(self):
        with self.assertRaisesRegex(ValueError, "gtc or"):
            mcp_server.sell("BTC/USD", qty=1, tif="day", confirm=True)
        self.client.post.assert_not_called()

    def test_mcp_asset_and_close_paths(self):
        mcp_server.asset("btc-usd")
        self.client.get.assert_called_once_with("/v2/assets/BTC%2FUSD")
        self.client.delete.return_value = {"id": "test-close"}
        mcp_server.close_position("BTC/USD", qty=0.001, confirm=True)
        self.client.delete.assert_called_once_with("/v2/positions/BTC%2FUSD", params={"qty": "0.001"})

    def test_mcp_asset_discovery(self):
        self.client.get.return_value = [{"symbol": "BTC/USD"}]
        result = mcp_server.assets(asset_class="crypto")
        self.assertEqual(result["assets"], [{"symbol": "BTC/USD"}])
        self.client.get.assert_called_once_with("/v2/assets", params={"status": "active", "asset_class": "crypto"})


if __name__ == "__main__":
    unittest.main()
