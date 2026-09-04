"""Tests for the awox (deliberate friendly-fire) detection mixin.

These tests verify the detection algorithm's qualification paths (damage
ownership, tackle override, HIC ship override), exclusion paths (whoring,
large-fleet crossfire, structure kills, throwaway-ship sparring), the
blue-scouting secondary friendly path, scoring (including super/titan bonus
and blue-scouting bonus), severity escalation, score cap, recency weighting,
and evidence structure (zKill links, kind classification).
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from allianceauth_securityaudit.constants import AWOX_SCORE_CAP
from allianceauth_securityaudit.services.audit_analysis.awox import (
    AwoxDetectionMixin,
    KIND_LABELS,
)


def _make_kill(
    killmail_id=1000001,
    victim_char_id=55555,
    victim_corp_id=20000,
    victim_alliance_id=None,
    victim_ship_type_id=670,  # Capsule
    victim_ship_group_id=29,
    victim_damage_taken=10000,
    attacker_char_id=99999,
    attacker_corp_id=20000,
    attacker_alliance_id=None,
    attacker_damage_done=10000,
    attacker_final_blow=True,
    attacker_weapon_type_id=3242,
    attacker_weapon_group_id=52,
    attacker_ship_type_id=12013,
    attacker_ship_group_id=894,
    attacker_count=1,
    extra_attackers=None,
    zkb_value=0,
    kill_time=None,
    source_character_id=None,
):
    """Build a zKill-shaped killmail dict for testing."""
    if kill_time is None:
        kill_time = timezone.now()
    kill_time_str = kill_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    attackers = [
        {
            "character_id": attacker_char_id,
            "corporation_id": attacker_corp_id,
            "alliance_id": attacker_alliance_id,
            "damage_done": attacker_damage_done,
            "final_blow": attacker_final_blow,
            "weapon_type_id": attacker_weapon_type_id,
            "ship_type_id": attacker_ship_type_id,
        }
    ]
    if extra_attackers:
        attackers.extend(extra_attackers)

    victim = {
        "character_id": victim_char_id,
        "corporation_id": victim_corp_id,
        "alliance_id": victim_alliance_id,
        "ship_type_id": victim_ship_type_id,
        "damage_taken": victim_damage_taken,
    }

    kill = {
        "killmail_id": killmail_id,
        "killmail_time": kill_time_str,
        "victim": victim,
        "attackers": attackers,
        "zkb": {"totalValue": zkb_value},
    }
    if source_character_id is not None:
        kill["__source_character_id"] = source_character_id
    return kill


class _FakePolicy:
    """Minimal policy stand-in for awox detection tests."""

    def __init__(self, **overrides):
        self.awox_min_damage_share = overrides.get("awox_min_damage_share", Decimal("0.50"))
        self.awox_lookback_days = overrides.get("awox_lookback_days", 180)
        self.awox_large_fleet_attacker_threshold = overrides.get("awox_large_fleet_attacker_threshold", 10)
        self.awox_solo_attacker_threshold = overrides.get("awox_solo_attacker_threshold", 3)
        self.awox_min_victim_value = overrides.get("awox_min_victim_value", Decimal("10000000"))
        self.awox_blue_scouting_bonus = overrides.get("awox_blue_scouting_bonus", 15)


class _AwoxEngine(AwoxDetectionMixin):
    """Bare engine instance with mocked esi/blacklist."""

    def __init__(self, policy, esi=None, npc_corp_ids=None):
        self.policy = policy
        self.esi = esi or MagicMock()
        self.npc_corp_ids = npc_corp_ids or set()


def _make_engine(policy=None, npc_corp_ids=None, type_info_map=None, char_info_map=None, resolve_names_map=None):
    """Create an engine with mocked ESI responses."""
    policy = policy or _FakePolicy()
    if npc_corp_ids is None:
        npc_corp_ids = set()

    esi = MagicMock()

    # get_type_info: return from type_info_map or None
    type_info_map = type_info_map or {}
    def _get_type_info(type_id):
        return type_info_map.get(int(type_id)) if type_id else None
    esi.get_type_info.side_effect = _get_type_info

    # get_character: return from char_info_map or {}
    char_info_map = char_info_map or {}
    def _get_character(char_id):
        return char_info_map.get(int(char_id), {})
    esi.get_character.side_effect = _get_character

    # resolve_names: return from resolve_names_map or empty
    resolve_names_map = resolve_names_map or {}
    esi.resolve_names.return_value = resolve_names_map

    # get_npc_corporations
    esi.get_npc_corporations.return_value = list(npc_corp_ids)

    engine = _AwoxEngine(policy, esi=esi, npc_corp_ids=npc_corp_ids)
    return engine


class AwoxDetectionTests(SimpleTestCase):
    """Core detection algorithm tests."""

    def _run_detect(self, kills, character_id=99999, ordered_character_ids=None, character_name_map=None,
                    policy=None, npc_corp_ids=None, type_info_map=None, char_info_map=None,
                    resolve_names_map=None):
        if ordered_character_ids is None:
            ordered_character_ids = [99999]
        if character_name_map is None:
            character_name_map = {99999: "AwoxAlt", 55555: "Victim"}

        with patch("allianceauth_securityaudit.services.audit_analysis.awox.cache") as mock_cache, \
             patch("allianceauth_securityaudit.services.audit_analysis.awox.BlacklistAdapter") as mock_bl, \
             patch("allianceauth_securityaudit.services.audit_analysis.awox.EnemyEntity") as mock_enemy:
            mock_cache.get.return_value = npc_corp_ids or set()
            mock_cache.set = MagicMock()
            mock_bl.is_available.return_value = False
            mock_bl.get_blacklisted_character_ids.return_value = set()
            mock_enemy.objects.filter.return_value.values_list.return_value = set()

            engine = _make_engine(
                policy=policy, npc_corp_ids=npc_corp_ids,
                type_info_map=type_info_map, char_info_map=char_info_map,
                resolve_names_map=resolve_names_map,
            )
            return engine._detect_awox(
                audit_run=MagicMock(),
                character_id=character_id,
                ordered_character_ids=ordered_character_ids,
                character_name_map=character_name_map,
                all_kills=kills,
            )

    # --- Qualification paths ---

    def test_solo_deliberate_awox_same_corp(self):
        """Solo awox: 1 attacker, final blow, 100% damage, same corp victim."""
        type_info = {
            670: {"group_id": 29, "name": "Capsule"},  # victim ship (pod)
            3242: {"group_id": 52, "name": "Warp Disruptor I"},  # weapon
            12013: {"group_id": 894, "name": "Broadsword"},  # attacker ship
        }
        kill = _make_kill(
            victim_ship_type_id=670, victim_ship_group_id=29,
            attacker_damage_done=10000, victim_damage_taken=10000,
            attacker_final_blow=True, attacker_count=1,
            attacker_weapon_type_id=3242, attacker_weapon_group_id=52,
            attacker_ship_type_id=12013, attacker_ship_group_id=894,
            zkb_value=50000000,
        )
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNotNone(result)
        self.assertIn("awox kill(s)", result["details"])
        self.assertEqual(result["severity"], "medium")
        evidence = dict(result["evidence"])
        kills_data = json.loads(evidence["awox_killmails"])
        self.assertEqual(len(kills_data), 1)
        self.assertEqual(kills_data[0]["kind"], "friendly_fire_damage")

    def test_same_alliance_awox(self):
        """Friendly-fire across same alliance."""
        kill = _make_kill(
            attacker_corp_id=20001, victim_corp_id=20002,
            attacker_alliance_id=30000, victim_alliance_id=30000,
            attacker_damage_done=8000, victim_damage_taken=10000,
            attacker_final_blow=True, attacker_count=2,
            attacker_weapon_type_id=999, attacker_weapon_group_id=999,
            attacker_ship_type_id=999, attacker_ship_group_id=999,
            victim_ship_type_id=670,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNotNone(result)
        kills_data = json.loads(dict(result["evidence"])["awox_killmails"])
        self.assertEqual(kills_data[0]["kind"], "friendly_fire_damage")

    def test_tackle_override_warp_scrambler(self):
        """Zero damage with warp scrambler (group 52) qualifies as tackle awox."""
        kill = _make_kill(
            attacker_damage_done=0, victim_damage_taken=10000,
            attacker_final_blow=False, attacker_count=3,
            attacker_weapon_type_id=3242, attacker_weapon_group_id=52,
            attacker_ship_type_id=999, attacker_ship_group_id=999,
            victim_ship_type_id=670,
        )
        type_info = {
            670: {"group_id": 29, "name": "Capsule"},
            3242: {"group_id": 52, "name": "Warp Disruptor I"},
        }
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNotNone(result)
        kills_data = json.loads(dict(result["evidence"])["awox_killmails"])
        self.assertEqual(kills_data[0]["kind"], "friendly_fire_tackle")

    def test_tackle_override_wdfg(self):
        """Zero damage with WDFG (group 899) qualifies as tackle awox."""
        kill = _make_kill(
            attacker_damage_done=0, victim_damage_taken=10000,
            attacker_final_blow=False, attacker_count=3,
            attacker_weapon_type_id=4248, attacker_weapon_group_id=899,
            attacker_ship_type_id=12013, attacker_ship_group_id=894,
            victim_ship_type_id=670,
        )
        type_info = {
            670: {"group_id": 29, "name": "Capsule"},
            4248: {"group_id": 899, "name": "Warp Disruption Field Generator II"},
        }
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNotNone(result)
        kills_data = json.loads(dict(result["evidence"])["awox_killmails"])
        self.assertEqual(kills_data[0]["kind"], "friendly_fire_tackle")

    def test_hic_ship_override_zero_damage(self):
        """HIC ship (group 894) with non-tackle weapon and zero damage qualifies."""
        kill = _make_kill(
            attacker_damage_done=0, victim_damage_taken=10000,
            attacker_final_blow=False, attacker_count=3,
            attacker_weapon_type_id=555, attacker_weapon_group_id=555,
            attacker_ship_type_id=12013, attacker_ship_group_id=894,
            victim_ship_type_id=670,
        )
        type_info = {
            670: {"group_id": 29, "name": "Capsule"},
            12013: {"group_id": 894, "name": "Broadsword"},
        }
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNotNone(result)
        kills_data = json.loads(dict(result["evidence"])["awox_killmails"])
        self.assertEqual(kills_data[0]["kind"], "friendly_fire_hic")

    # --- Exclusion paths ---

    def test_whoring_exclusion(self):
        """Low damage, not final blow, non-tackle, non-HIC → no finding."""
        kill = _make_kill(
            attacker_damage_done=100, victim_damage_taken=10000,
            attacker_final_blow=False, attacker_count=5,
            attacker_weapon_type_id=555, attacker_weapon_group_id=555,
            attacker_ship_type_id=555, attacker_ship_group_id=555,
            victim_ship_type_id=670,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNone(result)

    def test_structure_exclusion(self):
        """Victim with no character_id (structure) → no finding."""
        kill = _make_kill(victim_char_id=None, victim_ship_type_id=35832)
        kill["victim"]["character_id"] = None
        type_info = {35832: {"group_id": 1657, "name": "Astrahus"}}
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNone(result)

    def test_non_friendly_victim(self):
        """Different corp and alliance → no finding."""
        kill = _make_kill(
            attacker_corp_id=20001, victim_corp_id=20002,
            attacker_alliance_id=30001, victim_alliance_id=30002,
            victim_ship_type_id=670,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNone(result)

    def test_self_kill_across_alts_skipped(self):
        """Victim is one of the audited character's own declared alts → skipped."""
        kill = _make_kill(
            victim_char_id=88888,  # another declared alt
            victim_ship_type_id=670,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect(
            [kill],
            ordered_character_ids=[99999, 88888],
            character_name_map={99999: "Main", 88888: "Alt", 55555: "Victim"},
            type_info_map=type_info,
        )
        self.assertIsNone(result)

    def test_throwaway_ship_exclusion(self):
        """Corvette victim (group 237) with zkb value < min → no finding."""
        kill = _make_kill(
            victim_ship_type_id=32880,  # Impairor (corvette)
            zkb_value=500000,  # 500K ISK, below 10M default
        )
        type_info = {32880: {"group_id": 237, "name": "Impairor"}}
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNone(result)

    def test_throwaway_ship_not_triggered_high_value(self):
        """Corvette victim with zkb value >= min → finding created."""
        kill = _make_kill(
            victim_ship_type_id=32880,
            zkb_value=50000000,  # 50M ISK, above 10M default
        )
        type_info = {32880: {"group_id": 237, "name": "Impairor"}}
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNotNone(result)

    def test_pod_exemption_from_throwaway(self):
        """Pod victim (group 29) with high implant value → finding created."""
        kill = _make_kill(
            victim_ship_type_id=670,  # Capsule
            zkb_value=2000000000,  # 2B ISK (implants)
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNotNone(result)

    def test_large_fleet_crossfire_exclusion(self):
        """Large fleet with hostiles, low damage, not final, not tackle/HIC → excluded."""
        # 15 attackers, one is an enemy character
        extra = []
        for i in range(13):
            extra.append({
                "character_id": 70000 + i,
                "corporation_id": 20000,
                "damage_done": 500,
                "final_blow": False,
                "weapon_type_id": 555,
                "ship_type_id": 555,
            })
        # Enemy attacker
        extra.append({
            "character_id": 12345,  # enemy
            "corporation_id": 99000,
            "damage_done": 5000,
            "final_blow": True,
            "weapon_type_id": 555,
            "ship_type_id": 555,
        })
        kill = _make_kill(
            attacker_damage_done=200, victim_damage_taken=10000,
            attacker_final_blow=False, attacker_count=15,
            attacker_weapon_type_id=555, attacker_weapon_group_id=555,
            attacker_ship_type_id=555, attacker_ship_group_id=555,
            victim_ship_type_id=670,
            extra_attackers=extra,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}

        with patch("allianceauth_securityaudit.services.audit_analysis.awox.cache") as mock_cache, \
             patch("allianceauth_securityaudit.services.audit_analysis.awox.BlacklistAdapter") as mock_bl, \
             patch("allianceauth_securityaudit.services.audit_analysis.awox.EnemyEntity") as mock_enemy:
            mock_cache.get.return_value = set()
            mock_cache.set = MagicMock()
            mock_bl.is_available.return_value = False
            mock_bl.get_blacklisted_character_ids.return_value = set()
            # EnemyEntity returns enemy character 12345
            mock_enemy.objects.filter.return_value.values_list.return_value = {12345}

            engine = _make_engine(type_info_map=type_info)
            result = engine._detect_awox(
                audit_run=MagicMock(),
                character_id=99999,
                ordered_character_ids=[99999],
                character_name_map={99999: "AwoxAlt", 55555: "Victim"},
                all_kills=[kill],
            )
        self.assertIsNone(result)

    def test_large_fleet_no_hostiles_still_flagged(self):
        """Large fleet friendly fire with NO hostiles → still flagged."""
        extra = []
        for i in range(14):
            extra.append({
                "character_id": 70000 + i,
                "corporation_id": 20000,  # same corp, friendly
                "damage_done": 500,
                "final_blow": False,
                "weapon_type_id": 555,
                "ship_type_id": 555,
            })
        kill = _make_kill(
            attacker_damage_done=8000, victim_damage_taken=10000,
            attacker_final_blow=True, attacker_count=15,
            attacker_weapon_type_id=555, attacker_weapon_group_id=555,
            attacker_ship_type_id=555, attacker_ship_group_id=555,
            victim_ship_type_id=670,
            extra_attackers=extra,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNotNone(result)

    # --- Blue scouting ---

    def test_blue_scouting_via_corp(self):
        """NPC-corp alt kills someone in main's corp → blue scouting."""
        # Attacker (alt) in NPC corp 1000, victim in corp 20000
        # Main (char 11111) is in corp 20000
        kill = _make_kill(
            attacker_char_id=99999, attacker_corp_id=1000,  # NPC corp
            victim_corp_id=20000,
            attacker_damage_done=10000, victim_damage_taken=10000,
            attacker_final_blow=True, attacker_count=1,
            attacker_weapon_type_id=555, attacker_weapon_group_id=555,
            attacker_ship_type_id=555, attacker_ship_group_id=555,
            victim_ship_type_id=670,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        char_info = {
            11111: {"corporation_id": 20000, "alliance_id": None},
        }
        result = self._run_detect(
            [kill],
            ordered_character_ids=[99999, 11111],
            character_name_map={99999: "AwoxAlt", 11111: "Main", 55555: "Victim"},
            npc_corp_ids={1000},
            type_info_map=type_info,
            char_info_map=char_info,
        )
        self.assertIsNotNone(result)
        kills_data = json.loads(dict(result["evidence"])["awox_killmails"])
        self.assertEqual(kills_data[0]["kind"], "blue_scouting_damage")
        self.assertEqual(kills_data[0]["friendly_path"], "blue_scouting")
        self.assertEqual(kills_data[0]["friendly_link_char_id"], 11111)

    def test_blue_scouting_via_alliance(self):
        """NPC-corp alt kills someone in alt's alliance → blue scouting."""
        kill = _make_kill(
            attacker_char_id=99999, attacker_corp_id=1000,  # NPC corp
            victim_corp_id=20002, victim_alliance_id=30000,
            attacker_damage_done=10000, victim_damage_taken=10000,
            attacker_final_blow=True, attacker_count=1,
            attacker_weapon_type_id=555, attacker_weapon_group_id=555,
            attacker_ship_type_id=555, attacker_ship_group_id=555,
            victim_ship_type_id=670,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        char_info = {
            11111: {"corporation_id": 20001, "alliance_id": 30000},
        }
        result = self._run_detect(
            [kill],
            ordered_character_ids=[99999, 11111],
            character_name_map={99999: "AwoxAlt", 11111: "Main", 55555: "Victim"},
            npc_corp_ids={1000},
            type_info_map=type_info,
            char_info_map=char_info,
        )
        self.assertIsNotNone(result)
        kills_data = json.loads(dict(result["evidence"])["awox_killmails"])
        self.assertEqual(kills_data[0]["kind"], "blue_scouting_damage")
        self.assertEqual(kills_data[0]["friendly_link_type"], "alliance")

    def test_blue_scouting_not_triggered_no_match(self):
        """NPC-corp alt, no audited char in victim's corp/alliance → no finding."""
        kill = _make_kill(
            attacker_char_id=99999, attacker_corp_id=1000,  # NPC corp
            victim_corp_id=20002, victim_alliance_id=30002,
            attacker_damage_done=10000, victim_damage_taken=10000,
            attacker_final_blow=True, attacker_count=1,
            victim_ship_type_id=670,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        char_info = {
            11111: {"corporation_id": 20001, "alliance_id": 30001},  # different
        }
        result = self._run_detect(
            [kill],
            ordered_character_ids=[99999, 11111],
            character_name_map={99999: "AwoxAlt", 11111: "Main", 55555: "Victim"},
            npc_corp_ids={1000},
            type_info_map=type_info,
            char_info_map=char_info,
        )
        self.assertIsNone(result)

    def test_blue_scouting_not_triggered_player_corp(self):
        """Attacker in player corp, main in victim's corp → primary path, not blue scouting."""
        kill = _make_kill(
            attacker_char_id=99999, attacker_corp_id=20000,  # player corp, same as victim
            victim_corp_id=20000,
            attacker_damage_done=10000, victim_damage_taken=10000,
            attacker_final_blow=True, attacker_count=1,
            victim_ship_type_id=670,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect(
            [kill],
            ordered_character_ids=[99999, 11111],
            character_name_map={99999: "AwoxAlt", 11111: "Main", 55555: "Victim"},
            npc_corp_ids={1000},  # 20000 is NOT an NPC corp
            type_info_map=type_info,
        )
        self.assertIsNotNone(result)
        kills_data = json.loads(dict(result["evidence"])["awox_killmails"])
        self.assertEqual(kills_data[0]["friendly_path"], "direct")
        self.assertEqual(kills_data[0]["kind"], "friendly_fire_damage")

    # --- Scoring ---

    def test_super_titan_bonus_higher_than_carrier(self):
        """Titan victim (+25) should score higher than carrier victim (+15)."""
        def _make_capital_kill(victim_ship_group_id, victim_ship_type_id):
            return _make_kill(
                victim_ship_type_id=victim_ship_type_id,
                attacker_damage_done=10000, victim_damage_taken=10000,
                attacker_final_blow=True, attacker_count=1,
                attacker_weapon_type_id=555, attacker_weapon_group_id=555,
                attacker_ship_type_id=555, attacker_ship_group_id=555,
                zkb_value=100000000000,
            )

        # Titan (group 30)
        titan_type_info = {
            23773: {"group_id": 30, "name": "Ragnarok"},  # victim ship
        }
        titan_kill = _make_capital_kill(30, 23773)
        titan_result = self._run_detect([titan_kill], type_info_map=titan_type_info)
        self.assertIsNotNone(titan_result)
        titan_kills = json.loads(dict(titan_result["evidence"])["awox_killmails"])
        titan_score = titan_kills[0]["kill_score"]

        # Carrier (group 547)
        carrier_type_info = {
            23757: {"group_id": 547, "name": "Archon"},  # victim ship
        }
        carrier_kill = _make_capital_kill(547, 23757)
        carrier_result = self._run_detect([carrier_kill], type_info_map=carrier_type_info)
        self.assertIsNotNone(carrier_result)
        carrier_kills = json.loads(dict(carrier_result["evidence"])["awox_killmails"])
        carrier_score = carrier_kills[0]["kill_score"]

        self.assertGreater(titan_score, carrier_score,
                           f"Titan score ({titan_score}) should be higher than carrier score ({carrier_score})")

    def test_repeat_pattern_severity_escalation(self):
        """2 kills → high, 4 kills → critical."""
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        base_kill = _make_kill(victim_ship_type_id=670, zkb_value=50000000)

        # 2 kills → high
        kills_2 = [
            _make_kill(killmail_id=1000001, victim_ship_type_id=670, zkb_value=50000000),
            _make_kill(killmail_id=1000002, victim_char_id=55556, victim_ship_type_id=670, zkb_value=50000000),
        ]
        result_2 = self._run_detect(kills_2, type_info_map=type_info,
                                    character_name_map={99999: "AwoxAlt", 55555: "V1", 55556: "V2"})
        self.assertEqual(result_2["severity"], "high")

        # 4 kills → critical
        kills_4 = [
            _make_kill(killmail_id=1000001, victim_ship_type_id=670, zkb_value=50000000),
            _make_kill(killmail_id=1000002, victim_char_id=55556, victim_ship_type_id=670, zkb_value=50000000),
            _make_kill(killmail_id=1000003, victim_char_id=55557, victim_ship_type_id=670, zkb_value=50000000),
            _make_kill(killmail_id=1000004, victim_char_id=55558, victim_ship_type_id=670, zkb_value=50000000),
        ]
        result_4 = self._run_detect(kills_4, type_info_map=type_info,
                                    character_name_map={99999: "AwoxAlt", 55555: "V1", 55556: "V2", 55557: "V3", 55558: "V4"})
        self.assertEqual(result_4["severity"], "critical")

    def test_score_cap(self):
        """Total score should be capped at AWOX_SCORE_CAP."""
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        kills = [
            _make_kill(killmail_id=1000000 + i, victim_char_id=55555 + i,
                       victim_ship_type_id=670, zkb_value=50000000)
            for i in range(10)
        ]
        char_map = {99999: "AwoxAlt"}
        for i in range(10):
            char_map[55555 + i] = f"V{i}"
        result = self._run_detect(kills, type_info_map=type_info, character_name_map=char_map)
        self.assertLessEqual(result["score"], AWOX_SCORE_CAP)

    # --- Recency ---

    def test_recency_weighting_old_kill_excluded(self):
        """Kill older than lookback → excluded."""
        old_time = timezone.now() - timedelta(days=400)
        kill = _make_kill(
            kill_time=old_time,
            victim_ship_type_id=670,
            zkb_value=50000000,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect([kill], type_info_map=type_info,
                                  policy=_FakePolicy(awox_lookback_days=180))
        self.assertIsNone(result)

    # --- Evidence structure ---

    def test_evidence_includes_zkill_links(self):
        """Evidence entries must contain zkill_url."""
        kill = _make_kill(
            killmail_id=12345678,
            victim_ship_type_id=670,
            zkb_value=50000000,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect([kill], type_info_map=type_info)
        kills_data = json.loads(dict(result["evidence"])["awox_killmails"])
        self.assertEqual(kills_data[0]["zkill_url"], "https://zkillboard.com/kill/12345678/")

    def test_details_string_specifies_kind(self):
        """Details string should mention the awox kind."""
        kill = _make_kill(
            victim_ship_type_id=670,
            attacker_damage_done=10000, victim_damage_taken=10000,
            attacker_final_blow=True,
            zkb_value=50000000,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}
        result = self._run_detect([kill], type_info_map=type_info)
        self.assertIn("friendly-fire", result["details"].lower())

    # --- Policy override ---

    def test_policy_override_min_damage_share(self):
        """Per-run awox_min_damage_share override should be respected."""
        # With min_damage_share=0.90, a kill with 60% damage and not final blow should be excluded
        kill = _make_kill(
            attacker_damage_done=6000, victim_damage_taken=10000,
            attacker_final_blow=False, attacker_count=1,
            attacker_weapon_type_id=555, attacker_weapon_group_id=555,
            attacker_ship_type_id=555, attacker_ship_group_id=555,
            victim_ship_type_id=670,
            zkb_value=50000000,
        )
        type_info = {670: {"group_id": 29, "name": "Capsule"}}

        # Default (0.50): 60% >= 50% → qualifies
        result_default = self._run_detect([kill], type_info_map=type_info)
        self.assertIsNotNone(result_default)

        # Override (0.90): 60% < 90% and not final blow, not tackle, not HIC → excluded
        result_override = self._run_detect(
            [kill], type_info_map=type_info,
            policy=_FakePolicy(awox_min_damage_share=Decimal("0.90")),
        )
        self.assertIsNone(result_override)


class KindLabelsTests(SimpleTestCase):
    """Verify KIND_LABELS covers all expected kinds."""

    def test_all_kinds_have_labels(self):
        expected_kinds = {
            "friendly_fire_damage",
            "friendly_fire_tackle",
            "friendly_fire_hic",
            "blue_scouting_damage",
            "blue_scouting_tackle",
            "blue_scouting_hic",
        }
        self.assertEqual(set(KIND_LABELS.keys()), expected_kinds)
