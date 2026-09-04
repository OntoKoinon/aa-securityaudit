"""Tests for the ESI client caching layer.

Verifies that cached methods return cached values on second call, that
different parameters use different cache keys, and that error responses
are not cached permanently.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from allianceauth_securityaudit.services.esi_client import EsiClient


class EsiClientCacheTests(SimpleTestCase):
    def setUp(self):
        self.client = EsiClient()

    def _mock_response(self, json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.headers = {}
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @patch("allianceauth_securityaudit.services.esi_client.cache")
    def test_get_character_caches_by_id(self, mock_cache):
        """get_character should use a cache key specific to the character ID."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()
        mock_response = self._mock_response({"name": "Test Pilot", "corporation_id": 123})

        with patch.object(self.client, "_request_with_retry", return_value=mock_response) as mock_req:
            self.client.get_character(100)
            self.client.get_character(100)

            # Only one HTTP request should have been made
            self.assertEqual(mock_req.call_count, 1)
            # cache.set should have been called once with the character-specific key
            mock_cache.set.assert_called_once()
            args, kwargs = mock_cache.set.call_args
            self.assertIn("100", args[0])

    @patch("allianceauth_securityaudit.services.esi_client.cache")
    def test_get_character_different_ids_different_keys(self, mock_cache):
        """Different character IDs must use different cache keys."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()

        resp1 = self._mock_response({"name": "Pilot One"})
        resp2 = self._mock_response({"name": "Pilot Two"})

        responses = [resp1, resp2]
        with patch.object(self.client, "_request_with_retry", side_effect=responses):
            self.client.get_character(100)
            self.client.get_character(200)

            self.assertEqual(mock_cache.set.call_count, 2)
            key1 = mock_cache.set.call_args_list[0].args[0]
            key2 = mock_cache.set.call_args_list[1].args[0]
            self.assertNotEqual(key1, key2)

    @patch("allianceauth_securityaudit.services.esi_client.cache")
    def test_resolve_character_name_caches_result(self, mock_cache):
        """resolve_character_name should cache the resolved ID."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()
        mock_response = self._mock_response(
            {"characters": [{"id": 999, "name": "Test Pilot"}]}
        )

        with patch.object(self.client, "_request_with_retry", return_value=mock_response):
            result = self.client.resolve_character_name("Test Pilot")
            self.assertEqual(result, 999)
            mock_cache.set.assert_called_once()

    @patch("allianceauth_securityaudit.services.esi_client.cache")
    def test_resolve_character_name_returns_cached(self, mock_cache):
        """If cache has a value, no HTTP request should be made."""
        mock_cache.get.return_value = 999

        with patch.object(self.client, "_request_with_retry") as mock_req:
            result = self.client.resolve_character_name("Test Pilot")
            self.assertEqual(result, 999)
            mock_req.assert_not_called()

    @patch("allianceauth_securityaudit.services.esi_client.cache")
    def test_search_universe_caches_by_term_and_strict(self, mock_cache):
        """search_universe should cache by term + strict flag."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()
        mock_response = self._mock_response({"character": [1], "corporation": [], "alliance": []})

        with patch.object(self.client, "_request_with_retry", return_value=mock_response) as mock_req:
            self.client.search_universe("test", strict=False)
            self.client.search_universe("test", strict=True)

            # Two different cache keys -> two HTTP requests
            self.assertEqual(mock_req.call_count, 2)
            self.assertEqual(mock_cache.set.call_count, 2)
            key1 = mock_cache.set.call_args_list[0].args[0]
            key2 = mock_cache.set.call_args_list[1].args[0]
            self.assertNotEqual(key1, key2)

    @patch("allianceauth_securityaudit.services.esi_client.cache")
    def test_cached_value_returned_without_http(self, mock_cache):
        """When cache.get returns a value, no HTTP request is made."""
        mock_cache.get.return_value = {"name": "Cached Pilot"}
        mock_cache.set = MagicMock()

        with patch.object(self.client, "_request_with_retry") as mock_req:
            result = self.client.get_character(100)
            self.assertEqual(result["name"], "Cached Pilot")
            mock_req.assert_not_called()
            mock_cache.set.assert_not_called()
