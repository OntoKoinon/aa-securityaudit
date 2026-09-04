import hashlib
import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache

from .esi_client import EsiClient

LOGGER = logging.getLogger(__name__)

# Janice market prices shift, but the same contract item set appraised
# multiple times within a run (or across closely-spaced runs) should
# not hit the API repeatedly.
JANICE_CACHE_TTL = 3600  # 1 hour


class JaniceClient:
    """Thin wrapper for the Janice v1 pricer API."""

    def __init__(self):
        self.base_url = "https://janice.e-351.com/api/rest/v1"
        self.api_key = getattr(settings, "SECURITYAUDIT_JANICE_API_KEY", "")
        self.market = int(getattr(settings, "SECURITYAUDIT_JANICE_MARKET", 2))
        user_agent = getattr(
            settings,
            "SECURITYAUDIT_USER_AGENT",
            "AllianceAuth-SecurityAudit/0.1",
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": user_agent,
            }
        )

    @staticmethod
    def _resolve_type_names(type_ids):
        try:
            payload = [int(t) for t in type_ids if t]
            return EsiClient().resolve_names(payload) or {}
        except Exception as exc:
            LOGGER.warning("Could not resolve type names for Janice: %s", exc)
            return {}

    @staticmethod
    def _parse_appraisal(data):
        if isinstance(data, list):
            total_buy = Decimal("0")
            total_sell = Decimal("0")
            for row in data:
                qty = int(row.get("quantity") or 1)
                prices = row.get("price") or {}
                if isinstance(prices, dict):
                    buy = Decimal(str(prices.get("buy") or 0))
                    sell = Decimal(str(prices.get("sell") or 0))
                else:
                    buy = sell = Decimal(str(prices or 0))
                total_buy += buy * qty
                total_sell += sell * qty
            return {
                "buy": total_buy,
                "sell": total_sell,
                "total": max(total_buy, total_sell),
            }

        if isinstance(data, dict):
            totals = data.get("totals") or {}
            if totals:
                total_buy = Decimal(str(totals.get("buy") or 0))
                total_sell = Decimal(str(totals.get("sell") or 0))
                return {
                    "buy": total_buy,
                    "sell": total_sell,
                    "total": max(total_buy, total_sell),
                }
            rows = data.get("items") or data.get("data") or []
            return JaniceClient._parse_appraisal(rows)

        return {"buy": Decimal("0"), "sell": Decimal("0"), "total": Decimal("0")}

    def appraise_items(self, items):
        """Appraise a list of {'type_id': int, 'quantity': int} dicts."""
        if not items:
            return {"buy": Decimal("0"), "sell": Decimal("0"), "total": Decimal("0")}

        # Cache by a stable hash of the item set so repeated appraisals of
        # the same contract items don't hit Janice repeatedly.
        item_sig = sorted(
            (int(i.get("type_id") or 0), int(i.get("quantity") or 1)) for i in items
        )
        cache_key = "securityaudit:janice:" + hashlib.md5(repr(item_sig).encode("utf-8")).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        type_ids = {item.get("type_id") for item in items if item.get("type_id")}
        names = self._resolve_type_names(type_ids)

        lines = []
        for item in items:
            name = names.get(item.get("type_id"))
            if not name:
                continue
            quantity = int(item.get("quantity") or 1)
            lines.append(f"{quantity} {name}")

        if not lines:
            return {"buy": Decimal("0"), "sell": Decimal("0"), "total": Decimal("0")}

        url = f"{self.base_url.rstrip('/')}/pricer"
        params = {"key": self.api_key}
        if self.market:
            params["market"] = self.market

        body = "\n".join(lines)
        try:
            response = self.session.post(
                url,
                params=params,
                data=body,
                headers={"Content-Type": "text/plain"},
                timeout=60,
            )
            response.raise_for_status()
            result = self._parse_appraisal(response.json())
            cache.set(cache_key, result, JANICE_CACHE_TTL)
            return result
        except Exception as exc:
            LOGGER.warning("Janice appraisal failed: %s", exc)
            return {"buy": Decimal("0"), "sell": Decimal("0"), "total": Decimal("0")}

    def price_items(self, items):
        """Return the total ISK value for the supplied items; 0 on failure."""
        appraisal = self.appraise_items(items)
        return appraisal.get("total", Decimal("0"))
