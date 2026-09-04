"""Tests for the zKill client caching layer.

Verifies that zKill responses are cached by URL hash, that different
endpoints/characters/pages use different cache keys, and that error
responses return an empty list instead of being cached as errors.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from allianceauth_securityaudit.services.zkill_client import ZkillClient


class ZkillClientCacheTests(SimpleTestCase):
    def setUp(self):
        self.client = ZkillClient()

    def _mock_response(self, json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.headers = {}
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("allianceauth_securityaudit.services.zkill_client.cache")
    def test_get_json_caches_by_url(self, mock_cache):
        """_get_json should cache by URL hash and not re-fetch on second call."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()
        mock_response = self._mock_response([{"killmail_id": 1}])

        with patch.object(self.client, "_request_with_retry", return_value=mock_response) as mock_req:
            self.client._get_json("https://zkillboard.com/api/kills/characterID/100/")
            self.client._get_json("https://zkillboard.com/api/kills/characterID/100/")

            self.assertEqual(mock_req.call_count, 1)
            mock_cache.set.assert_called_once()

    @patch("allianceauth_securityaudit.services.zkill_client.cache")
    def test_different_urls_different_cache_keys(self, mock_cache):
        """Different URLs must produce different cache keys."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()

        resp1 = self._mock_response([{"killmail_id": 1}])
        resp2 = self._mock_response([{"killmail_id": 2}])

        with patch.object(self.client, "_request_with_retry", side_effect=[resp1, resp2]):
            self.client._get_json("https://zkillboard.com/api/kills/characterID/100/")
            self.client._get_json("https://zkillboard.com/api/kills/characterID/200/")

            self.assertEqual(mock_cache.set.call_count, 2)
            key1 = mock_cache.set.call_args_list[0].args[0]
            key2 = mock_cache.set.call_args_list[1].args[0]
            self.assertNotEqual(key1, key2)

    @patch("allianceauth_securityaudit.services.zkill_client.cache")
    def test_error_response_returns_empty_list(self, mock_cache):
        """A response with an 'error' key should return [] and not be cached."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()
        mock_response = self._mock_response({"error": "group is invalid"})

        with patch.object(self.client, "_request_with_retry", return_value=mock_response):
            result = self.client._get_json("https://zkillboard.com/api/test/")

            self.assertEqual(result, [])
            # Error responses should not be cached
            mock_cache.set.assert_not_called()

    @patch("allianceauth_securityaudit.services.zkill_client.cache")
    def test_cached_value_returned_without_http(self, mock_cache):
        """When cache has a value, no HTTP request is made."""
        cached_data = [{"killmail_id": 42}]
        mock_cache.get.return_value = cached_data
        mock_cache.set = MagicMock()

        with patch.object(self.client, "_request_with_retry") as mock_req:
            result = self.client._get_json("https://zkillboard.com/api/kills/characterID/100/")

            self.assertEqual(result, cached_data)
            mock_req.assert_not_called()
            mock_cache.set.assert_not_called()

    @patch("allianceauth_securityaudit.services.zkill_client.cache")
    def test_paginated_uses_different_keys_per_page(self, mock_cache):
        """Different pages must use different cache keys (URL includes /page/N/)."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()

        resp1 = self._mock_response([{"killmail_id": 1}])
        resp2 = self._mock_response([{"killmail_id": 2}])

        with patch.object(self.client, "_request_with_retry", side_effect=[resp1, resp2]):
            self.client._get_json("https://zkillboard.com/api/kills/characterID/100/")
            self.client._get_json("https://zkillboard.com/api/kills/characterID/100/page/2/")

            self.assertEqual(mock_cache.set.call_count, 2)
            key1 = mock_cache.set.call_args_list[0].args[0]
            key2 = mock_cache.set.call_args_list[1].args[0]
            self.assertNotEqual(key1, key2)

    @patch("allianceauth_securityaudit.services.zkill_client.cache")
    def test_get_recent_kills_returns_cached(self, mock_cache):
        """get_recent_kills should return cached data without HTTP on second call."""
        cached_kills = [{"killmail_id": 1}, {"killmail_id": 2}]
        mock_cache.get.return_value = cached_kills
        mock_cache.set = MagicMock()

        with patch.object(self.client, "_request_with_retry") as mock_req:
            result = self.client.get_recent_kills(100, max_pages=1)

            self.assertEqual(result, cached_kills)
            mock_req.assert_not_called()
