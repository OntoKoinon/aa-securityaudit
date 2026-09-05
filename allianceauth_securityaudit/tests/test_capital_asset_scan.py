"""Tests for the MemberAudit capital asset/ship ownership scan.

These tests verify that get_capital_ownership gracefully handles
missing MemberAudit models, correctly aggregates asset counts, and
detects the current ship. MemberAudit models are mocked since the
app may not be installed in the test environment.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from allianceauth_securityaudit.services.memberaudit_adapter import MemberAuditAdapter


class GetCapitalOwnershipTests(SimpleTestCase):
    def test_empty_input_returns_empty(self):
        """Passing no character IDs should return an empty dict."""
        result = MemberAuditAdapter.get_capital_ownership([])
        self.assertEqual(result, {})

    def test_none_input_returns_empty(self):
        """Passing None should return an empty dict."""
        result = MemberAuditAdapter.get_capital_ownership(None)
        self.assertEqual(result, {})

    @patch("allianceauth_securityaudit.services.memberaudit_adapter.cache")
    @patch("allianceauth_securityaudit.services.memberaudit_adapter.apps")
    def test_memberaudit_not_installed_returns_empty(self, mock_apps, mock_cache):
        """If MemberAudit models are not available, return empty dict."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()
        mock_apps.get_model.side_effect = LookupError("not found")

        result = MemberAuditAdapter.get_capital_ownership([100, 200])
        self.assertEqual(result, {})

    @patch("allianceauth_securityaudit.services.memberaudit_adapter.cache")
    @patch("allianceauth_securityaudit.services.memberaudit_adapter.apps")
    def test_cached_result_returned_without_queries(self, mock_apps, mock_cache):
        """If cache has a value for a character, no DB queries should be made."""
        # Per-character cache returns the character's data directly (not
        # wrapped in a char_id key — the outer method assembles that).
        cached_char_data = {23757: {"asset_count": 1, "is_current_ship": False}}
        mock_cache.get.return_value = cached_char_data

        result = MemberAuditAdapter.get_capital_ownership([100])
        self.assertEqual(result, {100: cached_char_data})
        # get_model should not be called when cache hits
        mock_apps.get_model.assert_not_called()

    @patch("allianceauth_securityaudit.services.memberaudit_adapter.cache")
    @patch("allianceauth_securityaudit.services.memberaudit_adapter.apps")
    def test_asset_count_aggregation(self, mock_apps, mock_cache):
        """Asset quantities should be summed per type ID."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()

        # Mock MemberAudit models
        CharacterModel = MagicMock()
        CharacterAsset = MagicMock()
        CharacterShip = MagicMock()

        def get_model(app_label, model_name):
            if model_name == "Character":
                return CharacterModel
            if model_name == "CharacterAsset":
                return CharacterAsset
            if model_name == "CharacterShip":
                return CharacterShip
            return None

        mock_apps.get_model.side_effect = get_model

        # Mock character lookup
        ma_char = MagicMock()
        CharacterModel.objects.select_related.return_value.get.return_value = ma_char

        # Mock assets: 2 Archons (type 23757) with quantities 1 and 2
        asset1 = MagicMock()
        asset1.eve_type_id = 23757
        asset1.quantity = 1
        asset1.is_singleton = True
        asset2 = MagicMock()
        asset2.eve_type_id = 23757
        asset2.quantity = 2
        asset2.is_singleton = False
        CharacterAsset.objects.filter.return_value = [asset1, asset2]

        # Mock ship: no current ship
        CharacterShip.objects.get.side_effect = CharacterShip.DoesNotExist()

        result = MemberAuditAdapter.get_capital_ownership([100])

        self.assertIn(100, result)
        self.assertIn(23757, result[100])
        self.assertEqual(result[100][23757]["asset_count"], 3)
        self.assertFalse(result[100][23757]["is_current_ship"])

    @patch("allianceauth_securityaudit.services.memberaudit_adapter.cache")
    @patch("allianceauth_securityaudit.services.memberaudit_adapter.apps")
    def test_current_ship_detected(self, mock_apps, mock_cache):
        """CharacterShip should set is_current_ship=True for the matching type."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()

        CharacterModel = MagicMock()
        CharacterAsset = MagicMock()
        CharacterShip = MagicMock()

        def get_model(app_label, model_name):
            if model_name == "Character":
                return CharacterModel
            if model_name == "CharacterAsset":
                return CharacterAsset
            if model_name == "CharacterShip":
                return CharacterShip
            return None

        mock_apps.get_model.side_effect = get_model

        ma_char = MagicMock()
        CharacterModel.objects.select_related.return_value.get.return_value = ma_char

        # No assets
        CharacterAsset.objects.filter.return_value = []

        # Current ship is a Phoenix (type 19726)
        ship = MagicMock()
        ship.eve_type_id = 19726
        CharacterShip.objects.get.return_value = ship

        result = MemberAuditAdapter.get_capital_ownership([100])

        self.assertIn(100, result)
        self.assertIn(19726, result[100])
        self.assertTrue(result[100][19726]["is_current_ship"])
        self.assertEqual(result[100][19726]["asset_count"], 0)

    @patch("allianceauth_securityaudit.services.memberaudit_adapter.cache")
    @patch("allianceauth_securityaudit.services.memberaudit_adapter.apps")
    def test_character_not_in_memberaudit_skipped(self, mock_apps, mock_cache):
        """Characters not found in MemberAudit should be silently skipped."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()

        CharacterModel = MagicMock()
        CharacterAsset = MagicMock()
        CharacterShip = MagicMock()

        def get_model(app_label, model_name):
            if model_name == "Character":
                return CharacterModel
            if model_name == "CharacterAsset":
                return CharacterAsset
            if model_name == "CharacterShip":
                return CharacterShip
            return None

        mock_apps.get_model.side_effect = get_model

        # Character not found
        CharacterModel.objects.select_related.return_value.get.side_effect = (
            CharacterModel.DoesNotExist()
        )

        result = MemberAuditAdapter.get_capital_ownership([999])
        self.assertEqual(result, {})

    @patch("allianceauth_securityaudit.services.memberaudit_adapter.cache")
    @patch("allianceauth_securityaudit.services.memberaudit_adapter.apps")
    def test_non_capital_ship_type_ignored(self, mock_apps, mock_cache):
        """CharacterShip with a non-capital type ID should be ignored."""
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()

        CharacterModel = MagicMock()
        CharacterAsset = MagicMock()
        CharacterShip = MagicMock()

        def get_model(app_label, model_name):
            if model_name == "Character":
                return CharacterModel
            if model_name == "CharacterAsset":
                return CharacterAsset
            if model_name == "CharacterShip":
                return CharacterShip
            return None

        mock_apps.get_model.side_effect = get_model

        ma_char = MagicMock()
        CharacterModel.objects.select_related.return_value.get.return_value = ma_char
        CharacterAsset.objects.filter.return_value = []

        # Current ship is a frigate (type 587) - not a capital
        ship = MagicMock()
        ship.eve_type_id = 587
        CharacterShip.objects.get.return_value = ship

        result = MemberAuditAdapter.get_capital_ownership([100])
        self.assertEqual(result, {})
