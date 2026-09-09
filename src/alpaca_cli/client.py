"""Thin HTTP client for the Alpaca Trading and Market Data APIs."""

import time
from typing import Any, Optional

import requests

from .config import DATA_BASE, Credentials

MAX_RETRIES = 3


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"API error {status}: {message}")
        self.status = status
        self.message = message


class AlpacaClient:
    def __init__(self, creds: Credentials):
        self.creds = creds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "APCA-API-KEY-ID": creds.api_key,
                "APCA-API-SECRET-KEY": creds.secret_key,
                "Accept": "application/json",
            }
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        data_api: bool = False,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> Any:
        base = DATA_BASE if data_api else self.creds.trading_base
        url = base + path
        for attempt in range(MAX_RETRIES + 1):
            resp = self.session.request(method, url, params=params, json=json, timeout=30)
            if resp.status_code == 429 and attempt < MAX_RETRIES:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2 ** attempt
                time.sleep(min(delay, 30))
                continue
            break
        if resp.status_code >= 400:
            try:
                message = resp.json().get("message", resp.text)
            except ValueError:
                message = resp.text
            if not message or message.lstrip().startswith("<"):
                message = f"HTTP {resp.status_code} {resp.reason}"
            raise APIError(resp.status_code, message.strip())
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> Any:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs) -> Any:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> Any:
        return self.request("DELETE", path, **kwargs)
