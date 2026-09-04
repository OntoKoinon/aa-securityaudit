import hashlib
import logging
import time
from django.conf import settings
from django.core.cache import cache
import requests

LOGGER = logging.getLogger(__name__)

# zKill killmails are immutable once published, but new killmails appear
# over time. A moderate TTL avoids refetching the same pages within a
# single audit run and across closely-spaced runs while still picking
# up new activity eventually.
ZKILL_CACHE_TTL = 3600  # 1 hour


class ZkillClient:
    def __init__(self, throttle_seconds=0.0):
        self.base_url = getattr(settings, "SECURITYAUDIT_ZKILL_BASE", "https://zkillboard.com/api")
        self.throttle = float(throttle_seconds or 0)
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

    def _request_with_retry(self, url, timeout=30):
        """Execute a GET request with retry on 429 and 5xx errors.

        Uses exponential backoff (1s, 2s, 4s) up to 3 retries. Respects the
        Retry-After header on 429 responses. Does not retry on 4xx errors
        other than 429 — those are permanent failures.
        """
        max_retries = 3
        for attempt in range(max_retries + 1):
            response = self.session.get(url, timeout=timeout)
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
                        "zKill GET %s returned %s, retrying in %.1fs (attempt %d/%d)",
                        url, response.status_code, delay, attempt + 1, max_retries,
                    )
                    time.sleep(delay)
                    continue
            response.raise_for_status()
            return response
        return response

    def _get_json(self, url, timeout=30):
        cache_key = "securityaudit:zkill:" + hashlib.md5(url.encode("utf-8")).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        response = self._request_with_retry(url, timeout=timeout)
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            return []
        result = data if isinstance(data, list) else []
        cache.set(cache_key, result, ZKILL_CACHE_TTL)
        return result

    def _throttle(self):
        if self.throttle > 0:
            time.sleep(self.throttle)

    def _paginated(self, base_url, max_pages=1):
        results = []
        for page in range(1, max_pages + 1):
            url = f"{base_url.rstrip('/')}/page/{page}/" if page > 1 else base_url
            data = self._get_json(url)
            if not data:
                break
            results.extend(data)
            self._throttle()
        return results

    def get_recent_kills(self, character_id, max_pages=1):
        base_url = f"{self.base_url.rstrip('/')}/kills/characterID/{character_id}/"
        return self._paginated(base_url, max_pages=max_pages)

    def get_recent_losses(self, character_id, max_pages=1):
        base_url = f"{self.base_url.rstrip('/')}/losses/characterID/{character_id}/"
        return self._paginated(base_url, max_pages=max_pages)

    def get_losses_by_group(self, character_id, group_id, max_pages=1):
        base_url = f"{self.base_url.rstrip('/')}/losses/characterID/{character_id}/groupID/{group_id}/"
        return self._paginated(base_url, max_pages=max_pages)

    def get_kills_by_group(self, character_id, group_id, max_pages=1):
        """Killmails where character was an attacker flying a ship in group_id.

        zKill's kills/characterID endpoint filters by the attacker's ship when
        combined with shipTypeID/groupID, so this returns killmails where the
        character was the one in the capital hull.
        """
        base_url = f"{self.base_url.rstrip('/')}/kills/characterID/{character_id}/groupID/{group_id}/"
        return self._paginated(base_url, max_pages=max_pages)

    def get_kills_by_ship_type(self, character_id, ship_type_id, max_pages=1):
        """Killmails where character was an attacker flying ship_type_id."""
        base_url = f"{self.base_url.rstrip('/')}/kills/characterID/{character_id}/shipTypeID/{ship_type_id}/"
        return self._paginated(base_url, max_pages=max_pages)
