import hashlib
import logging
import time
from datetime import datetime
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache

LOGGER = logging.getLogger(__name__)

# TTLs for rarely/never-changing ESI data (in seconds)
NAME_CACHE_TTL = 86400
CHARACTER_CACHE_TTL = 3600
CORPORATION_CACHE_TTL = 86400
ALLIANCE_CACHE_TTL = 86400
NPC_CORPS_CACHE_TTL = 604800
CORP_HISTORY_CACHE_TTL = 21600
CONTRACTS_CACHE_TTL = 300
CONTRACT_ITEMS_CACHE_TTL = 21600
MARKET_ORDERS_CACHE_TTL = 300
NAME_TO_ID_CACHE_TTL = 86400
SEARCH_CACHE_TTL = 300
TYPE_INFO_CACHE_TTL = 604800  # types are immutable


class EsiClient:
    def __init__(self, throttle_seconds=None):
        self.base_url = getattr(settings, "SECURITYAUDIT_ESI_BASE", "https://esi.evetech.net/latest")
        self.throttle = 0.0
        if throttle_seconds is not None:
            self.throttle = float(throttle_seconds)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": getattr(
                    settings,
                    "SECURITYAUDIT_USER_AGENT",
                    "AllianceAuth-SecurityAudit/0.1",
                ),
            }
        )

    def _request_with_retry(self, method, url, timeout=30, **kwargs):
        """Execute an HTTP request with retry on 429 and 5xx errors.

        Uses exponential backoff (1s, 2s, 4s) up to 3 retries. Respects the
        Retry-After header on 429 responses. Does not retry on 4xx errors
        other than 429 — those are permanent failures.
        """
        max_retries = 3
        for attempt in range(max_retries + 1):
            response = self.session.request(method, url, timeout=timeout, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < max_retries:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except (TypeError, ValueError):
                            delay = 2 ** attempt
                    else:
                        delay = 2 ** attempt
                    LOGGER.warning(
                        "ESI %s %s returned %s, retrying in %.1fs (attempt %d/%d)",
                        method, url, response.status_code, delay, attempt + 1, max_retries,
                    )
                    time.sleep(delay)
                    continue
            response.raise_for_status()
            return response
        return response

    def _get(self, path, timeout=30):
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        response = self._request_with_retry("GET", url, timeout=timeout)
        if self.throttle > 0:
            time.sleep(self.throttle)
        return response.json()

    def _post(self, path, payload, timeout=30):
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        response = self._request_with_retry("POST", url, timeout=timeout, json=payload)
        if self.throttle > 0:
            time.sleep(self.throttle)
        return response.json()

    def resolve_character_name(self, character_name):
        cache_key = f"securityaudit:esi:charname:{character_name.casefold()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        payload = [character_name]
        data = self._post("universe/ids/?datasource=tranquility&language=en", payload)
        for item in data.get("characters", []):
            if item.get("name", "").casefold() == character_name.casefold():
                char_id = item.get("id")
                cache.set(cache_key, char_id, NAME_TO_ID_CACHE_TTL)
                return char_id
        return None

    def resolve_corporation_name(self, corporation_name):
        cache_key = f"securityaudit:esi:corpname:{corporation_name.casefold()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        payload = [corporation_name]
        data = self._post("universe/ids/?datasource=tranquility&language=en", payload)
        for item in data.get("corporations", []):
            if item.get("name", "").casefold() == corporation_name.casefold():
                corp_id = item.get("id")
                cache.set(cache_key, corp_id, NAME_TO_ID_CACHE_TTL)
                return corp_id
        return None

    def resolve_names_to_ids(self, names):
        """Resolve exact EVE names to IDs, returning a list of dicts with type, id, and name."""
        if not names:
            return []
        # Cache by a stable hash of the sorted name set.
        name_sig = tuple(sorted(n.casefold() for n in names))
        cache_key = "securityaudit:esi:names2ids:" + hashlib.md5(repr(name_sig).encode("utf-8")).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        payload = list(names)
        try:
            data = self._post("universe/ids/?datasource=tranquility&language=en", payload)
        except Exception:
            return []
        type_map = {
            "characters": "character",
            "corporations": "corporation",
            "alliances": "alliance",
        }
        results = []
        for category, key in type_map.items():
            for item in data.get(category, []):
                results.append({
                    "type": key,
                    "id": item.get("id"),
                    "name": item.get("name", ""),
                })
        cache.set(cache_key, results, NAME_TO_ID_CACHE_TTL)
        return results

    def resolve_names(self, ids):
        if not ids:
            return {}
        payload = [int(i) for i in ids if i is not None]

        keys = {i: f"securityaudit:esi:name:{i}" for i in payload}
        cached = cache.get_many(keys.values())
        by_id = {int(k.split(":")[-1]): cached[k] for k in cached if cached[k] is not None}
        missing = [i for i in payload if i not in by_id]

        if missing:
            try:
                data = self._post("universe/names/?datasource=tranquility", missing)
                for item in data:
                    item_id = item.get("id")
                    if item_id is not None:
                        by_id[item_id] = item.get("name", "")
                        cache.set(keys.get(item_id), by_id[item_id], NAME_CACHE_TTL)
            except Exception:
                pass

        return {i: by_id.get(i, "") for i in payload}

    def search_universe(self, term, strict=False):
        term = (term or "").strip()
        if len(term) < 2:
            return {"characters": [], "corporations": [], "alliances": []}
        strict_value = "true" if strict else "false"
        cache_key = f"securityaudit:esi:search:{term.casefold()}:{strict_value}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        path = (
            "search/?categories=character,corporation,alliance"
            f"&search={quote(term)}"
            f"&strict={strict_value}"
            "&datasource=tranquility"
        )
        data = self._get(path)
        result = {
            "characters": data.get("character", []) or [],
            "corporations": data.get("corporation", []) or [],
            "alliances": data.get("alliance", []) or [],
        }
        cache.set(cache_key, result, SEARCH_CACHE_TTL)
        return result

    def _cached_get(self, key, path, ttl):
        cached = cache.get(key)
        if cached is not None:
            return cached
        data = self._get(path)
        cache.set(key, data, ttl)
        return data

    def get_character(self, character_id):
        key = f"securityaudit:esi:character:{character_id}"
        return self._cached_get(key, f"characters/{character_id}/?datasource=tranquility", CHARACTER_CACHE_TTL)

    def get_corporation(self, corp_id):
        key = f"securityaudit:esi:corporation:{corp_id}"
        return self._cached_get(key, f"corporations/{corp_id}/?datasource=tranquility", CORPORATION_CACHE_TTL)

    def get_npc_corporations(self):
        return self._cached_get("securityaudit:esi:npccorps", "corporations/npccorps/?datasource=tranquility", NPC_CORPS_CACHE_TTL)

    def get_type_info(self, type_id):
        """Return ``{"group_id": int, "name": str}`` for a universe type.

        Types are immutable so the result is cached for a week. Returns
        ``None`` on any error (caller should treat as unknown type).
        """
        if not type_id:
            return None
        try:
            type_id = int(type_id)
        except (TypeError, ValueError):
            return None
        key = f"securityaudit:esi:typeinfo:{type_id}"
        cached = cache.get(key)
        if cached is not None:
            return cached
        try:
            data = self._get(f"universe/types/{type_id}/?datasource=tranquility")
        except Exception:
            LOGGER.warning("ESI get_type_info failed for type_id=%s", type_id)
            return None
        if not isinstance(data, dict):
            return None
        result = {
            "group_id": int(data.get("group_id") or 0),
            "name": str(data.get("name") or ""),
        }
        cache.set(key, result, TYPE_INFO_CACHE_TTL)
        return result

    def get_alliance(self, alliance_id):
        key = f"securityaudit:esi:alliance:{alliance_id}"
        return self._cached_get(key, f"alliances/{alliance_id}/?datasource=tranquility", ALLIANCE_CACHE_TTL)

    def get_character_corp_history(self, character_id):
        key = f"securityaudit:esi:corphistory:{character_id}"
        return self._cached_get(key, f"characters/{character_id}/corporationhistory/?datasource=tranquility", CORP_HISTORY_CACHE_TTL)

    def get_character_wallet_journal(self, character_id, token=None):
        headers = {}
        access_token = self._extract_access_token(token)
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        url = f"{self.base_url.rstrip('/')}/characters/{character_id}/wallet/journal/?datasource=tranquility"
        response = self.session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_character_contracts(self, character_id, token=None):
        cache_key = f"securityaudit:esi:contracts:{character_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        headers = {}
        access_token = self._extract_access_token(token)
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        url = f"{self.base_url.rstrip('/')}/characters/{character_id}/contracts/?datasource=tranquility"
        response = self.session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data, CONTRACTS_CACHE_TTL)
        return data

    def get_character_contract_items(self, character_id, contract_id, token=None):
        cache_key = f"securityaudit:esi:contractitems:{character_id}:{contract_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        headers = {}
        access_token = self._extract_access_token(token)
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        url = f"{self.base_url.rstrip('/')}/characters/{character_id}/contracts/{contract_id}/items/?datasource=tranquility"
        response = self.session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data, CONTRACT_ITEMS_CACHE_TTL)
        return data

    def get_character_market_orders(self, character_id, token=None):
        """Fetch active and historical market orders for a character from ESI.

        Returns a list of dicts with keys: order_id, type_id, is_buy_order,
        state, volume_total, volume_remain, issued, duration, location_id,
        price, escrow, min_volume, range.
        """
        cache_key = f"securityaudit:esi:marketorders:{character_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        headers = {}
        access_token = self._extract_access_token(token)
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        url = f"{self.base_url.rstrip('/')}/characters/{character_id}/orders/?datasource=tranquility"
        response = self.session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data, MARKET_ORDERS_CACHE_TTL)
        return data

    @staticmethod
    def _extract_access_token(token):
        if token is None:
            return None
        if isinstance(token, str):
            return token

        for attr in ("access_token", "token"):
            value = getattr(token, attr, None)
            if isinstance(value, str) and value:
                return value

        getter = getattr(token, "valid_access_token", None)
        if callable(getter):
            try:
                value = getter()
                if isinstance(value, str) and value:
                    return value
            except Exception:
                return None
        return None

    @staticmethod
    def parse_esi_time(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            LOGGER.warning("Could not parse ESI datetime value: %s", value)
            return None
