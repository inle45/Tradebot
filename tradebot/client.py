import base64
import json
import time
from urllib.parse import quote, urlencode

import requests
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from tradebot.config import Config


class RevxApiError(Exception):
    pass


class RevxClient:
    """Client HTTP pour l'API de Revolut X, avec signature Ed25519 des requêtes
    authentifiées (voir https://developer.revolut.com/docs/x-api/)."""

    def __init__(self, config=Config):
        self.config = config
        self.session = requests.Session()
        self._private_key = None

    def _load_private_key(self):
        if self._private_key is None:
            with open(self.config.private_key_path, "rb") as f:
                self._private_key = load_pem_private_key(f.read(), password=None)
        return self._private_key

    def _sign(self, timestamp_ms, method, path, query_string, body):
        message = f"{timestamp_ms}{method}{path}{query_string}{body}".encode("utf-8")
        signature = self._load_private_key().sign(message)
        return base64.b64encode(signature).decode("ascii")

    def _request(self, method, path, params=None, body_obj=None, authenticated=True):
        query_string = ""
        if params:
            query_string = "?" + urlencode(sorted(params.items()))

        body = json.dumps(body_obj, separators=(",", ":")) if body_obj is not None else ""
        url = self.config.base_url + path + query_string

        headers = {"Content-Type": "application/json"}
        if authenticated:
            timestamp_ms = str(int(time.time() * 1000))
            api_path = "/api" + path
            headers.update(
                {
                    "X-Revx-API-Key": self.config.api_key,
                    "X-Revx-Timestamp": timestamp_ms,
                    "X-Revx-Signature": self._sign(
                        timestamp_ms, method, api_path, query_string, body
                    ),
                }
            )

        response = self.session.request(
            method, url, data=body if body_obj is not None else None, headers=headers
        )
        if response.status_code == 429:
            raise RevxApiError(
                f"Rate limit atteint, retry après {response.headers.get('Retry-After')} ms"
            )
        if not response.ok:
            raise RevxApiError(f"{method} {path} -> {response.status_code}: {response.text}")
        return response.json() if response.content else {}

    # --- Données de marché publiques (pas besoin de clé API) ---

    def get_ticker(self, symbol):
        data = self._request("GET", "/1.0/public/tickers", authenticated=False)
        for ticker in data.get("data", data if isinstance(data, list) else []):
            if ticker.get("symbol") == symbol:
                return ticker
        raise RevxApiError(f"Symbole {symbol} introuvable dans les tickers")

    def get_candles(self, symbol, interval_minutes, limit=100):
        return self._request(
            "GET",
            f"/1.0/public/candles/{quote(symbol, safe='')}",
            params={"interval": interval_minutes, "limit": limit},
            authenticated=False,
        )

    # --- Données de compte (authentifié) ---

    def get_balances(self):
        return self._request("GET", "/1.0/balances")

    def get_active_orders(self, symbol=None):
        params = {"symbol": symbol} if symbol else None
        return self._request("GET", "/1.0/orders/active", params=params)

    # --- Trading (authentifié) ---

    def place_market_order(self, symbol, side, client_order_id, quote_size=None, base_size=None):
        order_configuration = {"market": {}}
        if quote_size is not None:
            order_configuration["market"]["quote_size"] = str(quote_size)
        if base_size is not None:
            order_configuration["market"]["base_size"] = str(base_size)

        body = {
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "order_configuration": order_configuration,
        }
        return self._request("POST", "/1.0/orders", body_obj=body)

    def place_limit_order(
        self, symbol, side, client_order_id, price, base_size, post_only=True
    ):
        """Ordre limite. Avec post_only, l'ordre est rejeté s'il s'exécuterait
        immédiatement — ce qui garantit le tarif "maker" (0% sur Revolut X au
        lieu de 0,09% en taker), au prix d'une exécution non garantie."""
        body = {
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "order_configuration": {
                "limit": {
                    "price": str(price),
                    "base_size": str(base_size),
                    "execution_instructions": ["post_only"] if post_only else ["allow_taker"],
                }
            },
        }
        return self._request("POST", "/1.0/orders", body_obj=body)

    def get_order(self, venue_order_id):
        return self._request("GET", f"/1.0/orders/{venue_order_id}")

    def cancel_order(self, venue_order_id):
        return self._request("DELETE", f"/1.0/orders/{venue_order_id}")

    def get_order_book(self, symbol, limit=5):
        return self._request(
            "GET",
            f"/2.0/public/order-book/{quote(symbol, safe='')}",
            params={"limit": limit},
            authenticated=False,
        )
