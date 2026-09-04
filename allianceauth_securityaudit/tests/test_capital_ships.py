"""Tests for the capital ship registry.

These tests guard against the kind of type-ID/name swap bugs that have
happened before (e.g. Phoenix/Naglfar and Minokawa/Ninazu were swapped
in an earlier revision). They verify the registry is internally
consistent and that image URLs are well-formed.
"""
from django.test import SimpleTestCase

from allianceauth_securityaudit.services.audit_analysis.capital_ships import (
    CAPITAL_SHIPS,
    CAPITAL_SHIP_GROUPS,
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    CATEGORY_TO_GROUPS,
    ship_image_url,
)


class CapitalShipRegistryTests(SimpleTestCase):
    def test_no_duplicate_type_ids(self):
        """Every type ID in CAPITAL_SHIPS must be unique."""
        type_ids = list(CAPITAL_SHIPS.keys())
        self.assertEqual(len(type_ids), len(set(type_ids)),
                         "Duplicate type IDs found in CAPITAL_SHIPS")

    def test_no_duplicate_ship_names_within_category(self):
        """Ship names within the same category must be unique."""
        names_by_cat = {}
        for type_id, (cat, name) in CAPITAL_SHIPS.items():
            names_by_cat.setdefault(cat, []).append(name)
        for cat, names in names_by_cat.items():
            self.assertEqual(len(names), len(set(names)),
                             f"Duplicate ship names in category '{cat}': {names}")

    def test_all_categories_represented(self):
        """Every category in CATEGORY_ORDER must have at least one ship."""
        cats_in_registry = {cat for cat, _ in CAPITAL_SHIPS.values()}
        for cat in CATEGORY_ORDER:
            self.assertIn(cat, cats_in_registry,
                          f"Category '{cat}' has no ships in CAPITAL_SHIPS")
            self.assertIn(cat, CATEGORY_LABELS,
                          f"Category '{cat}' missing from CATEGORY_LABELS")

    def test_category_to_groups_covers_all_categories(self):
        """CATEGORY_TO_GROUPS must have an entry for every category."""
        for cat in CATEGORY_ORDER:
            self.assertIn(cat, CATEGORY_TO_GROUPS,
                          f"Category '{cat}' missing from CATEGORY_TO_GROUPS")

    def test_known_type_id_mappings(self):
        """Verify specific type IDs that were previously swapped and corrected."""
        known_good = {
            19722: "Naglfar",
            19726: "Phoenix",
            37605: "Minokawa",
            37607: "Ninazu",
            23757: "Archon",
            671: "Erebus",
            22852: "Hel",
            37604: "Apostle",
        }
        for type_id, expected_name in known_good.items():
            self.assertIn(type_id, CAPITAL_SHIPS,
                          f"Type ID {type_id} ({expected_name}) missing from CAPITAL_SHIPS")
            actual_cat, actual_name = CAPITAL_SHIPS[type_id]
            self.assertEqual(actual_name, expected_name,
                             f"Type ID {type_id} expected '{expected_name}', got '{actual_name}'")

    def test_capital_ship_groups_are_integers(self):
        """All group IDs must be integers (zKill requires numeric groupID)."""
        for gid in CAPITAL_SHIP_GROUPS:
            self.assertIsInstance(gid, int,
                                  f"Group ID {gid!r} is not an integer")

    def test_ship_image_url_format(self):
        """ship_image_url must return a valid EVE image server URL."""
        url = ship_image_url(19726)
        self.assertTrue(url.startswith("https://images.evetech.net/types/"),
                        f"Unexpected URL format: {url}")
        self.assertIn("/render?size=", url)

    def test_ship_image_url_custom_size(self):
        """ship_image_url must respect the size parameter."""
        url = ship_image_url(23757, size=256)
        self.assertIn("size=256", url)

    def test_every_ship_has_a_valid_category(self):
        """Every ship's category must be in CATEGORY_ORDER."""
        for type_id, (cat, name) in CAPITAL_SHIPS.items():
            self.assertIn(cat, CATEGORY_ORDER,
                          f"Ship '{name}' (type {type_id}) has unknown category '{cat}'")
