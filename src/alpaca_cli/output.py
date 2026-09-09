"""Human-friendly output helpers: tables, money, and colored P/L."""

import json
from decimal import Decimal
from typing import Any, Callable, List, Optional, Sequence, Tuple

import click

from .symbols import is_crypto, normalize_symbol

# A column is (header, function-that-extracts-a-display-string).
Column = Tuple[str, Callable[[dict], str]]


def print_json(data: Any, query: Optional[str] = None) -> None:
    if query:
        import jmespath

        data = jmespath.search(query, data)
    click.echo(json.dumps(data, indent=2, default=str))


def money(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return f"${float(value):,.2f}"


def price(value: Any, symbol: str) -> str:
    """Keep crypto price precision and label the actual quote currency."""
    if not is_crypto(symbol):
        return money(value)
    if value in (None, ""):
        return "-"
    currency = normalize_symbol(symbol).split("/")[1]
    text = num(value)
    return f"${text}" if currency == "USD" else f"{text} {currency}"


def signed_money(value: Any) -> str:
    """Money with a sign and green/red color, for P/L figures."""
    if value in (None, ""):
        return "-"
    v = float(value)
    text = f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"
    return click.style(text, fg="green" if v >= 0 else "red")


def signed_pct(value: Any) -> str:
    if value in (None, ""):
        return "-"
    v = float(value) * 100
    text = f"{'+' if v >= 0 else ''}{v:.2f}%"
    return click.style(text, fg="green" if v >= 0 else "red")


def num(value: Any) -> str:
    if value in (None, ""):
        return "-"
    text = format(Decimal(str(value)), ",f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def ts(value: Any) -> str:
    """Trim an ISO timestamp to something readable."""
    if not value:
        return "-"
    return str(value).replace("T", " ").split(".")[0].replace("Z", "")


def _visible_len(s: str) -> int:
    return len(click.unstyle(s))


def print_table(columns: Sequence[Column], rows: List[dict]) -> None:
    if not rows:
        click.echo("(none)")
        return
    headers = [h for h, _ in columns]
    cells = [[fn(row) for _, fn in columns] for row in rows]
    widths = [
        max(_visible_len(headers[i]), *(_visible_len(r[i]) for r in cells))
        for i in range(len(columns))
    ]
    click.echo("  ".join(click.style(h.ljust(widths[i]), bold=True) for i, h in enumerate(headers)))
    for r in cells:
        click.echo(
            "  ".join(c + " " * (widths[i] - _visible_len(c)) for i, c in enumerate(r)).rstrip()
        )


def print_kv(pairs: List[Tuple[str, str]]) -> None:
    width = max(len(k) for k, _ in pairs)
    for k, v in pairs:
        click.echo(f"{click.style(k.ljust(width), bold=True)}  {v}")
